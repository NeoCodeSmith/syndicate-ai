"""
SYNDICATE AI — Memory Store
File: src/syndicate/memory/store.py

Two-tier memory:
- Redis:      hot context (TTL-based, sub-ms reads)
- PostgreSQL: durable audit trail (via SQLAlchemy, stubbed here)

Security: all keys are sanitised before use to prevent Redis key injection.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import redis as redis_module

logger = logging.getLogger(__name__)

DEFAULT_TTL = 86400 * 7  # 7 days
_KEY_SAFE = re.compile(r"^[\w\-:.]+$")  # allow word chars, dash, colon, dot only


def _safe_key(*parts: str) -> str:
    """Build a Redis key, rejecting any part containing unsafe characters."""
    for p in parts:
        if not _KEY_SAFE.match(p):
            raise ValueError(f"Unsafe Redis key segment: {p!r}")
    return ":".join(parts)


class MemoryStore:
    """Redis-backed workflow context store with key sanitisation."""

    def __init__(self, redis_client: redis_module.Redis) -> None:
        self._redis = redis_client

    def set(
        self,
        execution_id: str,
        key: str,
        value: Any,
        step_id: str | None = None,  # noqa: ARG002  (reserved for future DB write)
        ttl: int = DEFAULT_TTL,
    ) -> None:
        redis_key = _safe_key("memory", execution_id, key)
        self._redis.setex(redis_key, ttl, json.dumps(value))

    def get(self, execution_id: str, key: str) -> Any | None:
        redis_key = _safe_key("memory", execution_id, key)
        raw = self._redis.get(redis_key)
        return json.loads(raw) if raw else None

    def delete(self, execution_id: str, key: str) -> None:
        redis_key = _safe_key("memory", execution_id, key)
        self._redis.delete(redis_key)

    def get_all(self, execution_id: str) -> dict[str, Any]:
        # Use a safe prefix scan (no user-controlled wildcards)
        safe_prefix = _safe_key("memory", execution_id, "*")
        keys = self._redis.keys(safe_prefix)
        result: dict[str, Any] = {}
        prefix_len = len(f"memory:{execution_id}:")
        for k in keys:
            short = k.decode()[prefix_len:]
            raw = self._redis.get(k)
            if raw:
                result[short] = json.loads(raw)
        return result

    def summarize(self, execution_id: str, max_entries: int = 20) -> str:
        ctx = self.get_all(execution_id)
        if not ctx:
            return "No prior context."
        lines = [f"WORKFLOW CONTEXT [{execution_id}]:"]
        for k, v in list(ctx.items())[:max_entries]:
            lines.append(f"  {k}: {str(v)[:200]}")
        if len(ctx) > max_entries:
            lines.append(f"  ... and {len(ctx) - max_entries} more entries")
        return "\n".join(lines)
