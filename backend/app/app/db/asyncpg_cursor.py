"""
Module pour la gestion des curseurs côté serveur PostgreSQL.

Ce module fournit des utilitaires pour:
- Traiter de grandes quantités de données sans saturer la mémoire
- Utiliser des curseurs PostgreSQL nommés avec asyncpg
- Traiter des données en streaming avec des générateurs asynchrones
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple, Callable

import asyncpg
from asyncpg.pool import Pool

from app.db.asyncpg_pool import get_pool

logger = logging.getLogger(__name__)

@asynccontextmanager
async def server_cursor(
    query: str, 
    params: Optional[Tuple[Any, ...]] = None, 
    batch_size: int = 1000,
    cursor_name: str = "server_cursor",
    timeout: Optional[float] = None
) -> AsyncGenerator[List[asyncpg.Record], None]:
    """
    Gestionnaire de contexte qui crée un curseur côté serveur pour le traitement
    efficace des requêtes volumineuses.
    
    Args:
        query: Requête SQL à exécuter
        params: Paramètres de la requête (optionnels)
        batch_size: Nombre d'enregistrements à récupérer par lot
        cursor_name: Nom du curseur côté serveur
        timeout: Timeout pour l'acquisition d'une connexion
        
    Exemple d'utilisation:
    ```
    async for batch in server_cursor("SELECT * FROM large_table WHERE status = $1", ('active',)):
        for row in batch:
            # Traiter chaque ligne
    ```
    
    Yields:
        Lots d'enregistrements (asyncpg.Record)
    """
    pool = await get_pool()
    conn = await pool.acquire(timeout=timeout)
    try:
        # Démarrer une transaction
        tr = conn.transaction()
        await tr.start()
        
        # Créer un curseur nommé
        declare_cursor = f"DECLARE {cursor_name} CURSOR FOR {query}"
        if params:
            await conn.execute(declare_cursor, *params)
        else:
            await conn.execute(declare_cursor)
        
        # Récupérer des données par lots
        while True:
            batch = await conn.fetch(f"FETCH {batch_size} FROM {cursor_name}")
            if not batch:
                break
            yield batch
            
        # Fermer la transaction
        await tr.commit()
    except Exception as e:
        logger.error(f"Error in server cursor: {e}")
        try:
            # Annuler la transaction en cas d'erreur
            await tr.rollback()
        except Exception as rollback_error:
            logger.error(f"Error during transaction rollback: {rollback_error}")
        raise
    finally:
        # Libérer la connexion
        await pool.release(conn)

async def fetch_large_dataset(
    query: str, 
    params: Optional[Tuple[Any, ...]] = None,
    transform_func: Optional[Callable[[Dict[str, Any]], Any]] = None,
    batch_size: int = 1000,
    timeout: Optional[float] = None
) -> AsyncGenerator[Any, None]:
    """
    Utilitaire pour récupérer et traiter de grands ensembles de données
    avec traitement en streaming.
    
    Args:
        query: Requête SQL à exécuter
        params: Paramètres de la requête (optionnels)
        transform_func: Fonction de transformation à appliquer à chaque ligne
        batch_size: Nombre d'enregistrements à récupérer par lot
        timeout: Timeout pour l'acquisition d'une connexion
        
    Yields:
        Lignes traitées de la base de données
        
    Exemple:
    ```
    async for user in fetch_large_dataset(
        "SELECT * FROM users WHERE created_at > $1",
        ('2023-01-01',),
        transform_func=lambda row: {"id": row["id"], "name": row["name"].upper()}
    ):
        # Traiter chaque utilisateur...
    ```
    """
    async for batch in server_cursor(query, params, batch_size, timeout=timeout):
        for row in batch:
            row_dict = dict(row)
            if transform_func:
                yield transform_func(row_dict)
            else:
                yield row_dict

async def count_records(
    pool: Pool,
    table: str, 
    where_clause: str = "", 
    params: Optional[Tuple[Any, ...]] = None
) -> int:
    """
    Compte le nombre d'enregistrements dans une table avec une clause WHERE optionnelle.
    
    Args:
        pool: Pool de connexions PostgreSQL
        table: Nom de la table
        where_clause: Clause WHERE, sans le mot-clé 'WHERE' (optionnel)
        params: Paramètres pour la clause WHERE (optionnel)
        
    Returns:
        Nombre d'enregistrements
    """
    query = f"SELECT COUNT(*) FROM {table}"
    if where_clause:
        query += f" WHERE {where_clause}"
        
    async with pool.acquire() as conn:
        return await conn.fetchval(query, *params) if params else await conn.fetchval(query)

async def execute_in_batches(
    pool: Pool,
    query: str,
    items: List[Any],
    batch_size: int = 1000,
    on_batch_complete: Optional[Callable[[int, int], None]] = None
) -> int:
    """
    Exécute une requête en lots pour éviter les timeouts et problèmes de mémoire.
    
    Utile pour les opérations d'insertion/mise à jour en masse.
    
    Args:
        pool: Pool de connexions PostgreSQL
        query: Requête SQL avec paramètres (ex: "INSERT INTO users VALUES ($1, $2)")
        items: Liste des éléments à traiter
        batch_size: Taille des lots
        on_batch_complete: Callback appelé après chaque lot traité
        
    Returns:
        Nombre total d'éléments traités
        
    Exemple:
    ```
    users = [("alice", "alice@example.com"), ("bob", "bob@example.com"), ...]
    processed = await execute_in_batches(
        pool,
        "INSERT INTO users(name, email) VALUES($1, $2)",
        users,
        batch_size=100,
        on_batch_complete=lambda processed, total: print(f"Processed {processed}/{total}")
    )
    ```
    """
    total_items = len(items)
    processed_items = 0
    
    # Traiter par lots
    for i in range(0, total_items, batch_size):
        batch = items[i:i + batch_size]
        processed_items += len(batch)
        
        async with pool.acquire() as conn:
            async with conn.transaction():
                # Exécuter chaque élément du lot
                for item in batch:
                    if isinstance(item, tuple):
                        await conn.execute(query, *item)
                    else:
                        await conn.execute(query, item)
        
        # Appeler le callback si fourni
        if on_batch_complete:
            on_batch_complete(processed_items, total_items)
    
    return processed_items 