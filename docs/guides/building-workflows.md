# Building Workflow DAGs

Workflows define multi-agent pipelines as YAML. The Orchestration Engine executes them deterministically.

## Core Concepts

**Steps** are the nodes in your DAG. Each step specifies one agent and what to do on success or failure.

**Input mappings** are how data flows between steps. They tell the engine: "take field X from step A's output and pass it as field Y to step B's input."

**on_success / on_failure** are the DAG edges. They reference other step names, or the special values `ESCALATE` and `ABORT`.

## Input Mapping

```yaml
steps:
  - name: "step-b"
    agent_id: "engineering.ui-engineer"
    input_mappings:
      - from_step: "step-a"        # the previous step name
        from_field: "result.data"  # dot-notation path in step-a's output.data
        to_field: "feature_description"  # field in step-b's input_schema
```

## Parallel Execution

```yaml
  - name: "step-c"
    agent_id: "marketing.growth-systems-engineer"
    parallel_with: ["step-d"]     # step-c and step-d run simultaneously
    on_success: "step-e"

  - name: "step-d"
    agent_id: "design.interaction-experience-designer"
    on_success: "step-e"          # both feed into step-e
```

## Failure Routing

```yaml
on_failure: "ESCALATE"   # notify operator, pause workflow
on_failure: "ABORT"      # terminate workflow immediately
on_failure: "recovery-step"  # route to a named fallback step
```

## Running a Workflow

```bash
curl -X POST http://localhost:8000/api/v1/workflows/my-workflow/execute \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{"context": {"project_brief": "..."}}'
```
