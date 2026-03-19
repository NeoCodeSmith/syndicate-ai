"""
SYNDICATE AI — FastAPI Interface Layer
File: src/syndicate/api/main.py
"""
from __future__ import annotations

import logging
from typing import Any

import jsonschema
from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security.api_key import APIKeyHeader
from prometheus_fastapi_instrumentator import Instrumentator

from syndicate.core.models import AgentListResponse, CreateWorkflowRequest, WorkflowStatusResponse

logger = logging.getLogger(__name__)

app = FastAPI(
    title="SYNDICATE AI",
    description="Deterministic Multi-Agent Orchestration Platform",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

Instrumentator().instrument(app).expose(app, endpoint="/metrics")

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=True)


async def verify_api_key(key: str = Security(API_KEY_HEADER)) -> str:
    from syndicate.app import get_settings
    if key not in get_settings().valid_api_keys:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return key


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy", "version": "1.0.0"}


@app.post("/api/v1/workflows/{workflow_id}/execute",
          response_model=WorkflowStatusResponse, status_code=202)
async def execute_workflow(workflow_id: str, request: CreateWorkflowRequest,
                           _: str = Depends(verify_api_key)) -> WorkflowStatusResponse:
    from syndicate.app import get_orchestration_engine, get_workflow_registry
    wf_reg = get_workflow_registry()
    orch = get_orchestration_engine()

    wf_def = wf_reg.get(workflow_id)
    if not wf_def:
        raise HTTPException(status_code=404, detail=f"Workflow '{workflow_id}' not found")

    if wf_def.context_schema:
        try:
            jsonschema.validate(instance=request.context, schema=wf_def.context_schema)
        except jsonschema.ValidationError as e:
            raise HTTPException(status_code=400, detail=f"Invalid context: {e.message}")

    try:
        execution = orch.start_workflow(wf_def, request.context, request.created_by)
    except Exception as e:
        logger.exception("Failed to start workflow")
        raise HTTPException(status_code=500, detail=str(e))

    return WorkflowStatusResponse(
        execution_id=execution.id, workflow_name=execution.workflow_name,
        status=execution.status, current_step=execution.current_step,
        completed_steps=0, total_steps=len(wf_def.steps),
        started_at=execution.started_at, completed_at=execution.completed_at,
    )


@app.get("/api/v1/executions/{execution_id}", response_model=WorkflowStatusResponse)
async def get_execution(execution_id: str, _: str = Depends(verify_api_key)) -> WorkflowStatusResponse:
    from syndicate.app import get_orchestration_engine
    orch = get_orchestration_engine()
    try:
        execution = orch._load(execution_id)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Execution '{execution_id}' not found")

    completed = sum(1 for s in execution.steps if s.status.value in ("COMMITTED", "VERIFIED"))
    return WorkflowStatusResponse(
        execution_id=execution.id, workflow_name=execution.workflow_name,
        status=execution.status, current_step=execution.current_step,
        completed_steps=completed, total_steps=len(execution.steps),
        started_at=execution.started_at, completed_at=execution.completed_at,
    )


@app.get("/api/v1/agents", response_model=AgentListResponse)
async def list_agents(division: str | None = None, capability: str | None = None,
                      _: str = Depends(verify_api_key)) -> AgentListResponse:
    from syndicate.app import get_agent_registry
    reg = get_agent_registry()
    agents = reg.list_all()
    if division:
        agents = [a for a in agents if a.division == division]
    if capability:
        agents = [a for a in agents if capability in a.capabilities]
    divs = sorted(set(a.division for a in agents))
    return AgentListResponse(
        agents=[a.model_dump(include={"id", "name", "division", "capabilities", "version"})
                for a in agents],
        total=len(agents), divisions=divs,
    )


@app.get("/api/v1/agents/{agent_id}")
async def get_agent(agent_id: str, _: str = Depends(verify_api_key)) -> dict[str, Any]:
    from syndicate.app import get_agent_registry
    agent = get_agent_registry().get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    return agent.model_dump()
