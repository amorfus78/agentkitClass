# -*- coding: utf-8 -*-
# mypy: disable-error-code="attr-defined"
from fastapi import APIRouter, Depends, HTTPException
from fastapi_cache.decorator import cache
from typing import Dict, List, Any

from app.db.session import sql_tool_db
from app.schemas.response_schema import IGetResponseBase, create_response
from app.schemas.tool_schemas.sql_tool_schema import ExecutionResult
from app.utils.sql import is_sql_query_safe
from app.db.asyncpg_service import PostgresService
from app.api.deps import get_pg_service
    
router = APIRouter()


@router.get("/execute")
@cache(expire=600)  # -> Bug on POST requests https://github.com/long2ice/fastapi-cache/issues/113
async def execute_sql(
    statement: str,
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
    pg_service: PostgresService = Depends(get_pg_service),
):
    """
    Endpoint pour récupérer un grand volume de données 
    de manière efficace (streaming)
    """
    results = []
    # Utilisation du curseur serveur pour traiter de grandes quantités de données
    # Of course, we would change large_table to the actual table name, provided by the user
    async for row in pg_service.stream_results(
        "SELECT * FROM large_table WHERE created_at > $1 ORDER BY created_at",
        "2023-01-01"
    ):
        
        if 'created_at' in row:
            row['created_at_iso'] = row['created_at'].isoformat()
        if 'amount' in row:
            row['amount_formatted'] = f"{row['amount']:.2f} €"
        results.append(row)

    return {"data": results}

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
