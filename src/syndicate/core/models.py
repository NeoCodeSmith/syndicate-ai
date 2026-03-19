"""
SYNDICATE AI — Core Data Models
File: src/syndicate/core/models.py
"""
from __future__ import annotations
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


class StepStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    VERIFIED = "VERIFIED"
    COMMITTED = "COMMITTED"
    FAILED = "FAILED"
    ESCALATED = "ESCALATED"
    RETRYING = "RETRYING"


class WorkflowStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ABORTED = "ABORTED"


class AgentOutputStatus(str, Enum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class OrchestratorDecision(str, Enum):
    DISPATCH_NEXT = "DISPATCH_NEXT"
    RETRY_STEP = "RETRY_STEP"
    ESCALATE = "ESCALATE"
    COMPLETE_WORKFLOW = "COMPLETE_WORKFLOW"
    ABORT_WORKFLOW = "ABORT_WORKFLOW"


class AuthorityLevel(str, Enum):
    ADVISORY = "ADVISORY"
    EXECUTION = "EXECUTION"
    APPROVAL = "APPROVAL"


class AgentFailureConfig(BaseModel):
    conditions: List[str] = Field(default_factory=list)
    max_retries: int = Field(default=3, ge=0, le=10)
    retry_strategy: str = "exponential_backoff"
    failure_handler: Optional[str] = None


class AgentExecutionConfig(BaseModel):
    system_prompt_template: str
    tools: List[str] = Field(default_factory=list)
    max_tokens: int = Field(default=4096, ge=256, le=32768)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    output_format: str = "json"


class AgentSuccessMetrics(BaseModel):
    primary: str
    assertions: List[Dict[str, str]] = Field(default_factory=list)


class AgentTone(BaseModel):
    style: str
    voice: str


class AgentDefinition(BaseModel):
    id: str
    name: str
    version: str
    division: str
    role_definition: Dict[str, Any]
    input_schema: Dict[str, Any]
    output_schema: Dict[str, Any]
    execution: AgentExecutionConfig
    failure: AgentFailureConfig
    success_metrics: AgentSuccessMetrics
    tone: AgentTone
    capabilities: List[str] = Field(default_factory=list)


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
    data: Dict[str, Any]
    metadata: AgentOutputMetadata = Field(default_factory=AgentOutputMetadata)
    errors: List[str] = Field(default_factory=list)


class StepInputMapping(BaseModel):
    from_step: str
    from_field: str
    to_field: str
    transform: Optional[str] = None


class WorkflowStep(BaseModel):
    name: str
    agent_id: str
    input_static: Dict[str, Any] = Field(default_factory=dict)
    input_mappings: List[StepInputMapping] = Field(default_factory=list)
    on_success: Optional[str] = None
    on_failure: Optional[str] = None
    parallel_with: List[str] = Field(default_factory=list)
    timeout_seconds: int = 300
    required: bool = True


class WorkflowDefinition(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    version: str = "1.0.0"
    description: str = ""
    steps: List[WorkflowStep]
    initial_step: str
    context_schema: Optional[Dict[str, Any]] = None

    @field_validator("steps")
    @classmethod
    def validate_dag(cls, steps: List[WorkflowStep]) -> List[WorkflowStep]:
        step_names = {s.name for s in steps}
        for step in steps:
            if step.on_success and step.on_success not in step_names:
                raise ValueError(
                    f"Step '{step.name}' references unknown on_success: '{step.on_success}'"
                )
            if step.on_failure and step.on_failure not in step_names \
                    and step.on_failure not in ("ESCALATE", "ABORT"):
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
    input: Dict[str, Any] = Field(default_factory=dict)
    output: Optional[AgentOutput] = None
    validated: bool = False
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None


class WorkflowExecution(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    workflow_definition_id: str
    workflow_name: str
    status: WorkflowStatus = WorkflowStatus.PENDING
    context: Dict[str, Any] = Field(default_factory=dict)
    current_step: Optional[str] = None
    steps: List[StepExecution] = Field(default_factory=list)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_by: Optional[str] = None


class CreateWorkflowRequest(BaseModel):
    context: Dict[str, Any] = Field(default_factory=dict)
    created_by: Optional[str] = None


class WorkflowStatusResponse(BaseModel):
    execution_id: str
    workflow_name: str
    status: WorkflowStatus
    current_step: Optional[str]
    completed_steps: int
    total_steps: int
    started_at: Optional[datetime]
    completed_at: Optional[datetime]


class AgentListResponse(BaseModel):
    agents: List[Dict[str, Any]]
    total: int
    divisions: List[str]
