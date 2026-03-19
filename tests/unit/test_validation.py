"""Unit tests for the Validation Engine."""
import pytest
from syndicate.validation.engine import ValidationEngine
from syndicate.core.models import (
    AgentOutput, AgentOutputStatus, AgentDefinition,
    AgentExecutionConfig, AgentFailureConfig, AgentSuccessMetrics, AgentTone,
)


def make_agent_def(assertions=None):
    return AgentDefinition(
        id="test.agent",
        name="Test Agent",
        version="1.0.0",
        division="test",
        role_definition={"mandate": "test"},
        input_schema={"type": "object"},
        output_schema={
            "type": "object",
            "required": ["agent_id", "workflow_id", "step_id", "status", "data"],
        },
        execution=AgentExecutionConfig(
            system_prompt_template="test",
            max_tokens=1024,
            temperature=0.2,
        ),
        failure=AgentFailureConfig(conditions=[]),
        success_metrics=AgentSuccessMetrics(
            primary="test passes",
            assertions=assertions or [],
        ),
        tone=AgentTone(style="technical", voice="test"),
    )


def make_output(data):
    return AgentOutput(
        agent_id="test.agent",
        workflow_id="wf-1",
        step_id="step-1",
        status=AgentOutputStatus.SUCCESS,
        data=data,
    )


class TestValidationEngine:
    def setup_method(self):
        self.engine = ValidationEngine()

    def test_passes_valid_output(self):
        agent_def = make_agent_def(
            assertions=[{"field": "data.result", "rule": "not_null"}]
        )
        output = make_output({"result": "some value"})
        result = self.engine.validate(output, agent_def)
        assert result.passed

    def test_fails_null_field(self):
        agent_def = make_agent_def(
            assertions=[{"field": "data.result", "rule": "not_null"}]
        )
        output = make_output({"result": None})
        result = self.engine.validate(output, agent_def)
        assert not result.passed
        assert any("not_null" in e for e in result.errors)

    def test_min_length_passes(self):
        agent_def = make_agent_def(
            assertions=[{"field": "data.items", "rule": "min_length:2"}]
        )
        output = make_output({"items": ["a", "b", "c"]})
        result = self.engine.validate(output, agent_def)
        assert result.passed

    def test_min_length_fails(self):
        agent_def = make_agent_def(
            assertions=[{"field": "data.items", "rule": "min_length:3"}]
        )
        output = make_output({"items": ["only-one"]})
        result = self.engine.validate(output, agent_def)
        assert not result.passed
