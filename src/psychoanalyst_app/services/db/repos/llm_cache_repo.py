"""LLM response cache persistence."""

from __future__ import annotations

import sqlite3
from typing import Any

from psychoanalyst_app.services.db.executor import TrioSQLiteExecutor


async def get_llm_cache_entry(
    executor: TrioSQLiteExecutor,
    cache_key: str,
) -> dict[str, Any] | None:
    """Fetch a cached LLM response by key."""
    async with executor.connection(row_factory=sqlite3.Row) as conn:
        return await executor.run_sync(_sync_get_llm_cache_entry, conn, cache_key)


def _sync_get_llm_cache_entry(
    conn: sqlite3.Connection,
    cache_key: str,
) -> dict[str, Any] | None:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT cache_key, call_type, model_name, prompt, context_json, schema_hash,
               response_json, created_at, user_id, session_block_id, source
        FROM llm_cache
        WHERE cache_key = ?
        """,
        (cache_key,),
    )
    row = cursor.fetchone()
    conn.commit()
    return dict(row) if row else None


async def upsert_llm_cache_entry(
    executor: TrioSQLiteExecutor,
    *,
    cache_key: str,
    call_type: str,
    model_name: str,
    prompt: str,
    context_json: str,
    schema_hash: str | None,
    response_json: str,
    created_at: str,
    user_id: str | None,
    session_block_id: str | None,
    source: str | None,
) -> None:
    """Insert or update a cached LLM response."""
    async with executor.connection() as conn:
        await executor.run_sync(
            _sync_upsert_llm_cache_entry,
            conn,
            cache_key,
            call_type,
            model_name,
            prompt,
            context_json,
            schema_hash,
            response_json,
            created_at,
            user_id,
            session_block_id,
            source,
        )


def _sync_upsert_llm_cache_entry(
    conn: sqlite3.Connection,
    cache_key: str,
    call_type: str,
    model_name: str,
    prompt: str,
    context_json: str,
    schema_hash: str | None,
    response_json: str,
    created_at: str,
    user_id: str | None,
    session_block_id: str | None,
    source: str | None,
) -> None:
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT OR REPLACE INTO llm_cache
        (cache_key, call_type, model_name, prompt, context_json, schema_hash,
         response_json, created_at, user_id, session_block_id, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            cache_key,
            call_type,
            model_name,
            prompt,
            context_json,
            schema_hash,
            response_json,
            created_at,
            user_id,
            session_block_id,
            source,
        ),
    )
    conn.commit()


async def delete_llm_cache_entry(
    executor: TrioSQLiteExecutor,
    cache_key: str,
) -> int:
    """Delete a cached LLM response by key."""
    async with executor.connection() as conn:
        return await executor.run_sync(
            _sync_delete_llm_cache_entry, conn, cache_key
        )


def _sync_delete_llm_cache_entry(
    conn: sqlite3.Connection, cache_key: str
) -> int:
    cursor = conn.cursor()
    cursor.execute("DELETE FROM llm_cache WHERE cache_key = ?", (cache_key,))
    conn.commit()
    return cursor.rowcount


async def prune_llm_cache_before(
    executor: TrioSQLiteExecutor,
    cutoff_iso: str,
) -> int:
    """Delete cache entries older than the cutoff."""
    async with executor.connection() as conn:
        return await executor.run_sync(
            _sync_prune_llm_cache_before, conn, cutoff_iso
        )


def _sync_prune_llm_cache_before(
    conn: sqlite3.Connection, cutoff_iso: str
) -> int:
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM llm_cache WHERE created_at < ?",
        (cutoff_iso,),
    )
    conn.commit()
    return cursor.rowcount


async def prune_llm_cache_to_max_rows(
    executor: TrioSQLiteExecutor,
    max_rows: int,
) -> int:
    """Ensure the cache contains at most max_rows entries."""
    async with executor.connection() as conn:
        return await executor.run_sync(
            _sync_prune_llm_cache_to_max_rows, conn, max_rows
        )


def _sync_prune_llm_cache_to_max_rows(
    conn: sqlite3.Connection, max_rows: int
) -> int:
    cursor = conn.cursor()
    cursor.execute(
        """
        DELETE FROM llm_cache
        WHERE cache_key IN (
            SELECT cache_key
            FROM llm_cache
            ORDER BY created_at DESC
            LIMIT -1 OFFSET ?
        )
        """,
        (max_rows,),
    )
    conn.commit()
    return cursor.rowcount
