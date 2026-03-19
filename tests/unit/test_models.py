"""Unit tests for core Pydantic models."""
import pytest
from syndicate.core.models import (
    AgentOutput, AgentOutputStatus, WorkflowDefinition,
    WorkflowExecution, WorkflowStatus, WorkflowStep,
)


def make_step(**kwargs):
    defaults = {"name": "step-1", "agent_id": "engineering.ui-engineer"}
    return WorkflowStep(**{**defaults, **kwargs})


class TestWorkflowDefinition:
    def test_valid_workflow(self):
        wf = WorkflowDefinition(
            name="Test Workflow",
            initial_step="step-1",
            steps=[make_step(on_success=None)],
        )
        assert wf.name == "Test Workflow"
        assert len(wf.steps) == 1

    def test_rejects_unknown_on_success(self):
        with pytest.raises(ValueError, match="unknown on_success"):
            WorkflowDefinition(
                name="Bad Workflow",
                initial_step="step-1",
                steps=[make_step(on_success="nonexistent-step")],
            )

    def test_allows_escalate_on_failure(self):
        wf = WorkflowDefinition(
            name="Workflow",
            initial_step="step-1",
            steps=[make_step(on_failure="ESCALATE")],
        )
        assert wf.steps[0].on_failure == "ESCALATE"

    def test_multi_step_dag(self):
        wf = WorkflowDefinition(
            name="Multi Step",
            initial_step="step-1",
            steps=[
                make_step(name="step-1", on_success="step-2"),
                make_step(name="step-2", on_success=None),
            ],
        )
        assert len(wf.steps) == 2


class TestAgentOutput:
    def test_success_output(self):
        out = AgentOutput(
            agent_id="engineering.ui-engineer",
            workflow_id="wf-1",
            step_id="step-1",
            status=AgentOutputStatus.SUCCESS,
            data={"component_code": "const Btn = () => <button />"},
        )
        assert out.status == AgentOutputStatus.SUCCESS
        assert out.data["component_code"]

    def test_failed_output_has_errors(self):
        out = AgentOutput(
            agent_id="engineering.ui-engineer",
            workflow_id="wf-1",
            step_id="step-1",
            status=AgentOutputStatus.FAILED,
            data={},
            errors=["LLM call timed out"],
        )
        assert out.status == AgentOutputStatus.FAILED
        assert len(out.errors) == 1
