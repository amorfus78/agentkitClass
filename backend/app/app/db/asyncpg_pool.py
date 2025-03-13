import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple, Union

import asyncpg
from asyncpg.pool import Pool
from pydantic import BaseModel

from app.core.config import settings

logger = logging.getLogger(__name__)

# Singleton pour le pool de connexions
_pool: Optional[Pool] = None

async def get_pool() -> Pool:
    """
    Renvoie un pool de connexions partagé, le crée s'il n'existe pas encore.
    
    Ce pool est configuré pour être optimal:
    - min_size: nombre minimum de connexions maintenues
    - max_size: nombre maximum de connexions autorisées
    - timeout: temps d'attente max pour obtenir une connexion
    - command_timeout: temps max pour l'exécution d'une commande
    """
    global _pool
    if _pool is None:
        try:
            _pool = await asyncpg.create_pool(
                dsn=settings.POSTGRES_DSN,
                min_size=5,                 # Garder au moins 5 connexions
                max_size=settings.POOL_SIZE, # Limite supérieure définie dans settings
                max_inactive_connection_lifetime=300.0,  # Recycler les connexions après 5 minutes
                timeout=10.0,               # Attente max pour une connexion
                command_timeout=60.0,       # Timeout pour les requêtes longues
                statement_cache_size=1000,  # Cache des requêtes préparées
                server_settings={
                    'application_name': 'agentkit',
                    'jit': 'off',           # Désactive JIT pour stabilité
                    'work_mem': '8MB',      # Mémoire pour opérations de tri
                }
            )
            logger.info("PostgreSQL connection pool established")
        except Exception as e:
            logger.error(f"Failed to create connection pool: {e}")
            raise
    return _pool

async def close_pool():
    """Ferme proprement le pool de connexions"""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("PostgreSQL connection pool closed")

class PgResult(BaseModel):
    """Modèle pour représenter les résultats d'une requête"""
    count: int
    rows: List[Dict[str, Any]]
    
    @classmethod
    def from_records(cls, records: List[asyncpg.Record]) -> 'PgResult':
        return cls(
            count=len(records),
            rows=[dict(r) for r in records]
        )
