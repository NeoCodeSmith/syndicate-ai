"""
SYNDICATE AI — Core Data Models
File: src/syndicate/core/models.py
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class StepStatus(StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    VERIFIED = "VERIFIED"
    COMMITTED = "COMMITTED"
    FAILED = "FAILED"
    ESCALATED = "ESCALATED"
    RETRYING = "RETRYING"


class WorkflowStatus(StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ABORTED = "ABORTED"


class AgentOutputStatus(StrEnum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class OrchestratorDecision(StrEnum):
    DISPATCH_NEXT = "DISPATCH_NEXT"
    RETRY_STEP = "RETRY_STEP"
    ESCALATE = "ESCALATE"
    COMPLETE_WORKFLOW = "COMPLETE_WORKFLOW"
    ABORT_WORKFLOW = "ABORT_WORKFLOW"


class AuthorityLevel(StrEnum):
    ADVISORY = "ADVISORY"
    EXECUTION = "EXECUTION"
    APPROVAL = "APPROVAL"


class AgentFailureConfig(BaseModel):
    conditions: list[str] = Field(default_factory=list)
    max_retries: int = Field(default=3, ge=0, le=10)
    retry_strategy: str = "exponential_backoff"
    failure_handler: str | None = None


class AgentExecutionConfig(BaseModel):
    system_prompt_template: str
    tools: list[str] = Field(default_factory=list)
    max_tokens: int = Field(default=4096, ge=256, le=32768)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    output_format: str = "json"


class AgentSuccessMetrics(BaseModel):
    primary: str
    assertions: list[dict[str, str]] = Field(default_factory=list)


class AgentTone(BaseModel):
    style: str
    voice: str


class AgentDefinition(BaseModel):
    id: str
    name: str
    version: str
    division: str
    role_definition: dict[str, Any]
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    execution: AgentExecutionConfig
    failure: AgentFailureConfig
    success_metrics: AgentSuccessMetrics
    tone: AgentTone
    capabilities: list[str] = Field(default_factory=list)


class AgentOutputMetadata(BaseModel):
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    tokens_used: int = 0
    model: str = ""
    duration_ms: int = 0
    attempt: int = 1


class AgentOutput(BaseModel):
    agent_id: str
    workflow_id: str
    step_id: str
    status: AgentOutputStatus
    data: dict[str, Any]
    metadata: AgentOutputMetadata = Field(default_factory=AgentOutputMetadata)
    errors: list[str] = Field(default_factory=list)


class StepInputMapping(BaseModel):
    from_step: str
    from_field: str
    to_field: str
    transform: str | None = None


class WorkflowStep(BaseModel):
    name: str
    agent_id: str
    input_static: dict[str, Any] = Field(default_factory=dict)
    input_mappings: list[StepInputMapping] = Field(default_factory=list)
    on_success: str | None = None
    on_failure: str | None = None
    parallel_with: list[str] = Field(default_factory=list)
    timeout_seconds: int = 300
    required: bool = True


class WorkflowDefinition(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    version: str = "1.0.0"
    description: str = ""
    steps: list[WorkflowStep]
    initial_step: str
    context_schema: dict[str, Any] | None = None

    @field_validator("steps")
    @classmethod
    def validate_dag(cls, steps: list[WorkflowStep]) -> list[WorkflowStep]:
        step_names = {s.name for s in steps}
        for step in steps:
            if step.on_success and step.on_success not in step_names:
                raise ValueError(
                    f"Step '{step.name}' references unknown on_success: '{step.on_success}'"
                )
            if (
                step.on_failure
                and step.on_failure not in step_names
                and step.on_failure not in ("ESCALATE", "ABORT")
            ):
                raise ValueError(
                    f"Step '{step.name}' references unknown on_failure: '{step.on_failure}'"
                )
        return steps


class StepExecution(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    execution_id: str
    workflow_definition_id: str
    step_name: str
    agent_id: str
    status: StepStatus = StepStatus.PENDING
    attempt: int = 1
    input: dict[str, Any] = Field(default_factory=dict)
    output: AgentOutput | None = None
    validated: bool = False
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None


class WorkflowExecution(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    workflow_definition_id: str
    workflow_name: str
    status: WorkflowStatus = WorkflowStatus.PENDING
    context: dict[str, Any] = Field(default_factory=dict)
    current_step: str | None = None
    steps: list[StepExecution] = Field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_by: str | None = None


class CreateWorkflowRequest(BaseModel):
    context: dict[str, Any] = Field(default_factory=dict)
    created_by: str | None = None


class WorkflowStatusResponse(BaseModel):
    execution_id: str
    workflow_name: str
    status: WorkflowStatus
    current_step: str | None
    completed_steps: int
    total_steps: int
    started_at: datetime | None
    completed_at: datetime | None


class AgentListResponse(BaseModel):
    agents: list[dict[str, Any]]
    total: int
    divisions: list[str]
