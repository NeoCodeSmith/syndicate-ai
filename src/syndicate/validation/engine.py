"""
SYNDICATE AI — Validation Engine
File: src/syndicate/validation/engine.py

Two-pass validation: JSON Schema structural check + success assertions.
Nothing advances the DAG without passing both passes.
"""

from __future__ import annotations

import logging
from typing import Any

import jsonschema

from syndicate.core.models import AgentDefinition, AgentOutput

logger = logging.getLogger(__name__)


class ValidationResult:
    def __init__(self, passed: bool, errors: list[str]) -> None:
        self.passed = passed
        self.errors = errors

    def __bool__(self) -> bool:
        return self.passed


class ValidationEngine:
    """Runs schema + assertion validation on every agent output."""

    def validate(self, output: AgentOutput, agent_def: AgentDefinition) -> ValidationResult:
        errors: list[str] = []

        # Pass 1: JSON Schema
        envelope = {
            "agent_id": output.agent_id,
            "workflow_id": output.workflow_id,
            "step_id": output.step_id,
            "status": output.status.value,
            "data": output.data,
        }
        errors.extend(self._validate_schema(envelope, agent_def.output_schema))

        # Pass 2: success assertions (only if schema passed)
        if not errors:
            errors.extend(self._run_assertions(output.data, agent_def.success_metrics.assertions))

        passed = len(errors) == 0
        if not passed:
            logger.warning(
                "Validation failed for agent '%s': %s",
                output.agent_id,
                errors,
                extra={"step_id": output.step_id},
            )
        return ValidationResult(passed=passed, errors=errors)

    def _validate_schema(self, data: dict[str, Any], schema: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        try:
            jsonschema.validate(instance=data, schema=schema)
        except jsonschema.ValidationError as exc:
            errors.append(f"Schema: {exc.message} at {list(exc.path)}")
        except jsonschema.SchemaError as exc:
            errors.append(f"Schema definition error: {exc.message}")
        return errors

    def _run_assertions(self, data: dict[str, Any], assertions: list[dict[str, str]]) -> list[str]:
        errors: list[str] = []
        for assertion in assertions:
            field = assertion.get("field", "")
            rule = assertion.get("rule", "")
            value = self._nested_get(data, field.replace("data.", ""))
            passed, reason = self._evaluate_rule(value, rule, data)
            if not passed:
                errors.append(f"Assertion failed: {field} {rule} — {reason}")
        return errors

    def _evaluate_rule(self, value: Any, rule: str, context: dict[str, Any]) -> tuple[bool, str]:
        if rule == "not_null":
            return (value is not None, "value is null")

        if rule.startswith("min_length:"):
            n = int(rule.split(":")[1])
            if value is None:
                return (False, "value is null")
            return (len(value) >= n, f"length {len(value)} < {n}")

        if rule.startswith("max_length:"):
            n = int(rule.split(":")[1])
            if value is None:
                return (True, "")
            return (len(value) <= n, f"length {len(value)} > {n}")

        if rule.startswith("valid_if:"):
            condition = rule.replace("valid_if:", "").strip()
            if " == " in condition:
                parts = condition.split(" == ")
                field_path = parts[0].strip().replace("data.", "")
                expected = parts[1].strip().strip("'\"")
                actual = str(self._nested_get(context, field_path))
                if actual != expected:
                    return (True, "condition not applicable")
                return (value is not None and len(value) > 0, "condition true but value empty")

        if rule == "is_boolean":
            return (isinstance(value, bool), f"expected bool, got {type(value).__name__}")

        if rule == "is_number":
            return (
                isinstance(value, (int, float)),
                f"expected number, got {type(value).__name__}",
            )

        logger.warning("Unknown assertion rule: %s", rule)
        return (True, "")

    def _nested_get(self, data: dict[str, Any], path: str) -> Any:
        cur: Any = data
        for p in path.split("."):
            if not isinstance(cur, dict):
                return None
            cur = cur.get(p)
        return cur
