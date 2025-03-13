# -*- coding: utf-8 -*-
from typing import Callable, List, Optional, Tuple

from langchain.agents import AgentExecutor
from langchain.base_language import BaseLanguageModel
from langchain.memory import ChatMessageHistory, ConversationTokenBufferMemory
from langchain.schema import AIMessage, HumanMessage

from app.core.config import settings
from app.schemas.agent_schema import AgentConfig
from app.schemas.tool_schema import LLMType
from app.services.chat_agent.helpers.llm import get_llm
from app.services.chat_agent.helpers.memory_optimizer import batch_save_context, dynamic_memory_reduction
from app.services.chat_agent.router_agent.SimpleRouterAgent import SimpleRouterAgent
from app.services.chat_agent.tools.tools import get_tools
from app.utils.config_loader import get_agent_config
from app.api.deps import get_redis_client
from app.utils.uuid7 import uuid7


async def get_conv_token_buffer_memory(
    chat_messages: List[AIMessage | HumanMessage],
    api_key: str,
    conversation_id: Optional[str] = None,
) -> ConversationTokenBufferMemory:
    """
    Get a ConversationTokenBufferMemory from a list of chat messages.

    Version optimisée qui utilise:
    1. Des opérations batch Redis pour réduire la latence
    2. Une réduction dynamique de l'historique pour économiser des tokens

    Args:
        chat_messages (List[Union[AIMessage, HumanMessage]]): The list of chat messages.
        api_key (str): The API key.
        conversation_id (Optional[str]): ID de la conversation pour le cache Redis.

    Returns:
        ConversationTokenBufferMemory: The ConversationTokenBufferMemory object.
    """
    agent_config = get_agent_config()
    llm = get_llm(
        agent_config.common.llm,
        api_key=api_key,
    )
    chat_history = ChatMessageHistory()
    memory = ConversationTokenBufferMemory(
        memory_key="chat_history",
        return_messages=True,
        max_token_limit=agent_config.common.max_token_length,
        llm=llm,
        chat_memory=chat_history,
    )

    # Si pas de messages, retourner la mémoire vide
    if not chat_messages:
        return memory
        
    # Générer un ID de conversation si non fourni
    if conversation_id is None:
        conversation_id = str(uuid7())
        
    # Préparer les paires de messages pour le traitement batch
    chat_pairs = []
    i = 0
    while i < len(chat_messages):
        if isinstance(chat_messages[i], HumanMessage):
            if i + 1 < len(chat_messages) and isinstance(chat_messages[i + 1], AIMessage):
                # Paire complète utilisateur-AI
                chat_pairs.append((chat_messages[i].content, chat_messages[i + 1].content))
                i += 2
            else:
                # Message utilisateur sans réponse
                chat_pairs.append((chat_messages[i].content, ""))
                i += 1
        else:
            # Message AI isolé
            chat_pairs.append((chat_messages[i].content, ""))
            i += 1
    
    # Obtenir le client Redis
    redis_client = await get_redis_client()
    
    # Sauvegarder en batch
    await batch_save_context(
        memory=memory,
        chat_pairs=chat_pairs,
        redis_client=redis_client,
        conversation_id=conversation_id
    )
    
    # Réduire dynamiquement si nécessaire
    await dynamic_memory_reduction(
        memory=memory,
        max_token_limit=agent_config.common.max_token_length
    )

    return memory


def create_meta_agent(
    agent_config: AgentConfig,
    get_llm_hook: Callable[[LLMType, Optional[str]], BaseLanguageModel] = get_llm,
) -> AgentExecutor:
    """
    Create a meta agent from a config.

    This function takes an AgentConfig object and creates a MetaAgent.
    It retrieves the language models and the list tools, with which a SimpleRouterAgent is created.
    Then, it returns an AgentExecutor.

    Args:
        agent_config (AgentConfig): The AgentConfig object.

    Returns:
        AgentExecutor: The AgentExecutor object.
    """
    api_key = agent_config.api_key
    if api_key is None or api_key == "":
        api_key = settings.OPENAI_API_KEY

    llm = get_llm_hook(
        agent_config.common.llm,
        api_key,
    )

    tools = get_tools(tools=agent_config.tools)
    simple_router_agent = SimpleRouterAgent.from_llm_and_tools(
        tools=tools,
        llm=llm,
        prompt_message=agent_config.prompt_message,
        system_context=agent_config.system_context,
        action_plans=agent_config.action_plans,
    )
    return AgentExecutor.from_agent_and_tools(
        agent=simple_router_agent,
        tools=tools,
        verbose=True,
        max_iterations=15,
        max_execution_time=300,
        early_stopping_method="generate",
        handle_parsing_errors=True,
    )
