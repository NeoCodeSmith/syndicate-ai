"""
SYNDICATE AI — Celery Tasks
File: src/syndicate/execution/tasks.py
"""

from __future__ import annotations

import logging
from typing import Any

from syndicate.core.models import AgentOutputStatus
from syndicate.execution.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(  # type: ignore[misc]
    name="syndicate.execution.tasks.run_agent",
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
)
def run_agent(
    self: Any,
    execution_id: str,
    step_id: str,
    agent_id: str,
    step_name: str,
    input_data: dict[str, Any],
) -> None:
    from syndicate.app import get_execution_engine, get_orchestration_engine

    exec_engine = get_execution_engine()
    orch_engine = get_orchestration_engine()

    logger.info("Task started: execution=%s step=%s agent=%s", execution_id, step_name, agent_id)
    try:
        output = exec_engine.run(
            execution_id=execution_id,
            step_id=step_id,
            agent_id=agent_id,
            step_name=step_name,
            input_data=input_data,
        )
        if output.status == AgentOutputStatus.FAILED:
            orch_engine.on_step_failed(execution_id, step_name, "; ".join(output.errors))
        else:
            orch_engine.on_step_completed(execution_id, step_name, output)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unhandled exception in task for step '%s'", step_name)
        orch_engine.on_step_failed(execution_id, step_name, str(exc))
