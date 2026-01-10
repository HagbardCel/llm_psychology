"""Service for caching LLM responses via the database."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel

from psychoanalyst_app.services.db_serialization import dump_json, load_json
from psychoanalyst_app.services.trio_db_service import TrioDatabaseService

logger = logging.getLogger(__name__)


class LLMCacheService:
    """Cache LLM responses with retention controls and context scoping."""

    def __init__(
        self,
        db_service: TrioDatabaseService,
        *,
        enabled: bool,
        max_age_days: int,
        max_rows: int,
        sources: list[str] | None,
        require_context: bool,
    ) -> None:
        self._db_service = db_service
        self.enabled = enabled
        self.max_age_days = max_age_days
        self.max_rows = max_rows
        self.require_context = require_context
        self._sources = [source.lower() for source in (sources or [])]

    def _normalize_call_context(
        self, call_context: dict[str, str] | None
    ) -> dict[str, str | None]:
        if not isinstance(call_context, dict):
            return {"user_id": None, "session_block_id": None, "source": None}
        return {
            "user_id": call_context.get("user_id"),
            "session_block_id": call_context.get("session_block_id"),
            "source": call_context.get("source"),
        }

    def _should_cache(
        self, call_context: dict[str, str] | None
    ) -> tuple[bool, dict[str, str | None]]:
        if not self.enabled:
            return False, {}
        normalized = self._normalize_call_context(call_context)
        user_id = normalized.get("user_id")
        session_block_id = normalized.get("session_block_id")
        source = normalized.get("source")
        if self.require_context and (not user_id or not session_block_id or not source):
            return False, {}
        if self._sources:
            if not source or source.lower() not in self._sources:
                return False, {}
        return True, normalized

    def _serialize_context(self, context: list[dict[str, str]] | None) -> str:
        return dump_json(context or [])

    def _schema_hash(self, schema: dict | type[BaseModel] | None) -> str | None:
        if schema is None:
            return None
        if isinstance(schema, type) and issubclass(schema, BaseModel):
            schema_payload = schema.model_json_schema()
        elif isinstance(schema, dict):
            schema_payload = schema
        else:
            raise TypeError("Unsupported schema type for caching")
        raw = json.dumps(schema_payload, sort_keys=True, ensure_ascii=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _build_cache_key(
        self,
        *,
        call_type: str,
        model_name: str,
        prompt: str,
        context_json: str,
        schema_hash: str | None,
        method: str | None,
        call_context: dict[str, str | None],
    ) -> str:
        payload = {
            "call_type": call_type,
            "model_name": model_name,
            "prompt": prompt,
            "context_json": context_json,
            "schema_hash": schema_hash,
            "method": method,
            "user_id": call_context.get("user_id"),
            "session_block_id": call_context.get("session_block_id"),
            "source": call_context.get("source"),
        }
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _serialize_response(self, response: Any) -> str:
        if isinstance(response, BaseModel):
            payload = response.model_dump(mode="json")
        else:
            payload = response
        return dump_json(payload)

    def _deserialize_response(
        self, payload: str, schema: dict | type[BaseModel] | None
    ) -> Any:
        data = load_json(payload, default=None)
        if schema is None:
            return data
        if isinstance(schema, type) and issubclass(schema, BaseModel):
            return schema.model_validate(data)
        return data

    def _is_entry_expired(self, created_at: str) -> bool:
        if self.max_age_days <= 0:
            return False
        try:
            created = datetime.fromisoformat(created_at)
        except ValueError:
            return False
        cutoff = datetime.now() - timedelta(days=self.max_age_days)
        return created < cutoff

    async def get_cached_response(
        self,
        *,
        call_type: str,
        model_name: str,
        prompt: str,
        context: list[dict[str, str]] | None,
        schema: dict | type[BaseModel] | None,
        method: str | None,
        call_context: dict[str, str] | None,
    ) -> Any | None:
        should_cache, normalized = self._should_cache(call_context)
        if not should_cache:
            return None

        context_json = self._serialize_context(context)
        schema_hash = self._schema_hash(schema)
        cache_key = self._build_cache_key(
            call_type=call_type,
            model_name=model_name,
            prompt=prompt,
            context_json=context_json,
            schema_hash=schema_hash,
            method=method,
            call_context=normalized,
        )

        entry = await self._db_service.get_llm_cache_entry(cache_key)
        if not entry:
            logger.debug("LLM cache miss for key %s", cache_key)
            return None

        created_at = entry.get("created_at") or ""
        if created_at and self._is_entry_expired(created_at):
            await self._db_service.delete_llm_cache_entry(cache_key)
            logger.debug("LLM cache expired for key %s", cache_key)
            return None

        logger.info("LLM cache hit for key %s", cache_key)
        return self._deserialize_response(entry["response_json"], schema)

    async def store_response(
        self,
        *,
        call_type: str,
        model_name: str,
        prompt: str,
        context: list[dict[str, str]] | None,
        schema: dict | type[BaseModel] | None,
        method: str | None,
        call_context: dict[str, str] | None,
        response: Any,
    ) -> None:
        should_cache, normalized = self._should_cache(call_context)
        if not should_cache:
            return

        context_json = self._serialize_context(context)
        schema_hash = self._schema_hash(schema)
        cache_key = self._build_cache_key(
            call_type=call_type,
            model_name=model_name,
            prompt=prompt,
            context_json=context_json,
            schema_hash=schema_hash,
            method=method,
            call_context=normalized,
        )
        response_json = self._serialize_response(response)
        await self._db_service.upsert_llm_cache_entry(
            cache_key=cache_key,
            call_type=call_type,
            model_name=model_name,
            prompt=prompt,
            context_json=context_json,
            schema_hash=schema_hash,
            response_json=response_json,
            created_at=datetime.now().isoformat(),
            user_id=normalized.get("user_id"),
            session_block_id=normalized.get("session_block_id"),
            source=normalized.get("source"),
        )
        await self._enforce_limits()

    async def _enforce_limits(self) -> None:
        if self.max_age_days > 0:
            cutoff = datetime.now() - timedelta(days=self.max_age_days)
            await self._db_service.prune_llm_cache_before(
                cutoff.isoformat()
            )
        if self.max_rows > 0:
            await self._db_service.prune_llm_cache_to_max_rows(self.max_rows)
