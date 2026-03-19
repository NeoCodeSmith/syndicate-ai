"""
SYNDICATE AI — Server-Sent Events Streaming
File: src/syndicate/streaming/sse.py

Real-time workflow execution updates via SSE.
Clients subscribe to an execution stream and receive step-by-step
status events as the DAG executes — no polling required.

This is a key differentiator vs LangGraph (polling only) and
CrewAI (no streaming API at all).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

import redis.asyncio as aioredis
from fastapi import Request
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

# ── Event types ────────────────────────────────────────────────────────────


class EventType:
    EXECUTION_STARTED = "execution.started"
    STEP_DISPATCHED = "step.dispatched"
    STEP_ACTIVE = "step.active"
    STEP_COMPLETED = "step.completed"
    STEP_FAILED = "step.failed"
    STEP_RETRYING = "step.retrying"
    STEP_ESCALATED = "step.escalated"
    VALIDATION_PASSED = "validation.passed"
    VALIDATION_FAILED = "validation.failed"
    EXECUTION_COMPLETED = "execution.completed"
    EXECUTION_ABORTED = "execution.aborted"
    HEARTBEAT = "heartbeat"


def make_event(
    event_type: str,
    data: dict[str, Any],
    event_id: str | None = None,
) -> str:
    """
    Format a Server-Sent Event message.
    SSE format: 'event: <type>\\ndata: <json>\\nid: <id>\\n\\n'
    """
    lines = [f"event: {event_type}", f"data: {json.dumps(data)}"]
    if event_id:
        lines.append(f"id: {event_id}")
    return "\n".join(lines) + "\n\n"


# ── Publisher — called by Orchestration Engine ────────────────────────────


class StreamPublisher:
    """
    Publishes execution events to Redis PubSub channels.
    Called by the Orchestration Engine at each state transition.
    """

    def __init__(self, redis_client: Any) -> None:
        self._redis = redis_client

    def publish(
        self,
        execution_id: str,
        event_type: str,
        data: dict[str, Any],
    ) -> None:
        """Publish an event to the execution's stream channel."""
        channel = f"stream:{execution_id}"
        payload = json.dumps({"type": event_type, "data": data})
        self._redis.publish(channel, payload)

    def publish_step_update(
        self,
        execution_id: str,
        step_name: str,
        agent_id: str,
        status: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self.publish(
            execution_id,
            f"step.{status.lower()}",
            {
                "step_name": step_name,
                "agent_id": agent_id,
                "status": status,
                **(detail or {}),
            },
        )


# ── Subscriber — SSE endpoint handler ─────────────────────────────────────


async def execution_event_stream(
    execution_id: str,
    redis_url: str,
    request: Request,
    timeout_seconds: int = 600,
) -> AsyncGenerator[str, None]:
    """
    Async generator that yields SSE events for a workflow execution.

    Subscribes to Redis PubSub channel for the execution.
    Yields events as they arrive. Sends heartbeats every 15s to
    prevent proxy/firewall connection timeouts.
    Terminates on: execution completed/aborted, client disconnect,
    or timeout.
    """
    client = aioredis.from_url(redis_url, decode_responses=True)
    pubsub = client.pubsub()
    channel = f"stream:{execution_id}"

    try:
        await pubsub.subscribe(channel)

        # Send initial connection event
        yield make_event(
            EventType.EXECUTION_STARTED,
            {"execution_id": execution_id, "message": "Stream connected"},
        )

        deadline = asyncio.get_event_loop().time() + timeout_seconds
        heartbeat_interval = 15.0
        last_heartbeat = asyncio.get_event_loop().time()

        while True:
            # Check client disconnect
            if await request.is_disconnected():
                logger.info("SSE client disconnected for execution %s", execution_id)
                break

            # Check timeout
            now = asyncio.get_event_loop().time()
            if now > deadline:
                yield make_event(EventType.HEARTBEAT, {"status": "timeout"})
                break

            # Send heartbeat if needed
            if now - last_heartbeat >= heartbeat_interval:
                yield make_event(EventType.HEARTBEAT, {"status": "alive"})
                last_heartbeat = now

            # Poll for messages (non-blocking, 1s timeout)
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)

            if message and message["type"] == "message":
                try:
                    payload = json.loads(message["data"])
                    event_type = payload.get("type", "unknown")
                    data = payload.get("data", {})

                    yield make_event(event_type, data)

                    # Terminal events — close the stream
                    if event_type in (
                        EventType.EXECUTION_COMPLETED,
                        EventType.EXECUTION_ABORTED,
                    ):
                        logger.info(
                            "Stream closing: %s for execution %s",
                            event_type,
                            execution_id,
                        )
                        break

                except (json.JSONDecodeError, KeyError) as exc:
                    logger.warning("Malformed SSE payload: %s", exc)
                    continue

            await asyncio.sleep(0.05)  # prevent busy-loop

    except asyncio.CancelledError:
        logger.info("SSE stream cancelled for execution %s", execution_id)
    finally:
        await pubsub.unsubscribe(channel)
        await client.aclose()  # type: ignore[attr-defined]


def create_sse_response(
    execution_id: str,
    redis_url: str,
    request: Request,
) -> StreamingResponse:
    """Create a FastAPI StreamingResponse for SSE."""
    return StreamingResponse(
        execution_event_stream(execution_id, redis_url, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering
            "Connection": "keep-alive",
        },
    )
