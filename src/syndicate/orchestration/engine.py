"""
SYNDICATE AI — Orchestration Engine
File: src/syndicate/orchestration/engine.py

Deterministic DAG executor. Replaces markdown-based orchestration with
a real state machine that advances workflow steps, handles retries with
exponential backoff, and escalates on terminal failures.
"""

from __future__ import annotations

import logging
from typing import Any

import redis
from celery import Celery

from syndicate.core.models import (
    AgentOutput,
    AgentOutputStatus,
    OrchestratorDecision,
    StepExecution,
    StepStatus,
    WorkflowDefinition,
    WorkflowExecution,
    WorkflowStatus,
)

logger = logging.getLogger(__name__)

MAX_STEPS_PER_WORKFLOW = 100


class OrchestrationEngine:
    """Parses workflow DAGs, dispatches Celery tasks, and enforces state transitions."""

    def __init__(
        self, celery_app: Celery, redis_client: redis.Redis, memory_store: Any, agent_registry: Any
    ) -> None:
        self._celery = celery_app
        self._redis = redis_client
        self._memory = memory_store
        self._registry = agent_registry

    # ── Public ──────────────────────────────────────────────────────────────

    def start_workflow(
        self,
        workflow_def: WorkflowDefinition,
        context: dict[str, Any],
        created_by: str | None = None,
    ) -> WorkflowExecution:
        execution = WorkflowExecution(
            workflow_definition_id=workflow_def.id,
            workflow_name=workflow_def.name,
            status=WorkflowStatus.ACTIVE,
            context=context,
            current_step=workflow_def.initial_step,
            created_by=created_by,
        )
        self._persist(execution)
        step_def = self._get_step(workflow_def, workflow_def.initial_step)
        if not step_def:
            raise ValueError(f"Initial step '{workflow_def.initial_step}' not in DAG")
        self._dispatch(execution, workflow_def, step_def, context)
        logger.info("Workflow started", extra={"id": execution.id, "name": workflow_def.name})
        return execution

    def on_step_completed(
        self, execution_id: str, step_name: str, output: AgentOutput
    ) -> OrchestratorDecision:
        execution = self._load(execution_id)
        workflow_def = self._load_def(execution.workflow_definition_id)
        step_def = self._get_step(workflow_def, step_name)
        step_exec = self._get_step_exec(execution, step_name)

        if (
            sum(1 for s in execution.steps if s.status == StepStatus.COMMITTED)
            >= MAX_STEPS_PER_WORKFLOW
        ):
            return self._abort(execution, "Hard step limit reached")

        if output.status == AgentOutputStatus.FAILED:
            return self._handle_failure(
                execution, workflow_def, step_def, step_exec, str(output.errors)
            )

        step_exec.output = output
        step_exec.status = StepStatus.COMMITTED
        step_exec.validated = True
        self._memory.set(execution_id, f"step:{step_name}:output", output.data)
        self._persist(execution)

        if not step_def.on_success:
            return self._complete(execution)

        next_def = self._get_step(workflow_def, step_def.on_success)
        if not next_def:
            return self._abort(execution, f"Unknown next step: {step_def.on_success}")

        next_input = self._resolve_input(execution, workflow_def, next_def)
        for p in next_def.parallel_with:
            p_def = self._get_step(workflow_def, p)
            if p_def:
                self._dispatch(
                    execution,
                    workflow_def,
                    p_def,
                    self._resolve_input(execution, workflow_def, p_def),
                )
        self._dispatch(execution, workflow_def, next_def, next_input)
        return OrchestratorDecision.DISPATCH_NEXT

    def on_step_failed(self, execution_id: str, step_name: str, error: str) -> OrchestratorDecision:
        execution = self._load(execution_id)
        workflow_def = self._load_def(execution.workflow_definition_id)
        step_def = self._get_step(workflow_def, step_name)
        step_exec = self._get_step_exec(execution, step_name)
        return self._handle_failure(execution, workflow_def, step_def, step_exec, error)

    # ── Private ─────────────────────────────────────────────────────────────

    def _handle_failure(self, execution, workflow_def, step_def, step_exec, error):
        agent_def = self._registry.get(step_def.agent_id)
        max_retries = agent_def.failure.max_retries if agent_def else 3
        step_exec.error_message = error

        if step_exec.attempt < max_retries:
            backoff = min(2**step_exec.attempt, 60)
            step_exec.status = StepStatus.RETRYING
            step_exec.attempt += 1
            self._persist(execution)
            resolved = self._resolve_input(execution, workflow_def, step_def)
            self._dispatch(execution, workflow_def, step_def, resolved, countdown=backoff)
            logger.warning(
                f"Retrying '{step_def.name}' attempt {step_exec.attempt}/{max_retries} in {backoff}s"
            )
            return OrchestratorDecision.RETRY_STEP

        step_exec.status = StepStatus.ESCALATED
        self._persist(execution)
        if step_def and step_def.on_failure == "ABORT":
            return self._abort(execution, f"Terminal failure: {error}")
        logger.error(f"Step '{step_def.name}' escalated after {max_retries} retries")
        return OrchestratorDecision.ESCALATE

    def _dispatch(self, execution, workflow_def, step_def, input_data, countdown=0):
        step_exec = StepExecution(
            execution_id=execution.id,
            workflow_definition_id=workflow_def.id,
            step_name=step_def.name,
            agent_id=step_def.agent_id,
            status=StepStatus.ACTIVE,
            input=input_data,
        )
        execution.current_step = step_def.name
        execution.steps.append(step_exec)
        self._persist(execution)
        self._celery.send_task(
            "syndicate.execution.tasks.run_agent",
            kwargs={
                "execution_id": execution.id,
                "step_id": step_exec.id,
                "agent_id": step_def.agent_id,
                "step_name": step_def.name,
                "input_data": input_data,
            },
            countdown=countdown,
        )
        logger.info(f"Dispatched '{step_def.name}' → '{step_def.agent_id}'")
        return step_exec

    def _resolve_input(self, execution, workflow_def, step_def) -> dict[str, Any]:
        result = dict(step_def.input_static)
        for m in step_def.input_mappings:
            src = self._memory.get(execution.id, f"step:{m.from_step}:output")
            if src:
                val = self._nested_get(src, m.from_field)
                if val is not None:
                    self._nested_set(result, m.to_field, val)
        result["_context"] = execution.context
        return result

    def _complete(self, execution):
        execution.status = WorkflowStatus.COMPLETED
        self._persist(execution)
        logger.info("Workflow completed", extra={"id": execution.id})
        return OrchestratorDecision.COMPLETE_WORKFLOW

    def _abort(self, execution, reason):
        execution.status = WorkflowStatus.ABORTED
        self._persist(execution)
        logger.error(f"Workflow aborted: {reason}", extra={"id": execution.id})
        return OrchestratorDecision.ABORT_WORKFLOW

    def _persist(self, execution) -> None:
        self._redis.setex(f"execution:{execution.id}", 86400 * 7, execution.model_dump_json())

    def _load(self, execution_id: str) -> WorkflowExecution:
        data = self._redis.get(f"execution:{execution_id}")
        if not data:
            raise ValueError(f"Execution {execution_id} not found")
        return WorkflowExecution.model_validate_json(data)

    def _persist_def(self, wf_def: WorkflowDefinition) -> None:
        self._redis.setex(f"workflow_def:{wf_def.id}", 86400 * 30, wf_def.model_dump_json())

    def _load_def(self, wf_def_id: str) -> WorkflowDefinition:
        data = self._redis.get(f"workflow_def:{wf_def_id}")
        if not data:
            raise ValueError(f"WorkflowDefinition {wf_def_id} not found")
        return WorkflowDefinition.model_validate_json(data)

    def _get_step(self, wf: WorkflowDefinition, name: str):
        return next((s for s in wf.steps if s.name == name), None)

    def _get_step_exec(self, execution: WorkflowExecution, step_name: str) -> StepExecution:
        s = next((s for s in reversed(execution.steps) if s.step_name == step_name), None)
        if not s:
            raise ValueError(f"StepExecution '{step_name}' not found")
        return s

    def _nested_get(self, data, path):
        cur = data
        for p in path.split("."):
            if not isinstance(cur, dict):
                return None
            cur = cur.get(p)
        return cur

    def _nested_set(self, data, path, value) -> None:
        parts = path.split(".")
        cur = data
        for p in parts[:-1]:
            cur = cur.setdefault(p, {})
        cur[parts[-1]] = value
