# -*- coding: utf-8 -*-
# mypy: disable-error-code="attr-defined"
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from fastapi_cache.decorator import cache
from typing import Dict, List, Any, Optional
import json
import asyncio

from app.db.session import sql_tool_db
from app.schemas.response_schema import IGetResponseBase, create_response
from app.schemas.tool_schemas.sql_tool_schema import ExecutionResult
from app.utils.sql import is_sql_query_safe
from app.db.asyncpg_service import PostgresService
from app.api.deps import get_pg_service
from app.services.cache.async_redis_service import AsyncRedisService, get_cache_service, CacheCategory, async_cache
    
router = APIRouter()


@router.get("/execute")
async def execute_sql(
    statement: str,
    cache_service: AsyncRedisService = Depends(get_cache_service)
) -> IGetResponseBase[ExecutionResult]:
    """Executes an SQL query on the database and returns the result."""
    if not is_sql_query_safe(statement):
        return create_response(
            message="SQL query contains forbidden keywords (DML, DDL statements)",
            data=None,
            meta={},
        )
    if sql_tool_db is None:
        return create_response(
            message="SQL query execution is disabled",
            data=None,
            meta={},
        )

    # Vérifier si le résultat est en cache
    cache_key = f"sql_query:{hash(statement)}"
    cached_result = await cache_service.get(cache_key)
    if cached_result:
        return create_response(
            message="Successfully executed SQL query (cached)",
            data=cached_result,
        )

    try:
        (
            columns,
            rows,
        ) = sql_tool_db.execute(statement)
        execution_result = ExecutionResult(
            raw_result=[
                dict(
                    zip(
                        columns,
                        row,
                    )
                )
                for row in rows
            ],
            affected_rows=None,
            error=None,
        )
        
        # Mettre en cache le résultat avec TTL dynamique
        # Pour les requêtes analytics lourdes (commençant par SELECT COUNT, AVG, SUM, etc.)
        if statement.strip().upper().startswith(("SELECT COUNT", "SELECT SUM", "SELECT AVG")):
            # Cache plus long pour les requêtes analytiques
            await cache_service.set(cache_key, execution_result, category=CacheCategory.REFERENCE)
        else:
            # Cache standard pour les autres requêtes
            await cache_service.set(cache_key, execution_result, category=CacheCategory.USER)
            
    except Exception as e:
        return create_response(
            message=repr(e),
            data=None,
        )

    return create_response(
        message="Successfully executed SQL query",
        data=execution_result,
    )

@router.get("/query/large-data")
async def get_large_data(
    query: str,
    limit: Optional[int] = None,
    pg_service: PostgresService = Depends(get_pg_service),
):
    """
    Endpoint pour récupérer un grand volume de données 
    de manière efficace (streaming).
    
    Utilise un curseur côté serveur pour éviter les problèmes de mémoire.
    """
    # Vérifier si la requête est sécurisée
    if not is_sql_query_safe(query):
        raise HTTPException(status_code=400, detail="SQL query contains forbidden keywords")
        
    # Fonction pour transformer les lignes si nécessaire
    def process_row(row: Dict[str, Any]) -> Dict[str, Any]:
        # Exemple de transformation (convertir les timestamps en ISO format)
        for key, value in row.items():
            if hasattr(value, 'isoformat'):
                row[key] = value.isoformat()
        return row
    
    # Pour une requête volumineuse, utiliser StreamingResponse au lieu de charger tout en mémoire
    async def generate_json():
        """Générateur pour streamer les résultats JSON ligne par ligne"""
        # Début du tableau JSON
        yield '{"data":['
        
        count = 0
        first = True
        
        async for row in pg_service.stream_results(query):
            # Ajouter une virgule pour tous les éléments sauf le premier
            if not first:
                yield ','
            else:
                first = False
                
            # Traiter et convertir chaque ligne en JSON
            processed = process_row(row)
            yield json.dumps(processed)
            
            count += 1
            if limit and count >= limit:
                break
                
        # Fin du tableau JSON
        yield ']}'
    
    return StreamingResponse(
        generate_json(),
        media_type="application/json"
    )

@router.post("/multi-get")
async def multi_get_data(
    keys: List[str],
    cache_service: AsyncRedisService = Depends(get_cache_service),
):
    """
    Récupère plusieurs clés de cache en une seule opération.
    
    Utilise le pipeline Redis pour améliorer les performances.
    """
    if not keys:
        return {"data": {}}
        
    # Utiliser multi_get pour récupérer toutes les clés en une seule opération
    results = await cache_service.multi_get(keys)
    
    return {
        "data": results,
        "cache_hits": len(results),
        "cache_misses": len(keys) - len(results)
    }

@router.post("/multi-set")
async def multi_set_data(
    items: Dict[str, Any],
    category: Optional[CacheCategory] = CacheCategory.USER,
    cache_service: AsyncRedisService = Depends(get_cache_service),
):
    """
    Met en cache plusieurs valeurs en une seule opération atomique.
    
    Utilise le pipeline Redis pour améliorer les performances.
    """
    if not items:
        return {"success": True, "count": 0}
        
    success = await cache_service.multi_set(items, category=category)
    
    return {
        "success": success,
        "count": len(items)
    }

@router.post("/transaction-example")
async def transaction_example(
    data: Dict[str, Any],
    pg_service: PostgresService = Depends(get_pg_service),
):
    """
    Exemple d'endpoint utilisant une transaction
    """
    try:
        # Exécute plusieurs requêtes dans une transaction atomique
        async with pg_service.transaction() as conn:
            user_id = await conn.fetchval(
                "INSERT INTO users(name, email) VALUES($1, $2) RETURNING id", 
                data["name"], data["email"]
            )
            
            await conn.execute(
                "INSERT INTO user_settings(user_id, theme) VALUES($1, $2)",
                user_id, data.get("theme", "default")
            )
            
            return {"user_id": user_id, "status": "created"}
    except Exception as e:
        # La transaction est automatiquement annulée en cas d'erreur
        raise HTTPException(status_code=500, detail=f"Transaction failed: {str(e)}")

# Exemple d'utilisation du décorateur de cache asynchrone
@router.get("/cached-data/{item_id}")
@async_cache("item_data", lambda item_id, **kwargs: item_id, category=CacheCategory.USER)
async def get_cached_item(
    item_id: str, 
    full_details: bool = True,
    cache_service: AsyncRedisService = Depends(get_cache_service),
):
    """
    Exemple d'endpoint avec mise en cache automatique des résultats.
    
    Le décorateur @async_cache gère automatiquement la mise en cache.
    """
    # Simulation de récupération des données
    # Dans un cas réel, ici serait le code pour récupérer les données de la base
    await asyncio.sleep(1)  # Simuler une opération lente
    
    return {
        "id": item_id,
        "name": f"Item {item_id}",
        "details": {
            "created_at": "2023-07-15T10:30:00Z",
            "status": "active",
            "views": 1245
        } if full_details else None
    }
