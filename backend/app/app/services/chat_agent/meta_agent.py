# -*- coding: utf-8 -*-
from typing import Callable, List, Optional, Dict, Tuple

from langchain.agents import AgentExecutor
from langchain.base_language import BaseLanguageModel
from langchain.memory import ChatMessageHistory, ConversationTokenBufferMemory
from langchain.schema import AIMessage, HumanMessage

from app.core.config import settings
from app.schemas.agent_schema import AgentConfig
from app.schemas.tool_schema import LLMType
from app.services.chat_agent.helpers.llm import get_llm
from app.services.chat_agent.router_agent.SimpleRouterAgent import SimpleRouterAgent
from app.services.chat_agent.tools.tools import get_tools
from app.utils.config_loader import get_agent_config

import logging

logger = logging.getLogger(__name__)

# Memory cache to avoid reprocessing the same messages
# Key: (conversation_id, message_count), Value: ConversationTokenBufferMemory
_memory_cache: Dict[Tuple[str, int], ConversationTokenBufferMemory] = {}

def get_conv_token_buffer_memory(
    chat_messages: List[AIMessage | HumanMessage],
    api_key: str,
    conversation_id: str = None,  # Add optional conversation_id for caching
) -> ConversationTokenBufferMemory:
    """
    Get a ConversationTokenBufferMemory from a list of chat messages.

    This function takes a list of chat messages and returns a ConversationTokenBufferMemory object.
    If a conversation_id is provided and there's a cached memory with fewer messages,
    it will update the cached memory with only the new messages, improving performance.

    Args:
        chat_messages (List[Union[AIMessage, HumanMessage]]): The list of chat messages.
        api_key (str): The API key.
        conversation_id (str, optional): The conversation ID for caching. Defaults to None.

    Returns:
        ConversationTokenBufferMemory: The ConversationTokenBufferMemory object.
    """
    # If no conversation_id provided, or empty message list, create from scratch
    if not conversation_id or not chat_messages:
        return _create_memory_from_scratch(chat_messages, api_key)
    
    # Check if we have a cache entry for this conversation
    msg_count = len(chat_messages)
    cache_key = (conversation_id, msg_count)
    
    # Exact match in cache - return the cached memory
    if cache_key in _memory_cache:
        logger.info(f"Using cached memory for conversation {conversation_id} with {msg_count} messages")
        return _memory_cache[cache_key]
    
    # Look for the most recent cached memory with fewer messages
    prev_msg_counts = [k[1] for k in _memory_cache.keys() if k[0] == conversation_id and k[1] < msg_count]
    
    if prev_msg_counts:
        # Find the most recent (largest) message count
        prev_count = max(prev_msg_counts)
        prev_key = (conversation_id, prev_count)
        prev_memory = _memory_cache[prev_key]
        
        # Only process the new messages since last time
        new_messages = chat_messages[prev_count:]
        logger.info(f"Updating cached memory with {len(new_messages)} new messages")
        
        # Update the memory with new messages
        memory = _update_memory(prev_memory, new_messages)
        
        # Cache the updated memory
        _memory_cache[cache_key] = memory
        return memory
    
    # No previous cache, create from scratch
    memory = _create_memory_from_scratch(chat_messages, api_key)
    _memory_cache[cache_key] = memory
    return memory

def _create_memory_from_scratch(
    chat_messages: List[AIMessage | HumanMessage],
    api_key: str,
) -> ConversationTokenBufferMemory:
    """Create a new memory object from scratch with all messages."""
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

    # Process all messages safely
    _process_messages(memory, chat_messages)
    return memory

def _update_memory(
    memory: ConversationTokenBufferMemory,
    new_messages: List[AIMessage | HumanMessage],
) -> ConversationTokenBufferMemory:
    """Update an existing memory with only new messages."""
    _process_messages(memory, new_messages)
    return memory

def _process_messages(
    memory: ConversationTokenBufferMemory,
    messages: List[AIMessage | HumanMessage],
) -> None:
    """Safely process messages and add them to memory."""
    i = 0
    while i < len(messages):
        # Case 1: Human message followed by AI message
        if (isinstance(messages[i], HumanMessage) and 
            i + 1 < len(messages) and 
            isinstance(messages[i + 1], AIMessage)):
            
            memory.save_context(
                inputs={"input": messages[i].content},
                outputs={"output": messages[i + 1].content},
            )
            i += 2  # Skip both messages
        
        # Case 2: Any other message type
        else:
            memory.save_context(
                inputs={"input": messages[i].content},
                outputs={"output": ""},
            )
            i += 1


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
