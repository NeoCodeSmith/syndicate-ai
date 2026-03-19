"""
SYNDICATE AI — Memory Store
File: src/syndicate/memory/store.py

Two-tier memory replacing the fictional 'Memory' persona fields:
- Redis: hot context, TTL-based
- PostgreSQL: durable audit trail (via SQLAlchemy, stub here)
"""
from __future__ import annotations
import json
import logging
from typing import Any, Dict, Optional
import redis as redis_module

logger = logging.getLogger(__name__)
DEFAULT_TTL = 86400 * 7


class MemoryStore:
    def __init__(self, redis_client: redis_module.Redis) -> None:
        self._redis = redis_client

    def set(self, execution_id: str, key: str, value: Any,
            step_id: Optional[str] = None, ttl: int = DEFAULT_TTL) -> None:
        self._redis.setex(f"memory:{execution_id}:{key}", ttl, json.dumps(value))

    def get(self, execution_id: str, key: str) -> Optional[Any]:
        raw = self._redis.get(f"memory:{execution_id}:{key}")
        return json.loads(raw) if raw else None

    def delete(self, execution_id: str, key: str) -> None:
        self._redis.delete(f"memory:{execution_id}:{key}")

    def get_all(self, execution_id: str) -> Dict[str, Any]:
        keys = self._redis.keys(f"memory:{execution_id}:*")
        result = {}
        for k in keys:
            short = k.decode().replace(f"memory:{execution_id}:", "")
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
