"""
SYNDICATE AI — Application Factory
File: src/syndicate/app.py

All services are lazy singletons loaded via getter functions.
All configuration is sourced from environment variables / .env file.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

import redis as redis_module
from openai import OpenAI
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # LLM
    llm_base_url: str = "https://api.anthropic.com/v1"
    llm_api_key: str = ""
    llm_model: str = "claude-opus-4-6"
    llm_fallback_model: str = "claude-sonnet-4-6"

    # Database
    database_url: str = "postgresql+asyncpg://syndicate:password@postgres:5432/syndicate"

    # Redis
    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str = "redis://redis:6379/1"
    celery_result_backend: str = "redis://redis:6379/2"

    # Auth
    syndicate_api_keys: str = ""
    api_key_header_name: str = "X-API-Key"

    @property
    def valid_api_keys(self) -> set[str]:
        return {k.strip() for k in self.syndicate_api_keys.split(",") if k.strip()}

    # CORS
    cors_origins: str = "http://localhost:3000"

    @property
    def allowed_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    # Execution
    max_steps_per_workflow: int = 100
    default_step_timeout_seconds: int = 300
    celery_worker_concurrency: int = 4
    max_retries_default: int = 3

    # Rate limiting
    rate_limit_per_minute: int = 60
    rate_limit_per_hour: int = 1000

    # Observability
    log_level: str = "INFO"
    log_format: str = "json"
    otel_service_name: str = "syndicate-ai"
    otel_exporter_otlp_endpoint: str = "http://otel-collector:4317"
    prometheus_enabled: bool = True

    # File paths
    agents_dir: Path = Path("agents")
    workflows_dir: Path = Path("workflows")

    # Environment
    environment: str = "development"
    debug: bool = False

    # Flower / Grafana
    flower_user: str = "admin"
    flower_password: str = "change-me"
    grafana_admin_password: str = "change-me"


@lru_cache
def get_settings() -> Settings:
    return Settings()


# ── Lazy singletons ────────────────────────────────────────────────────────────

_redis_client: redis_module.Redis[str] | None = None
_llm_client: OpenAI | None = None
_agent_registry: Any = None
_workflow_registry: Any = None
_memory_store: Any = None
_orchestration_engine: Any = None
_execution_engine: Any = None


def get_redis() -> redis_module.Redis[str]:
    global _redis_client
    if _redis_client is None:
        settings = get_settings()
        _redis_client = redis_module.from_url(settings.redis_url, decode_responses=True)
    return _redis_client  # type: ignore[return-value]


def get_llm_client() -> OpenAI:
    global _llm_client
    if _llm_client is None:
        settings = get_settings()
        _llm_client = OpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
        )
    return _llm_client


def get_agent_registry() -> Any:
    global _agent_registry
    if _agent_registry is None:
        from syndicate.registry.agent_registry import AgentRegistry

        settings = get_settings()
        _agent_registry = AgentRegistry(agents_dir=settings.agents_dir)
    return _agent_registry


def get_workflow_registry() -> Any:
    global _workflow_registry
    if _workflow_registry is None:
        from syndicate.registry.workflow_registry import WorkflowRegistry

        settings = get_settings()
        _workflow_registry = WorkflowRegistry(workflows_dir=settings.workflows_dir)
    return _workflow_registry


def get_memory_store() -> Any:
    global _memory_store
    if _memory_store is None:
        from syndicate.memory.store import MemoryStore

        _memory_store = MemoryStore(redis_client=get_redis())
    return _memory_store


def get_orchestration_engine() -> Any:
    global _orchestration_engine
    if _orchestration_engine is None:
        from celery import current_app as celery_app

        from syndicate.orchestration.engine import OrchestrationEngine

        _orchestration_engine = OrchestrationEngine(
            celery_app=celery_app,
            redis_client=get_redis(),
            memory_store=get_memory_store(),
            agent_registry=get_agent_registry(),
        )
    return _orchestration_engine


def get_execution_engine() -> Any:
    global _execution_engine
    if _execution_engine is None:
        from syndicate.execution.engine import ExecutionEngine

        settings = get_settings()
        _execution_engine = ExecutionEngine(
            agent_registry=get_agent_registry(),
            llm_client=get_llm_client(),
            model=settings.llm_model,
        )
    return _execution_engine
