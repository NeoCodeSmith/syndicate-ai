"""
SYNDICATE AI — Execution Engine
File: src/syndicate/execution/engine.py

Handles LLM calls with typed I/O enforcement. Each agent invocation is
isolated — no shared mutable state, full JSON output enforcement.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

import jsonschema
from openai import OpenAI

from syndicate.core.models import (
    AgentOutput,
    AgentOutputMetadata,
    AgentOutputStatus,
)

logger = logging.getLogger(__name__)


class ExecutionEngine:
    """Calls LLM with rendered system prompt, parses JSON, validates schema."""

    def __init__(self, agent_registry: Any, llm_client: OpenAI, model: str = "claude-opus-4-6") -> None:
        self._registry = agent_registry
        self._llm = llm_client
        self._model = model

    def run(self, execution_id: str, step_id: str, agent_id: str,
            step_name: str, input_data: dict[str, Any], attempt: int = 1) -> AgentOutput:
        agent_def = self._registry.get(agent_id)
        if not agent_def:
            return self._fail(execution_id, step_id, agent_id, f"Agent '{agent_id}' not in registry")

        system_prompt = self._render(agent_def.execution.system_prompt_template, input_data)
        start = int(time.time() * 1000)

        try:
            resp = self._llm.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system",
                     "content": system_prompt + "\n\nRESPOND ONLY WITH VALID JSON. No markdown, no explanation."},
                    {"role": "user", "content": json.dumps(input_data, indent=2)},
                ],
                max_tokens=agent_def.execution.max_tokens,
                temperature=agent_def.execution.temperature,
            )
        except Exception as exc:
            logger.exception(f"LLM call failed for '{agent_id}'")
            return self._fail(execution_id, step_id, agent_id, str(exc))

        duration_ms = int(time.time() * 1000) - start

        try:
            text = resp.choices[0].message.content or ""
            parsed = self._parse_json(text)
        except (ValueError, KeyError) as exc:
            return self._fail(execution_id, step_id, agent_id, f"JSON parse error: {exc}")

        err = self._validate_schema(parsed, agent_def.output_schema)
        if err:
            return self._fail(execution_id, step_id, agent_id, f"Schema violation: {err}")

        tokens = getattr(resp.usage, "total_tokens", 0)
        data_payload = parsed.get("data", parsed)

        return AgentOutput(
            agent_id=agent_id, workflow_id=execution_id, step_id=step_id,
            status=AgentOutputStatus.SUCCESS, data=data_payload,
            metadata=AgentOutputMetadata(tokens_used=tokens, model=self._model,
                                         duration_ms=duration_ms, attempt=attempt),
        )

    def _render(self, template: str, inputs: dict[str, Any]) -> str:
        result = template
        for k, v in inputs.items():
            result = result.replace(f"{{input.{k}}}", str(v) if not isinstance(v, str) else v)
        return result

    def _parse_json(self, text: str) -> dict[str, Any]:
        t = text.strip()
        if t.startswith("```"):
            lines = t.split("\n")
            t = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        return json.loads(t)

    def _validate_schema(self, data: dict, schema: dict) -> str | None:
        try:
            jsonschema.validate(instance=data, schema=schema)
            return None
        except jsonschema.ValidationError as e:
            return e.message
        except jsonschema.SchemaError as e:
            return f"Schema error: {e.message}"

    def _fail(self, execution_id, step_id, agent_id, reason) -> AgentOutput:
        return AgentOutput(agent_id=agent_id, workflow_id=execution_id, step_id=step_id,
                           status=AgentOutputStatus.FAILED, data={}, errors=[reason])
