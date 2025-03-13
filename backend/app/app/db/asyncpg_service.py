import logging
import asyncpg
from asyncpg.pool import Pool


from typing import Any, Dict, List, Optional, Tuple, Union

from app.db.asyncpg_pool import PgResult, get_pool
from app.db.asyncpg_cursor import fetch_large_dataset

logger = logging.getLogger(__name__)

class PostgresService:
    """Service pour interagir directement avec PostgreSQL via asyncpg"""

    async def execute(
        self, query: str, *args, timeout: Optional[float] = None
    ) -> str:
        """
        Exécute une requête sans résultat (INSERT, UPDATE, DELETE).
        Retourne le tag de l'opération effectuée.
        """
        pool = await get_pool()
        async with pool.acquire() as conn:
            return await conn.execute(query, *args, timeout=timeout)

    async def fetch(
        self, query: str, *args, timeout: Optional[float] = None
    ) -> PgResult:
        """
        Exécute une requête et renvoie tous les résultats (SELECT).
        """
        pool = await get_pool()
        async with pool.acquire() as conn:
            records = await conn.fetch(query, *args, timeout=timeout)
            return PgResult.from_records(records)

    async def fetch_one(
        self, query: str, *args, timeout: Optional[float] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Exécute une requête et renvoie la première ligne de résultat.
        """
        pool = await get_pool()
        async with pool.acquire() as conn:
            record = await conn.fetchrow(query, *args, timeout=timeout)
            return dict(record) if record else None

    async def fetch_val(
        self, query: str, *args, column: int = 0, timeout: Optional[float] = None
    ) -> Any:
        """
        Exécute une requête et renvoie une seule valeur (première ligne, colonne spécifiée).
        """
        pool = await get_pool()
        async with pool.acquire() as conn:
            return await conn.fetchval(query, *args, column=column, timeout=timeout)

    async def transaction(self):
        """
        Retourne un gestionnaire de contexte pour exécuter des requêtes dans une transaction.
        
        Exemple:
        ```
        async with pg_service.transaction() as conn:
            await conn.execute("INSERT INTO users (name) VALUES ($1)", "Alice")
            await conn.execute("UPDATE stats SET user_count = user_count + 1")
        ```
        """
        pool = await get_pool()
        return pool.acquire()
