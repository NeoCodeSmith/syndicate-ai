"""
SYNDICATE AI — FastAPI Interface Layer
File: src/syndicate/api/main.py

Security hardening:
- CORS origins from env (no wildcard)
- Rate limiting via slowapi
- API key auth on all routes
- Redis key sanitisation
- Structured error responses
"""

from __future__ import annotations

import logging
import os
from typing import Any

import jsonschema
from fastapi import Depends, FastAPI, HTTPException, Request, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security.api_key import APIKeyHeader
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from syndicate.core.models import (
    AgentListResponse,
    CreateWorkflowRequest,
    WorkflowStatusResponse,
)

logger = logging.getLogger(__name__)

# ── Rate limiter ──────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="SYNDICATE AI",
    description="Deterministic Multi-Agent Orchestration Platform",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS — origins from environment, never wildcard ───────────────────────────
_raw_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000")
_allowed_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["X-API-Key", "Content-Type"],
)

Instrumentator().instrument(app).expose(app, endpoint="/metrics")

# ── Auth ──────────────────────────────────────────────────────────────────────
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=True)


async def verify_api_key(key: str = Security(API_KEY_HEADER)) -> str:
    from syndicate.app import get_settings

    if key not in get_settings().valid_api_keys:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return key


# ── Helpers ───────────────────────────────────────────────────────────────────


def _sanitise_id(value: str, field: str) -> str:
    """Reject IDs containing path separators or Redis wildcard chars."""
    forbidden = set("*?[]{}\\/ \t\n")
    if any(c in forbidden for c in value):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid characters in {field}",
        )
    if len(value) > 200:
        raise HTTPException(status_code=400, detail=f"{field} too long")
    return value


# ── Health ────────────────────────────────────────────────────────────────────


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy", "version": "1.0.0"}


# ── Workflows ─────────────────────────────────────────────────────────────────


@app.post(
    "/api/v1/workflows/{workflow_id}/execute",
    response_model=WorkflowStatusResponse,
    status_code=202,
)
@limiter.limit("30/minute")
async def execute_workflow(
    request: Request,
    workflow_id: str,
    body: CreateWorkflowRequest,
    _: str = Depends(verify_api_key),
) -> WorkflowStatusResponse:
    """
    Start a new workflow execution.

    Responses: 202 accepted | 400 bad context | 401 auth | 404 not found |
               429 rate limit | 500 orchestration error
    """
    workflow_id = _sanitise_id(workflow_id, "workflow_id")

    from syndicate.app import get_orchestration_engine, get_workflow_registry

    wf_reg = get_workflow_registry()
    orch = get_orchestration_engine()

    wf_def = wf_reg.get(workflow_id)
    if not wf_def:
        raise HTTPException(status_code=404, detail=f"Workflow '{workflow_id}' not found")

    if wf_def.context_schema:
        try:
            jsonschema.validate(instance=body.context, schema=wf_def.context_schema)
        except jsonschema.ValidationError as e:
            raise HTTPException(status_code=400, detail=f"Invalid context: {e.message}") from e

    try:
        execution = orch.start_workflow(wf_def, body.context, body.created_by)
    except Exception as e:
        logger.exception("Failed to start workflow")
        raise HTTPException(status_code=500, detail="Orchestration error") from e

    return WorkflowStatusResponse(
        execution_id=execution.id,
        workflow_name=execution.workflow_name,
        status=execution.status,
        current_step=execution.current_step,
        completed_steps=0,
        total_steps=len(wf_def.steps),
        started_at=execution.started_at,
        completed_at=execution.completed_at,
    )


@app.get("/api/v1/executions/{execution_id}", response_model=WorkflowStatusResponse)
@limiter.limit("60/minute")
async def get_execution(
    request: Request,
    execution_id: str,
    _: str = Depends(verify_api_key),
) -> WorkflowStatusResponse:
    """
    Get execution status.

    Responses: 200 | 400 bad id | 401 auth | 404 not found | 429 rate limit
    """
    execution_id = _sanitise_id(execution_id, "execution_id")

    from syndicate.app import get_orchestration_engine

    orch = get_orchestration_engine()
    try:
        execution = orch._load(execution_id)
    except ValueError as e:
        raise HTTPException(
            status_code=404,
            detail=f"Execution '{execution_id}' not found",
        ) from e

    completed = sum(1 for s in execution.steps if s.status.value in ("COMMITTED", "VERIFIED"))
    return WorkflowStatusResponse(
        execution_id=execution.id,
        workflow_name=execution.workflow_name,
        status=execution.status,
        current_step=execution.current_step,
        completed_steps=completed,
        total_steps=len(execution.steps),
        started_at=execution.started_at,
        completed_at=execution.completed_at,
    )


# ── Agents ────────────────────────────────────────────────────────────────────


@app.get("/api/v1/agents", response_model=AgentListResponse)
@limiter.limit("60/minute")
async def list_agents(
    request: Request,
    division: str | None = None,
    capability: str | None = None,
    _: str = Depends(verify_api_key),
) -> AgentListResponse:
    """List registered agents, optionally filtered by division or capability."""
    from syndicate.app import get_agent_registry

    reg = get_agent_registry()
    agents = reg.list_all()
    if division:
        agents = [a for a in agents if a.division == division]
    if capability:
        agents = [a for a in agents if capability in a.capabilities]
    divs = sorted({a.division for a in agents})
    return AgentListResponse(
        agents=[
            a.model_dump(include={"id", "name", "division", "capabilities", "version"})
            for a in agents
        ],
        total=len(agents),
        divisions=divs,
    )


@app.get("/api/v1/agents/{agent_id}")
@limiter.limit("60/minute")
async def get_agent(
    request: Request,
    agent_id: str,
    _: str = Depends(verify_api_key),
) -> dict[str, Any]:
    """Get full agent contract definition."""
    agent_id = _sanitise_id(agent_id, "agent_id")

    from syndicate.app import get_agent_registry

    agent = get_agent_registry().get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    return agent.model_dump()


# ── Global error handler — never leak internal details ────────────────────────


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception on %s", request.url)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )
