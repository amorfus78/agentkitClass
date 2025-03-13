"""
Utilitaires pour la tokenization et le comptage de tokens.

Ce module fournit des fonctions pour estimer et compter le nombre de tokens
dans les textes, ce qui est utile pour gérer les limites de contexte des LLMs.
"""
import logging
from typing import Optional, Union

# Essayer d'importer tiktoken (bibliothèque OpenAI pour le comptage précis)
try:
    import tiktoken
    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False

logger = logging.getLogger(__name__)

# Modèles et leurs encodeurs associés
ENCODER_MAPPING = {
    "gpt-3.5-turbo": "cl100k_base",
    "gpt-4": "cl100k_base",
    "gpt-4-turbo": "cl100k_base",
    "text-embedding-ada-002": "cl100k_base",
}

# Cache des encodeurs pour éviter de les recréer
_ENCODERS = {}


def get_token_length(text: str, model: Optional[str] = None) -> int:
    """
    Compte le nombre de tokens dans un texte.
    
    Args:
        text: Texte à tokenizer
        model: Modèle à utiliser pour la tokenization (optionnel)
        
    Returns:
        Nombre de tokens
    """
    if not text:
        return 0
        
    # Utiliser tiktoken si disponible
    if TIKTOKEN_AVAILABLE:
        try:
            return len(get_encoder(model).encode(text))
        except Exception as e:
            logger.warning(f"Erreur lors du comptage des tokens avec tiktoken: {e}")
    
    # Fallback: estimation approximative (4 caractères ~ 1 token)
    return len(text) // 4 + 1


def get_encoder(model: Optional[str] = None):
    """
    Récupère l'encodeur approprié pour un modèle donné.
    
    Args:
        model: Nom du modèle
        
    Returns:
        Encodeur tiktoken
    """
    if not TIKTOKEN_AVAILABLE:
        raise ImportError("tiktoken n'est pas installé")
        
    # Utiliser cl100k_base par défaut (utilisé par GPT-3.5 et GPT-4)
    encoding_name = "cl100k_base"
    
    # Si un modèle est spécifié, utiliser son encodeur
    if model:
        encoding_name = ENCODER_MAPPING.get(model, "cl100k_base")
    
    # Utiliser l'encodeur en cache ou en créer un nouveau
    if encoding_name not in _ENCODERS:
        _ENCODERS[encoding_name] = tiktoken.get_encoding(encoding_name)
        
    return _ENCODERS[encoding_name]


def truncate_to_token_limit(text: str, max_tokens: int, model: Optional[str] = None) -> str:
    """
    Tronque un texte pour qu'il ne dépasse pas une limite de tokens.
    
    Args:
        text: Texte à tronquer
        max_tokens: Nombre maximum de tokens
        model: Modèle à utiliser pour la tokenization
        
    Returns:
        Texte tronqué
    """
    if not TIKTOKEN_AVAILABLE:
        # Estimation approximative si tiktoken n'est pas disponible
        if len(text) // 4 <= max_tokens:
            return text
        return text[:max_tokens * 4]
    
    encoder = get_encoder(model)
    tokens = encoder.encode(text)
    
    if len(tokens) <= max_tokens:
        return text
        
    # Tronquer les tokens et décoder
    truncated_tokens = tokens[:max_tokens]
    return encoder.decode(truncated_tokens) 