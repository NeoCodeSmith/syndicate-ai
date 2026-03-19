"""
SYNDICATE AI — Validation Engine
File: src/syndicate/validation/engine.py

Schema enforcement and assertion runner for all agent outputs.
This is the gate that prevents invalid data from advancing the DAG.
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
    """
    Runs two validation passes on every agent output:
    1. JSON Schema validation against the agent's output_schema
    2. Success assertion checks (field presence, min length, etc.)

    If either pass fails, the output is rejected and the Orchestration
    Engine is notified to retry or escalate.
    """

    def validate(
        self, output: AgentOutput, agent_def: AgentDefinition
    ) -> ValidationResult:
        errors: list[str] = []

        # Pass 1: JSON Schema
        schema_errors = self._validate_schema(
            data={"agent_id": output.agent_id, "workflow_id": output.workflow_id,
                  "step_id": output.step_id, "status": output.status.value, "data": output.data},
            schema=agent_def.output_schema,
        )
        errors.extend(schema_errors)

        # Pass 2: Success assertions
        if not errors:  # Only run assertions if schema passes
            assertion_errors = self._run_assertions(
                output.data, agent_def.success_metrics.assertions
            )
            errors.extend(assertion_errors)

        passed = len(errors) == 0
        if not passed:
            logger.warning(
                f"Validation failed for agent '{output.agent_id}': {errors}",
                extra={"step_id": output.step_id},
            )

        return ValidationResult(passed=passed, errors=errors)

    def _validate_schema(
        self, data: dict[str, Any], schema: dict[str, Any]
    ) -> list[str]:
        errors = []
        try:
            jsonschema.validate(instance=data, schema=schema)
        except jsonschema.ValidationError as exc:
            errors.append(f"Schema: {exc.message} at {list(exc.path)}")
        except jsonschema.SchemaError as exc:
            errors.append(f"Schema definition error: {exc.message}")
        return errors

    def _run_assertions(
        self, data: dict[str, Any], assertions: list[dict[str, str]]
    ) -> list[str]:
        errors = []
        for assertion in assertions:
            field = assertion.get("field", "")
            rule = assertion.get("rule", "")
            value = self._get_nested(data, field.replace("data.", ""))

            passed, reason = self._evaluate_rule(value, rule, data)
            if not passed:
                errors.append(f"Assertion failed: {field} {rule} — {reason}")

        return errors

    def _evaluate_rule(
        self, value: Any, rule: str, context: dict[str, Any]
    ) -> tuple[bool, str]:
        if rule == "not_null":
            return (value is not None, "value is null")

        if rule.startswith("min_length:"):
            n = int(rule.split(":")[1])
            if value is None:
                return (False, "value is null")
            length = len(value)
            return (length >= n, f"length {length} < {n}")

        if rule.startswith("max_length:"):
            n = int(rule.split(":")[1])
            if value is None:
                return (True, "")  # null passes max_length
            length = len(value)
            return (length <= n, f"length {length} > {n}")

        if rule.startswith("valid_if:"):
            condition = rule.replace("valid_if:", "").strip()
            # Simple condition evaluation
            if " == " in condition:
                parts = condition.split(" == ")
                field = parts[0].strip().replace("data.", "")
                expected = parts[1].strip().strip("'\"")
                actual = str(self._get_nested(context, field))
                if actual != expected:
                    return (True, "condition not applicable")
                return (value is not None and len(value) > 0, "condition true but value empty")

        if rule == "is_boolean":
            return (isinstance(value, bool), f"expected bool, got {type(value).__name__}")

        if rule == "is_number":
            return (isinstance(value, (int, float)), f"expected number, got {type(value).__name__}")

        # Unknown rule — pass by default (log warning)
        logger.warning(f"Unknown assertion rule: {rule}")
        return (True, "")

    def _get_nested(self, data: dict, path: str) -> Any:
        """Navigate dot-notation path."""
        parts = path.split(".")
        current = data
        for part in parts:
            if not isinstance(current, dict):
                return None
            current = current.get(part)
        return current
