"""
Service de cache Redis asynchrone optimisé.

Ce module fournit une implémentation de cache optimisée utilisant aioredis avec :
- Pipelines Redis pour les opérations atomiques multi-clés
- TTL dynamiques pour différents types de données
- Compression des valeurs de grande taille
- Méthodes utilitaires pour les scénarios courants
"""
import json
import logging
import time
import zlib
from enum import Enum
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, TypeVar, Union, cast

import redis.asyncio as aioredis
from fastapi import Depends, Request
from pydantic import BaseModel

from app.api.deps import get_redis_client
from app.core.config import settings

logger = logging.getLogger(__name__)

# Type générique pour les fonctions décorées
T = TypeVar("T")


class CacheCategory(str, Enum):
    """
    Catégories de cache avec des durées de vie (TTL) différentes.
    
    Cette enum permet de spécifier des TTL spécifiques selon le type de données,
    évitant ainsi de garder trop longtemps des données qui changent souvent.
    """
    # Données qui changent rarement (configurations, métadonnées)
    STATIC = "static"  
    
    # Données de référence qui peuvent changer (ex: listes de valeurs)
    REFERENCE = "reference"  
    
    # Données utilisateur qui changent régulièrement
    USER = "user"  
    
    # Données de courte durée utilisées pendant une session
    SESSION = "session"  
    
    # Données qui changent très fréquemment
    VOLATILE = "volatile"


class CacheSettings(BaseModel):
    """Configuration des TTL par catégorie de cache (en secondes)"""
    static: int = 86400 * 7  # 7 jours
    reference: int = 86400  # 1 jour
    user: int = 3600  # 1 heure
    session: int = 1800  # 30 minutes
    volatile: int = 300  # 5 minutes
    
    # Taille minimale (en octets) pour compresser les valeurs
    compression_threshold: int = 1024
    # Niveau de compression zlib (1-9, où 9 est max)
    compression_level: int = 6


class AsyncRedisService:
    """
    Service de cache Redis asynchrone optimisé pour les performances.
    
    Caractéristiques:
    - Pipelines Redis pour les opérations atomiques
    - TTL dynamiques basés sur les catégories de données
    - Compression automatique des grandes valeurs
    - Méthodes utilitaires pour les opérations courantes
    """
    
    def __init__(self, redis_client: aioredis.Redis):
        """
        Initialise le service avec un client Redis.
        
        Args:
            redis_client: Client Redis asynchrone
        """
        self.redis = redis_client
        self.settings = CacheSettings()
        
    def _get_ttl(self, category: CacheCategory) -> int:
        """Récupère le TTL en secondes pour une catégorie donnée."""
        return getattr(self.settings, category.value)
    
    def _format_key(self, key: str, prefix: Optional[str] = None) -> str:
        """Formate une clé avec un préfixe optionnel."""
        app_prefix = settings.CACHE_PREFIX
        if prefix:
            return f"{app_prefix}:{prefix}:{key}"
        return f"{app_prefix}:{key}"
    
    def _should_compress(self, value: bytes) -> bool:
        """Détermine si une valeur doit être compressée en fonction de sa taille."""
        return len(value) > self.settings.compression_threshold
    
    def _compress(self, value: bytes) -> bytes:
        """Compresse une valeur avec zlib."""
        return zlib.compress(value, level=self.settings.compression_level)
    
    def _decompress(self, value: bytes) -> bytes:
        """Décompresse une valeur compressée avec zlib."""
        try:
            return zlib.decompress(value)
        except zlib.error as e:
            logger.warning(f"Failed to decompress value: {e}")
            return value  # Renvoie la valeur d'origine en cas d'échec
    
    async def get(
        self, 
        key: str, 
        prefix: Optional[str] = None,
        default: Any = None,
        decompress: bool = True
    ) -> Any:
        """
        Récupère une valeur depuis le cache.
        
        Args:
            key: Clé du cache
            prefix: Préfixe optionnel
            default: Valeur par défaut si la clé n'existe pas
            decompress: Si True, décompresse la valeur si nécessaire
            
        Returns:
            La valeur en cache ou la valeur par défaut
        """
        formatted_key = self._format_key(key, prefix)
        value = await self.redis.get(formatted_key)
        
        if value is None:
            return default
        
        # Vérifier si la valeur est compressée (commence par les octets zlib)
        if decompress and value.startswith(b'x\x9c'):
            value = self._decompress(value)
        
        try:
            return json.loads(value)
        except (TypeError, json.JSONDecodeError):
            # Si la désérialisation JSON échoue, renvoyer la valeur brute
            return value.decode('utf-8') if isinstance(value, bytes) else value
    
    async def set(
        self,
        key: str,
        value: Any,
        category: CacheCategory = CacheCategory.USER,
        prefix: Optional[str] = None,
        ttl: Optional[int] = None,
    ) -> bool:
        """
        Met une valeur en cache avec TTL dynamique.
        
        Args:
            key: Clé du cache
            value: Valeur à mettre en cache
            category: Catégorie de cache pour le TTL
            prefix: Préfixe optionnel
            ttl: TTL personnalisé (remplace la catégorie si spécifié)
            
        Returns:
            True si l'opération a réussi
        """
        formatted_key = self._format_key(key, prefix)
        
        # Calculer le TTL effectif
        effective_ttl = ttl if ttl is not None else self._get_ttl(category)
        
        # Sérialiser et potentiellement compresser la valeur
        try:
            serialized = json.dumps(value).encode('utf-8')
            
            if self._should_compress(serialized):
                serialized = self._compress(serialized)
                # Stocker un indicateur de compression
                meta_key = f"{formatted_key}:meta"
                await self.redis.set(meta_key, "compressed", ex=effective_ttl)
                
            return await self.redis.set(formatted_key, serialized, ex=effective_ttl)
        except (TypeError, ValueError) as e:
            logger.error(f"Failed to cache value for key {formatted_key}: {e}")
            return False
    
    async def multi_get(
        self,
        keys: List[str],
        prefix: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Récupère plusieurs valeurs en une seule opération atomique.
        
        Utilise pipeline Redis pour réduire les allers-retours réseau.
        
        Args:
            keys: Liste des clés à récupérer
            prefix: Préfixe optionnel
            
        Returns:
            Dictionnaire {clé: valeur} des valeurs trouvées
        """
        if not keys:
            return {}
        
        formatted_keys = [self._format_key(key, prefix) for key in keys]
        
        # Créer un pipeline pour les opérations
        async with self.redis.pipeline() as pipe:
            # Ajouter toutes les opérations GET au pipeline
            for key in formatted_keys:
                pipe.get(key)
            
            # Exécuter le pipeline en une seule opération réseau
            values = await pipe.execute()
        
        result = {}
        for i, key in enumerate(keys):
            value = values[i]
            if value is not None:
                # Vérifier si la valeur est compressée
                if isinstance(value, bytes) and value.startswith(b'x\x9c'):
                    value = self._decompress(value)
                
                try:
                    if isinstance(value, bytes):
                        result[key] = json.loads(value)
                    else:
                        result[key] = value
                except (TypeError, json.JSONDecodeError):
                    result[key] = value.decode('utf-8') if isinstance(value, bytes) else value
                    
        return result
    
    async def multi_set(
        self,
        items: Dict[str, Any],
        category: CacheCategory = CacheCategory.USER,
        prefix: Optional[str] = None,
        ttl: Optional[int] = None,
    ) -> bool:
        """
        Met plusieurs valeurs en cache en une seule opération atomique.
        
        Args:
            items: Dictionnaire {clé: valeur} à mettre en cache
            category: Catégorie de cache pour le TTL
            prefix: Préfixe optionnel
            ttl: TTL personnalisé (remplace la catégorie si spécifié)
            
        Returns:
            True si l'opération a réussi
        """
        if not items:
            return True
        
        # Calculer le TTL effectif
        effective_ttl = ttl if ttl is not None else self._get_ttl(category)
        
        # Créer un pipeline pour les opérations
        async with self.redis.pipeline() as pipe:
            for key, value in items.items():
                formatted_key = self._format_key(key, prefix)
                
                try:
                    serialized = json.dumps(value).encode('utf-8')
                    
                    if self._should_compress(serialized):
                        serialized = self._compress(serialized)
                        # Ajouter une métadonnée pour indiquer la compression
                        pipe.set(f"{formatted_key}:meta", "compressed", ex=effective_ttl)
                    
                    pipe.set(formatted_key, serialized, ex=effective_ttl)
                except (TypeError, ValueError) as e:
                    logger.error(f"Failed to cache value for key {key}: {e}")
                    # Continuer avec les autres clés
            
            # Exécuter le pipeline en une seule opération réseau
            results = await pipe.execute()
            
        # Vérifier si toutes les opérations ont réussi
        return all(result for result in results)
    
    async def delete(self, key: str, prefix: Optional[str] = None) -> int:
        """
        Supprime une clé du cache.
        
        Args:
            key: Clé à supprimer
            prefix: Préfixe optionnel
            
        Returns:
            Nombre de clés supprimées (0 ou 1)
        """
        formatted_key = self._format_key(key, prefix)
        meta_key = f"{formatted_key}:meta"
        
        # Supprimer à la fois la clé et ses métadonnées
        async with self.redis.pipeline() as pipe:
            pipe.delete(formatted_key)
            pipe.delete(meta_key)
            results = await pipe.execute()
            
        return sum(results)
    
    async def delete_pattern(self, pattern: str, prefix: Optional[str] = None) -> int:
        """
        Supprime toutes les clés correspondant à un modèle.
        
        Args:
            pattern: Modèle de clé (glob-style pattern)
            prefix: Préfixe optionnel
            
        Returns:
            Nombre de clés supprimées
        """
        formatted_pattern = self._format_key(pattern, prefix)
        keys = []
        
        # Scan pour trouver toutes les clés correspondantes
        cursor = 0
        while True:
            cursor, batch = await self.redis.scan(cursor, match=formatted_pattern, count=100)
            keys.extend(batch)
            
            # Ajouter également les clés de métadonnées associées
            for key in batch:
                keys.append(f"{key}:meta")
                
            if cursor == 0:
                break
        
        if not keys:
            return 0
            
        # Supprimer toutes les clés en une seule opération
        return await self.redis.delete(*keys)
    
    async def exists(self, key: str, prefix: Optional[str] = None) -> bool:
        """
        Vérifie si une clé existe dans le cache.
        
        Args:
            key: Clé à vérifier
            prefix: Préfixe optionnel
            
        Returns:
            True si la clé existe
        """
        formatted_key = self._format_key(key, prefix)
        return bool(await self.redis.exists(formatted_key))
    
    async def increment(
        self, 
        key: str, 
        amount: int = 1,
        category: CacheCategory = CacheCategory.SESSION,
        prefix: Optional[str] = None,
    ) -> int:
        """
        Incrémente une valeur numérique dans le cache.
        
        Args:
            key: Clé à incrémenter
            amount: Montant de l'incrémentation
            category: Catégorie de cache pour le TTL
            prefix: Préfixe optionnel
            
        Returns:
            Nouvelle valeur après incrémentation
        """
        formatted_key = self._format_key(key, prefix)
        
        # Incrémenter et définir le TTL si la clé n'existe pas encore
        async with self.redis.pipeline() as pipe:
            pipe.incrby(formatted_key, amount)
            pipe.expire(formatted_key, self._get_ttl(category))
            results = await pipe.execute()
            
        return results[0]
    
    async def touch(
        self, 
        key: str, 
        category: CacheCategory = CacheCategory.USER,
        prefix: Optional[str] = None,
        ttl: Optional[int] = None,
    ) -> bool:
        """
        Met à jour le TTL d'une clé existante.
        
        Args:
            key: Clé à mettre à jour
            category: Catégorie de cache pour le TTL
            prefix: Préfixe optionnel
            ttl: TTL personnalisé (remplace la catégorie si spécifié)
            
        Returns:
            True si la clé existe et a été mise à jour
        """
        formatted_key = self._format_key(key, prefix)
        effective_ttl = ttl if ttl is not None else self._get_ttl(category)
        
        # Mettre à jour le TTL à la fois pour la clé et ses métadonnées
        async with self.redis.pipeline() as pipe:
            pipe.expire(formatted_key, effective_ttl)
            pipe.expire(f"{formatted_key}:meta", effective_ttl)
            results = await pipe.execute()
            
        return any(results)


# Fonction pour obtenir le service de cache comme dépendance FastAPI
async def get_cache_service(
    redis_client: aioredis.Redis = Depends(get_redis_client)
) -> AsyncRedisService:
    """
    Dépendance FastAPI pour obtenir le service de cache Redis.
    
    Usage:
    ```
    @app.get("/items/{item_id}")
    async def read_item(
        item_id: str,
        cache: AsyncRedisService = Depends(get_cache_service)
    ):
        cached_item = await cache.get(f"item:{item_id}")
        if cached_item:
            return cached_item
            
        # Logique pour récupérer l'élément...
        await cache.set(f"item:{item_id}", item, category=CacheCategory.USER)
        return item
    ```
    """
    return AsyncRedisService(redis_client)


# Décorateur pour la mise en cache des fonctions
def async_cache(
    key_prefix: str,
    key_func: Callable[..., str] = lambda *args, **kwargs: str(hash(str(args) + str(kwargs))),
    category: CacheCategory = CacheCategory.USER,
    ttl: Optional[int] = None,
):
    """
    Décorateur pour mettre en cache les résultats d'une fonction asynchrone.
    
    Args:
        key_prefix: Préfixe pour la clé de cache
        key_func: Fonction pour générer la partie unique de la clé
        category: Catégorie de cache pour le TTL
        ttl: TTL personnalisé (remplace la catégorie si spécifié)
        
    Usage:
    ```
    @async_cache("user_data", lambda user_id, **kwargs: user_id, category=CacheCategory.USER)
    async def get_user_data(user_id: str, include_details: bool = True) -> Dict:
        # Logique pour récupérer les données utilisateur...
        return user_data
    ```
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Extraire le service de cache des arguments
            cache_service = None
            for arg in args:
                if isinstance(arg, AsyncRedisService):
                    cache_service = arg
                    break
                    
            for value in kwargs.values():
                if isinstance(value, AsyncRedisService):
                    cache_service = value
                    break
            
            if not cache_service:
                # Si pas de service de cache, exécuter la fonction sans mise en cache
                return await func(*args, **kwargs)
            
            # Générer la clé de cache
            cache_key = f"{key_prefix}:{key_func(*args, **kwargs)}"
            
            # Vérifier si le résultat est en cache
            cached_result = await cache_service.get(cache_key)
            if cached_result is not None:
                return cached_result
                
            # Exécuter la fonction
            result = await func(*args, **kwargs)
            
            # Mettre en cache le résultat
            await cache_service.set(cache_key, result, category=category, ttl=ttl)
            
            return result
        return wrapper
    return decorator 