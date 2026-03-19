"""
SYNDICATE AI — Python SDK
File: src/syndicate/sdk/client.py

Type-safe Python client for the SYNDICATE AI REST API.
This is what developers import in their projects instead of making
raw HTTP calls. Provides sync and async interfaces.

Usage:
    from syndicate.sdk import SyndicateClient

    client = SyndicateClient(api_key="sk-...", base_url="http://localhost:8000")

    # Execute a workflow
    execution = client.execute("startup-mvp", context={
        "project_brief": "Invoice automation SaaS",
        "target_market": "SMB"
    })

    # Stream real-time updates
    for event in client.stream(execution.execution_id):
        print(f"[{event.type}] {event.data}")

    # Or just wait for completion
    result = client.wait(execution.execution_id)
    print(result.status)
"""

from __future__ import annotations

import time
from collections.abc import Generator
from dataclasses import dataclass, field
from typing import Any

import httpx

# ── Response models ────────────────────────────────────────────────────────


@dataclass
class ExecutionResponse:
    execution_id: str
    workflow_name: str
    status: str
    current_step: str | None
    completed_steps: int
    total_steps: int
    started_at: str | None
    completed_at: str | None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExecutionResponse:
        return cls(
            execution_id=data["execution_id"],
            workflow_name=data["workflow_name"],
            status=data["status"],
            current_step=data.get("current_step"),
            completed_steps=data.get("completed_steps", 0),
            total_steps=data.get("total_steps", 0),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
        )

    @property
    def is_terminal(self) -> bool:
        return self.status in ("COMPLETED", "FAILED", "ABORTED")

    @property
    def progress_pct(self) -> float:
        if self.total_steps == 0:
            return 0.0
        return round((self.completed_steps / self.total_steps) * 100, 1)


@dataclass
class AgentInfo:
    id: str
    name: str
    division: str
    capabilities: list[str]
    version: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentInfo:
        return cls(
            id=data["id"],
            name=data["name"],
            division=data["division"],
            capabilities=data.get("capabilities", []),
            version=data.get("version", "1.0.0"),
        )


@dataclass
class StreamEvent:
    type: str
    data: dict[str, Any]
    raw: str = field(repr=False)


@dataclass
class SyndicateError(Exception):
    status_code: int
    detail: str
    request_id: str | None = None

    def __str__(self) -> str:
        return f"SyndicateError({self.status_code}): {self.detail}"


# ── Client ─────────────────────────────────────────────────────────────────


class SyndicateClient:
    """
    Synchronous Python client for SYNDICATE AI.

    Thread-safe. Reuses a single httpx.Client with connection pooling.
    For async usage, use AsyncSyndicateClient.

    Args:
        api_key: Your SYNDICATE AI API key (starts with sk-)
        base_url: API base URL (default: http://localhost:8000)
        timeout: Request timeout in seconds (default: 30)
    """

    DEFAULT_BASE_URL = "http://localhost:8000"

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            base_url=self._base_url,
            headers={
                "X-API-Key": api_key,
                "Content-Type": "application/json",
                "User-Agent": "syndicate-python-sdk/1.0.0",
            },
            timeout=timeout,
        )

    # ── Workflow Execution ─────────────────────────────────────────────────

    def execute(
        self,
        workflow_id: str,
        context: dict[str, Any] | None = None,
        created_by: str | None = None,
    ) -> ExecutionResponse:
        """
        Start a workflow execution.

        Args:
            workflow_id: The workflow ID (e.g. 'startup-mvp')
            context: Initial inputs for the workflow
            created_by: Optional identifier for the requester

        Returns:
            ExecutionResponse with execution_id for tracking

        Raises:
            SyndicateError: On 4xx/5xx API responses
        """
        payload: dict[str, Any] = {"context": context or {}}
        if created_by:
            payload["created_by"] = created_by

        resp = self._client.post(
            f"/api/v1/workflows/{workflow_id}/execute",
            json=payload,
        )
        self._raise_for_status(resp)
        return ExecutionResponse.from_dict(resp.json())

    def get_execution(self, execution_id: str) -> ExecutionResponse:
        """Get the current status of a workflow execution."""
        resp = self._client.get(f"/api/v1/executions/{execution_id}")
        self._raise_for_status(resp)
        return ExecutionResponse.from_dict(resp.json())

    def wait(
        self,
        execution_id: str,
        poll_interval: float = 2.0,
        timeout: float = 600.0,
    ) -> ExecutionResponse:
        """
        Block until a workflow execution reaches a terminal state.

        Args:
            execution_id: The execution to wait for
            poll_interval: Seconds between status polls (default: 2s)
            timeout: Maximum wait time in seconds (default: 600s)

        Returns:
            Final ExecutionResponse (status: COMPLETED | FAILED | ABORTED)

        Raises:
            TimeoutError: If execution doesn't complete within timeout
            SyndicateError: On API errors
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            execution = self.get_execution(execution_id)
            if execution.is_terminal:
                return execution
            time.sleep(poll_interval)
        raise TimeoutError(f"Execution {execution_id} did not complete within {timeout}s")

    def run_and_wait(
        self,
        workflow_id: str,
        context: dict[str, Any] | None = None,
        timeout: float = 600.0,
    ) -> ExecutionResponse:
        """
        Execute a workflow and block until it completes.
        Convenience method combining execute() + wait().

        Example:
            result = client.run_and_wait(
                "startup-mvp",
                context={"project_brief": "B2B SaaS"}
            )
            if result.status == "COMPLETED":
                print("Done!")
        """
        execution = self.execute(workflow_id, context=context)
        return self.wait(execution.execution_id, timeout=timeout)

    def stream(
        self,
        execution_id: str,
        timeout: float = 600.0,
    ) -> Generator[StreamEvent, None, None]:
        """
        Stream real-time execution events via Server-Sent Events.

        Yields StreamEvent objects as the DAG executes.
        Terminates when execution reaches a terminal state or timeout.

        Example:
            for event in client.stream(execution.execution_id):
                if event.type == "step.completed":
                    print(f"Step done: {event.data['step_name']}")
                elif event.type == "execution.completed":
                    print("Workflow complete!")
        """
        with self._client.stream(
            "GET",
            f"/api/v1/executions/{execution_id}/stream",
            timeout=timeout,
        ) as response:
            self._raise_for_status(response)
            event_type = None
            data_buffer: list[str] = []

            for line in response.iter_lines():
                if line.startswith("event:"):
                    event_type = line[6:].strip()
                elif line.startswith("data:"):
                    data_buffer.append(line[5:].strip())
                elif line == "" and event_type and data_buffer:
                    import json

                    raw = "\n".join(data_buffer)
                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError:
                        data = {"raw": raw}
                    yield StreamEvent(type=event_type, data=data, raw=raw)
                    event_type = None
                    data_buffer = []

    # ── Agent Registry ─────────────────────────────────────────────────────

    def list_agents(
        self,
        division: str | None = None,
        capability: str | None = None,
    ) -> list[AgentInfo]:
        """List all registered agents, optionally filtered."""
        params: dict[str, str] = {}
        if division:
            params["division"] = division
        if capability:
            params["capability"] = capability

        resp = self._client.get("/api/v1/agents", params=params)
        self._raise_for_status(resp)
        data = resp.json()
        return [AgentInfo.from_dict(a) for a in data.get("agents", [])]

    def get_agent(self, agent_id: str) -> dict[str, Any]:
        """Get the full YAML contract for an agent."""
        resp = self._client.get(f"/api/v1/agents/{agent_id}")
        self._raise_for_status(resp)
        return dict(resp.json())

    # ── Health ─────────────────────────────────────────────────────────────

    def health(self) -> dict[str, str]:
        """Check API health. Returns {'status': 'healthy', 'version': '...'}"""
        resp = self._client.get("/health")
        self._raise_for_status(resp)
        return dict(resp.json())

    def is_healthy(self) -> bool:
        """Return True if the API is reachable and healthy."""
        try:
            return self.health().get("status") == "healthy"
        except Exception:  # noqa: BLE001
            return False

    # ── Context manager ────────────────────────────────────────────────────

    def __enter__(self) -> SyndicateClient:
        return self

    def __exit__(self, *_: object) -> None:
        self._client.close()

    def close(self) -> None:
        self._client.close()

    # ── Internal ───────────────────────────────────────────────────────────

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        try:
            detail = response.json().get("detail", response.text)
        except Exception:  # noqa: BLE001
            detail = response.text
        raise SyndicateError(
            status_code=response.status_code,
            detail=str(detail),
            request_id=response.headers.get("x-request-id"),
        )
