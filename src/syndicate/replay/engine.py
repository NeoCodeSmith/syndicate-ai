"""
SYNDICATE AI — Execution Replay & Debug Mode
File: src/syndicate/replay/engine.py

Replay any past workflow execution step-by-step.
Debug mode injects breakpoints between steps, allowing inspection
of intermediate outputs before advancing the DAG.

Use cases:
  - Replay a failed production execution locally to diagnose
  - Step through a new workflow interactively before deploying
  - Re-run a specific failed step with patched input
  - Compare outputs across two different LLM providers

Key differentiator: No other multi-agent framework (LangGraph, CrewAI,
AutoGen) offers execution replay or interactive step debugging.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class BreakpointAction(str, Enum):
    CONTINUE = "continue"  # advance to next step
    SKIP = "skip"  # skip this step, use mock output
    RETRY = "retry"  # retry with patched input
    ABORT = "abort"  # abort replay


@dataclass
class StepSnapshot:
    """Complete snapshot of a single step execution."""

    step_name: str
    agent_id: str
    input_data: dict[str, Any]
    output_data: dict[str, Any] | None
    status: str
    attempt: int
    duration_ms: int
    tokens_used: int
    error_message: str | None
    timestamp: str


@dataclass
class ExecutionSnapshot:
    """Complete snapshot of a workflow execution for replay."""

    execution_id: str
    workflow_id: str
    workflow_name: str
    status: str
    context: dict[str, Any]
    steps: list[StepSnapshot]
    started_at: str
    completed_at: str | None
    total_tokens: int = field(init=False)
    total_duration_ms: int = field(init=False)

    def __post_init__(self) -> None:
        self.total_tokens = sum(s.tokens_used for s in self.steps)
        self.total_duration_ms = sum(s.duration_ms for s in self.steps)


@dataclass
class ReplaySession:
    """An active replay session with optional breakpoints."""

    session_id: str
    source_execution_id: str
    workflow_id: str
    current_step_index: int
    breakpoints: set[str]  # step names where execution should pause
    patched_inputs: dict[str, dict[str, Any]]  # step_name → patched input
    mock_outputs: dict[str, dict[str, Any]]  # step_name → mock output
    status: str  # running | paused | completed | aborted
    step_results: list[dict[str, Any]]


class ReplayEngine:
    """
    Replays workflow executions from stored snapshots.

    Stores execution snapshots in Redis at completion time.
    Replays by re-executing steps with the original inputs,
    optionally with breakpoints and patched data.

    Usage:
        engine = ReplayEngine(redis_client, execution_engine)

        # Replay a past execution
        session = engine.create_session(execution_id="exec-abc123")

        # Add a breakpoint before a specific step
        engine.add_breakpoint(session.session_id, "qa-audit")

        # Patch the input for a step
        engine.patch_input(session.session_id, "qa-audit", {
            "acceptance_criteria": ["stricter criteria"]
        })

        # Run until breakpoint
        result = await engine.run_until_breakpoint(session.session_id)

        # Inspect output, then continue
        engine.continue_session(session.session_id)
    """

    def __init__(self, redis_client: Any, execution_engine: Any) -> None:
        self._redis = redis_client
        self._exec_engine = execution_engine

    # ── Snapshot management ─────────────────────────────────────────────────

    def save_snapshot(self, snapshot: ExecutionSnapshot) -> None:
        """Persist an execution snapshot for future replay."""
        key = f"replay:snapshot:{snapshot.execution_id}"
        self._redis.setex(
            key,
            86400 * 30,  # 30 days
            json.dumps(self._snapshot_to_dict(snapshot)),
        )
        logger.info("Saved replay snapshot for execution %s", snapshot.execution_id)

    def load_snapshot(self, execution_id: str) -> ExecutionSnapshot | None:
        """Load an execution snapshot."""
        key = f"replay:snapshot:{execution_id}"
        data = self._redis.get(key)
        if not data:
            return None
        return self._dict_to_snapshot(json.loads(data))

    # ── Session management ──────────────────────────────────────────────────

    def create_session(
        self,
        execution_id: str,
        breakpoints: list[str] | None = None,
    ) -> ReplaySession:
        """Create a new replay session from a past execution."""
        import uuid

        snapshot = self.load_snapshot(execution_id)
        if not snapshot:
            raise ValueError(f"No snapshot found for execution '{execution_id}'")

        session = ReplaySession(
            session_id=str(uuid.uuid4()),
            source_execution_id=execution_id,
            workflow_id=snapshot.workflow_id,
            current_step_index=0,
            breakpoints=set(breakpoints or []),
            patched_inputs={},
            mock_outputs={},
            status="ready",
            step_results=[],
        )

        self._save_session(session)
        logger.info(
            "Created replay session %s for execution %s",
            session.session_id,
            execution_id,
        )
        return session

    def add_breakpoint(self, session_id: str, step_name: str) -> None:
        """Add a breakpoint before a named step."""
        session = self._load_session(session_id)
        session.breakpoints.add(step_name)
        self._save_session(session)

    def remove_breakpoint(self, session_id: str, step_name: str) -> None:
        """Remove a breakpoint."""
        session = self._load_session(session_id)
        session.breakpoints.discard(step_name)
        self._save_session(session)

    def patch_input(self, session_id: str, step_name: str, patched_input: dict[str, Any]) -> None:
        """Override the input for a specific step during replay."""
        session = self._load_session(session_id)
        session.patched_inputs[step_name] = patched_input
        self._save_session(session)

    def mock_output(self, session_id: str, step_name: str, mock_data: dict[str, Any]) -> None:
        """
        Mock the output of a step (skip LLM call entirely).
        Useful for debugging downstream steps without re-running expensive agents.
        """
        session = self._load_session(session_id)
        session.mock_outputs[step_name] = mock_data
        self._save_session(session)

    def get_session_state(self, session_id: str) -> dict[str, Any]:
        """Get current state of a replay session."""
        session = self._load_session(session_id)
        snapshot = self.load_snapshot(session.source_execution_id)

        current_step_name = None
        if snapshot and session.current_step_index < len(snapshot.steps):
            current_step_name = snapshot.steps[session.current_step_index].step_name

        return {
            "session_id": session.session_id,
            "source_execution_id": session.source_execution_id,
            "workflow_id": session.workflow_id,
            "status": session.status,
            "current_step": current_step_name,
            "current_step_index": session.current_step_index,
            "total_steps": len(snapshot.steps) if snapshot else 0,
            "breakpoints": list(session.breakpoints),
            "patched_steps": list(session.patched_inputs.keys()),
            "mocked_steps": list(session.mock_outputs.keys()),
            "completed_steps": len(session.step_results),
        }

    def step_forward(
        self,
        session_id: str,
        action: BreakpointAction = BreakpointAction.CONTINUE,
    ) -> dict[str, Any]:
        """
        Execute the current step and advance to the next.
        Returns the step result.
        """
        session = self._load_session(session_id)
        snapshot = self.load_snapshot(session.source_execution_id)

        if not snapshot:
            raise ValueError("Snapshot not found")

        if session.current_step_index >= len(snapshot.steps):
            session.status = "completed"
            self._save_session(session)
            return {"status": "completed", "message": "All steps replayed"}

        step = snapshot.steps[session.current_step_index]

        # Apply patched input if provided
        input_data = session.patched_inputs.get(step.step_name, step.input_data)

        result: dict[str, Any]

        if action == BreakpointAction.SKIP or step.step_name in session.mock_outputs:
            # Use mock output
            mock = session.mock_outputs.get(step.step_name, step.output_data or {})
            result = {
                "step_name": step.step_name,
                "agent_id": step.agent_id,
                "status": "MOCKED",
                "output": mock,
                "original_output": step.output_data,
                "tokens_used": 0,
            }
        elif action == BreakpointAction.ABORT:
            session.status = "aborted"
            self._save_session(session)
            return {"status": "aborted"}
        else:
            # Re-execute the step with the execution engine
            output = self._exec_engine.run(
                execution_id=f"replay:{session.session_id}",
                step_id=f"step:{session.current_step_index}",
                agent_id=step.agent_id,
                step_name=step.step_name,
                input_data=input_data,
            )
            result = {
                "step_name": step.step_name,
                "agent_id": step.agent_id,
                "status": output.status.value,
                "output": output.data,
                "original_output": step.output_data,
                "tokens_used": output.metadata.tokens_used,
                "duration_ms": output.metadata.duration_ms,
            }

        session.step_results.append(result)
        session.current_step_index += 1

        # Check if next step has a breakpoint
        next_paused = False
        if session.current_step_index < len(snapshot.steps):
            next_step = snapshot.steps[session.current_step_index]
            if next_step.step_name in session.breakpoints:
                session.status = "paused"
                next_paused = True
        else:
            session.status = "completed"

        self._save_session(session)
        result["paused_at"] = (
            snapshot.steps[session.current_step_index].step_name
            if next_paused and session.current_step_index < len(snapshot.steps)
            else None
        )
        return result

    # ── Comparison ──────────────────────────────────────────────────────────

    def compare_executions(self, execution_id_a: str, execution_id_b: str) -> dict[str, Any]:
        """
        Compare two execution snapshots side-by-side.
        Shows differences in outputs, token usage, and timing.
        """
        snap_a = self.load_snapshot(execution_id_a)
        snap_b = self.load_snapshot(execution_id_b)

        if not snap_a or not snap_b:
            raise ValueError("One or both snapshots not found")

        steps_a = {s.step_name: s for s in snap_a.steps}
        steps_b = {s.step_name: s for s in snap_b.steps}
        all_steps = sorted(set(steps_a) | set(steps_b))

        comparison = []
        for step_name in all_steps:
            a = steps_a.get(step_name)
            b = steps_b.get(step_name)
            comparison.append(
                {
                    "step": step_name,
                    "a_status": a.status if a else "missing",
                    "b_status": b.status if b else "missing",
                    "a_tokens": a.tokens_used if a else 0,
                    "b_tokens": b.tokens_used if b else 0,
                    "a_duration_ms": a.duration_ms if a else 0,
                    "b_duration_ms": b.duration_ms if b else 0,
                    "output_changed": a is not None
                    and b is not None
                    and a.output_data != b.output_data,
                }
            )

        return {
            "execution_a": execution_id_a,
            "execution_b": execution_id_b,
            "a_total_tokens": snap_a.total_tokens,
            "b_total_tokens": snap_b.total_tokens,
            "a_total_duration_ms": snap_a.total_duration_ms,
            "b_total_duration_ms": snap_b.total_duration_ms,
            "token_delta": snap_b.total_tokens - snap_a.total_tokens,
            "steps": comparison,
        }

    # ── Private ─────────────────────────────────────────────────────────────

    def _save_session(self, session: ReplaySession) -> None:
        key = f"replay:session:{session.session_id}"
        self._redis.setex(key, 3600 * 24, json.dumps(self._session_to_dict(session)))

    def _load_session(self, session_id: str) -> ReplaySession:
        key = f"replay:session:{session_id}"
        data = self._redis.get(key)
        if not data:
            raise ValueError(f"Replay session '{session_id}' not found")
        return self._dict_to_session(json.loads(data))

    def _snapshot_to_dict(self, s: ExecutionSnapshot) -> dict[str, Any]:
        return {
            "execution_id": s.execution_id,
            "workflow_id": s.workflow_id,
            "workflow_name": s.workflow_name,
            "status": s.status,
            "context": s.context,
            "started_at": s.started_at,
            "completed_at": s.completed_at,
            "steps": [
                {
                    "step_name": st.step_name,
                    "agent_id": st.agent_id,
                    "input_data": st.input_data,
                    "output_data": st.output_data,
                    "status": st.status,
                    "attempt": st.attempt,
                    "duration_ms": st.duration_ms,
                    "tokens_used": st.tokens_used,
                    "error_message": st.error_message,
                    "timestamp": st.timestamp,
                }
                for st in s.steps
            ],
        }

    def _dict_to_snapshot(self, d: dict[str, Any]) -> ExecutionSnapshot:
        steps = [
            StepSnapshot(
                step_name=s["step_name"],
                agent_id=s["agent_id"],
                input_data=s["input_data"],
                output_data=s.get("output_data"),
                status=s["status"],
                attempt=s.get("attempt", 1),
                duration_ms=s.get("duration_ms", 0),
                tokens_used=s.get("tokens_used", 0),
                error_message=s.get("error_message"),
                timestamp=s.get("timestamp", ""),
            )
            for s in d.get("steps", [])
        ]
        return ExecutionSnapshot(
            execution_id=d["execution_id"],
            workflow_id=d["workflow_id"],
            workflow_name=d["workflow_name"],
            status=d["status"],
            context=d["context"],
            started_at=d["started_at"],
            completed_at=d.get("completed_at"),
            steps=steps,
        )

    def _session_to_dict(self, s: ReplaySession) -> dict[str, Any]:
        return {
            "session_id": s.session_id,
            "source_execution_id": s.source_execution_id,
            "workflow_id": s.workflow_id,
            "current_step_index": s.current_step_index,
            "breakpoints": list(s.breakpoints),
            "patched_inputs": s.patched_inputs,
            "mock_outputs": s.mock_outputs,
            "status": s.status,
            "step_results": s.step_results,
        }

    def _dict_to_session(self, d: dict[str, Any]) -> ReplaySession:
        return ReplaySession(
            session_id=d["session_id"],
            source_execution_id=d["source_execution_id"],
            workflow_id=d["workflow_id"],
            current_step_index=d["current_step_index"],
            breakpoints=set(d.get("breakpoints", [])),
            patched_inputs=d.get("patched_inputs", {}),
            mock_outputs=d.get("mock_outputs", {}),
            status=d["status"],
            step_results=d.get("step_results", []),
        )
