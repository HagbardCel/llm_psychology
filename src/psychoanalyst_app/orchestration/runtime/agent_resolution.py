"""Agent cache/creation helpers for orchestrator runtime."""

from __future__ import annotations

import logging
from typing import Any

from psychoanalyst_app.context.user_context import UserContext

logger = logging.getLogger(__name__)


async def get_or_create_cached_agent(
    *,
    cache: dict[str, Any],
    service_container,
    agent_type: str,
    user_id: str,
):
    """Return cached agent instance or create+cache a new one."""
    cache_key = f"{agent_type}_{user_id}"
    if cache_key in cache:
        logger.debug("Retrieved cached agent: %s", cache_key)
        return cache[cache_key]

    logger.info("Creating agent: %s for user %s", agent_type, user_id)
    user_context = UserContext(user_id=user_id)
    agent = service_container.create_agent(agent_type, user_context)

    cache[cache_key] = agent
    logger.info("Cached agent: %s", cache_key)
    return agent
