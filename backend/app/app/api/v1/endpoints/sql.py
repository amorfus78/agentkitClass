# -*- coding: utf-8 -*-
# mypy: disable-error-code="attr-defined"
from fastapi import APIRouter
from fastapi_cache.decorator import cache
import asyncpg
from typing import List, Dict, Any, Tuple

from app.db.session import sql_tool_db
from app.schemas.response_schema import IGetResponseBase, create_response
from app.schemas.tool_schemas.sql_tool_schema import ExecutionResult
from app.utils.sql import is_sql_query_safe
from app.core.config import settings

router = APIRouter()

pg_pool = None

async def initialize_pg_pool() -> None:
    """Initialize the PostgreSQL connection pool."""
    global pg_pool
    if pg_pool is None:
        pg_pool = await asyncpg.create_pool(
            dsn=f"postgresql://{settings.DB_USER}:{settings.DB_PASS}@{settings.DB_HOST}/{settings.DB_NAME}",
            min_size=5,
            max_size=50,  # Adjust pool size dynamically
            statement_cache_size=1000,  # Enable prepared statements cache
            timeout=5,
        )


async def cleanup_pg_pool() -> None:
    """Cleanup the PostgreSQL connection pool."""
    global pg_pool
    if pg_pool is not None:
        await pg_pool.close()
        pg_pool = None


@router.on_event("startup")
async def startup_event():
    """Initialize connection pool on startup."""
    if getattr(settings, "USE_POOL", False):
        await initialize_pg_pool()


@router.on_event("shutdown")
async def shutdown_event():
    """Cleanup connection pool on shutdown."""
    await cleanup_pg_pool()


async def pooled_execute_sql(statement: str) -> Tuple[List[str], List[List[Any]]]:
    """Optimized SQL execution with connection pooling."""
    if not is_sql_query_safe(statement):
        raise ValueError("Unsafe SQL detected")
    
    if pg_pool is None:
        await initialize_pg_pool()
    
    async with pg_pool.acquire() as conn:
        async with conn.transaction():
            # Use server-side cursors for large queries
            cursor = await conn.cursor(statement)
            rows = await cursor.fetch(100)  # Stream 100 rows at a time
            columns = [desc[0] for desc in cursor.description]
            
            # Fetch remaining rows if any
            all_rows = rows
            while rows:
                rows = await cursor.fetch(100)
                all_rows.extend(rows)
    
    return columns, all_rows


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
    
    try:
        # Use the pooled execution method if pool is available
        if pg_pool is not None or settings.USE_POOL:
            columns, rows = await pooled_execute_sql(statement)
        elif sql_tool_db is None:
            return create_response(
                message="SQL query execution is disabled",
                data=None,
                meta={},
            )
        else:
            # Fallback to the existing method
            columns, rows = sql_tool_db.execute(statement)
            
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
