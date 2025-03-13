"""
Optimisations pour la gestion de la mémoire de conversation.

Ce module fournit des fonctions pour:
1. Réduire la latence Redis en utilisant des pipelines pour les opérations batch
2. Ajuster dynamiquement la taille de l'historique pour économiser des tokens LLM
"""
import json
import logging
import time
from typing import Dict, List, Optional, Tuple, Union, Any

import redis.asyncio as aioredis
from langchain.memory import ConversationTokenBufferMemory
from langchain.schema import AIMessage, HumanMessage, BaseMessage

from app.utils.tokenization import get_token_length

logger = logging.getLogger(__name__)


async def batch_save_context(
    memory: ConversationTokenBufferMemory, 
    chat_pairs: List[Tuple[str, str]],
    redis_client: aioredis.Redis,
    conversation_id: str,
    ttl: int = 3600  # 1 heure par défaut
) -> None:
    """
    Sauvegarde en batch l'historique de conversation dans Redis.
    
    Cette fonction réduit considérablement la latence Redis en:
    1. Accumulant les messages à sauvegarder
    2. Exécutant les opérations en une seule transaction Redis
    
    Args:
        memory: Instance de ConversationTokenBufferMemory
        chat_pairs: Liste de tuples (message_utilisateur, message_ai)
        redis_client: Client Redis asynchrone
        conversation_id: Identifiant de la conversation
        ttl: Durée de vie des messages en cache (en secondes)
    """
    start_time = time.time()
    
    # Ajouter les messages à la mémoire locale
    for user_msg, ai_msg in chat_pairs:
        memory.save_context(
            inputs={"input": user_msg},
            outputs={"output": ai_msg}
        )
    
    # Utiliser un pipeline Redis pour les opérations batch
    async with redis_client.pipeline(transaction=True) as pipe:
        # Ajouter chaque paire au pipeline
        for user_msg, ai_msg in chat_pairs:
            key = f"chat_history:{conversation_id}:{int(time.time())}"
            pipe.set(key, ai_msg, ex=ttl)
            
        # Exécuter toutes les opérations en une seule transaction
        await pipe.execute()
    
    elapsed = time.time() - start_time
    logger.debug(f"Batch operation completed in {elapsed:.3f}s for {len(chat_pairs)} messages")


async def dynamic_memory_reduction(
    memory: ConversationTokenBufferMemory,
    max_token_limit: int,
    reduction_threshold: float = 0.85,
    aggressive: bool = False
) -> int:
    """
    Ajuste dynamiquement la taille de l'historique de conversation.
    
    Cette fonction:
    1. Vérifie si l'historique approche de la limite de tokens
    2. Réduit intelligemment l'historique en conservant les messages importants
    3. Retourne le nombre de tokens économisés
    
    Args:
        memory: Instance de ConversationTokenBufferMemory
        max_token_limit: Limite maximale de tokens
        reduction_threshold: Seuil de déclenchement (0.85 = 85% de la limite)
        aggressive: Si True, réduit plus agressivement l'historique
        
    Returns:
        Nombre de tokens économisés
    """
    # Obtenir les messages actuels
    messages = memory.chat_memory.messages
    
    # Estimer la taille en tokens
    token_count = sum(get_token_length(msg.content) for msg in messages)
    
    # Vérifier si on dépasse le seuil
    threshold = max_token_limit * reduction_threshold
    if token_count <= threshold:
        return 0  # Pas besoin de réduction
    
    # Conserver les messages système et les plus récents
    system_messages = [m for m in messages if not isinstance(m, (HumanMessage, AIMessage))]
    
    # Extraire les paires de conversation (humain-AI)
    conversation_pairs = []
    for i in range(0, len(messages) - 1, 2):
        if i + 1 < len(messages):
            if isinstance(messages[i], HumanMessage) and isinstance(messages[i+1], AIMessage):
                conversation_pairs.append((messages[i], messages[i+1]))
    
    # Toujours conserver les 3 dernières paires
    keep_recent = min(3, len(conversation_pairs))
    recent_pairs = conversation_pairs[-keep_recent:]
    
    # Échantillonner les paires plus anciennes
    older_pairs = conversation_pairs[:-keep_recent] if len(conversation_pairs) > keep_recent else []
    
    # Niveau de réduction selon le mode
    sample_rate = 0.3 if aggressive else 0.5
    
    # Échantillonner les paires plus anciennes
    if older_pairs:
        sample_count = max(1, int(len(older_pairs) * sample_rate))
        stride = max(1, len(older_pairs) // sample_count)
        sampled_pairs = [older_pairs[i] for i in range(0, len(older_pairs), stride)]
    else:
        sampled_pairs = []
    
    # Reconstruire la liste de messages
    new_messages = system_messages.copy()
    for pair in sampled_pairs + recent_pairs:
        new_messages.extend(pair)
    
    # Calculer les tokens économisés
    new_token_count = sum(get_token_length(msg.content) for msg in new_messages)
    tokens_saved = token_count - new_token_count
    
    # Mettre à jour la mémoire
    memory.chat_memory.messages = new_messages
    
    logger.info(
        f"Reduced memory from {token_count} to {new_token_count} tokens "
        f"(saved {tokens_saved} tokens, {len(messages) - len(new_messages)} messages)"
    )
    
    return tokens_saved


async def optimize_memory_usage(
    memory: ConversationTokenBufferMemory,
    redis_client: aioredis.Redis,
    conversation_id: str,
    new_messages: List[Tuple[str, str]],
    max_token_limit: int = 4000
) -> Dict[str, Any]:
    """
    Fonction complète pour optimiser l'utilisation de la mémoire.
    
    Cette fonction:
    1. Sauvegarde les nouveaux messages en batch
    2. Réduit dynamiquement l'historique si nécessaire
    3. Retourne des statistiques sur l'opération
    
    Args:
        memory: Instance de ConversationTokenBufferMemory
        redis_client: Client Redis asynchrone
        conversation_id: Identifiant de la conversation
        new_messages: Nouveaux messages à ajouter [(user_msg, ai_msg), ...]
        max_token_limit: Limite maximale de tokens
        
    Returns:
        Statistiques sur l'opération
    """
    start_time = time.time()
    
    # 1. Sauvegarder en batch
    await batch_save_context(
        memory=memory,
        chat_pairs=new_messages,
        redis_client=redis_client,
        conversation_id=conversation_id
    )
    
    # 2. Réduire dynamiquement si nécessaire
    tokens_saved = await dynamic_memory_reduction(
        memory=memory,
        max_token_limit=max_token_limit
    )
    
    # 3. Calculer les statistiques
    elapsed = time.time() - start_time
    
    return {
        "elapsed_time": elapsed,
        "messages_processed": len(new_messages),
        "tokens_saved": tokens_saved,
        "current_memory_size": len(memory.chat_memory.messages),
        "optimization_applied": tokens_saved > 0
    } 