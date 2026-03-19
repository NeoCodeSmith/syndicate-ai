<div align="center">

<img src="docs/assets/syndicate-banner.png" alt="SYNDICATE AI" width="100%" />

# SYNDICATE AI

### Deterministic Multi-Agent Orchestration Platform

**Production-grade AI agent execution with typed contracts, state persistence, and observable pipelines.**

[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Celery](https://img.shields.io/badge/Celery-5.4-37814A?style=flat-square&logo=celery&logoColor=white)](https://celeryq.dev)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791?style=flat-square&logo=postgresql&logoColor=white)](https://postgresql.org)
[![Redis](https://img.shields.io/badge/Redis-7-DC382D?style=flat-square&logo=redis&logoColor=white)](https://redis.io)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=flat-square&logo=docker&logoColor=white)](https://docker.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow?style=flat-square)](LICENSE)
[![CI](https://img.shields.io/github/actions/workflow/status/NeoCodeSmith/syndicate-ai/ci.yml?branch=main&style=flat-square&label=CI)](https://github.com/NeoCodeSmith/syndicate-ai/actions)

---

[**Documentation**](docs/) · [**Quick Start**](#-quick-start) · [**Agent Catalog**](agents/) · [**Architecture**](docs/architecture/) · [**Contributing**](CONTRIBUTING.md)

</div>

---

## What is SYNDICATE AI?

SYNDICATE AI is a **deterministic, production-grade multi-agent orchestration platform**. It gives every agent in your system a typed input contract, a validated output schema, a defined failure handler, and measurable success criteria — then wires them together into executable DAG workflows with full state persistence.

**The core principle**: agents are not personas. They are execution units with contracts.

### What makes it different

| Approach | What you get |
|---|---|
| Prompt-based agents | Non-deterministic outputs, no validation, no state, no real orchestration |
| **SYNDICATE AI** | **Typed I/O contracts · DAG execution engine · State machine · Memory persistence · Validation gates** |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         SYNDICATE AI                            │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Interface Layer  (FastAPI · API Key Auth · Rate Limit)  │   │
│  └────────────────────────────┬─────────────────────────────┘   │
│                               │                                 │
│  ┌────────────────────────────▼─────────────────────────────┐   │
│  │  Orchestration Layer  (DAG Executor · State Machine)     │   │
│  │  PENDING → ACTIVE → VERIFIED → COMMITTED                 │   │
│  └──────────┬──────────────────────────┬────────────────────┘   │
│             │                          │                        │
│  ┌──────────▼──────────┐  ┌────────────▼──────────────────┐    │
│  │   Memory Layer      │  │   Execution Layer             │    │
│  │   PostgreSQL (WAL)  │  │   Celery Workers              │    │
│  │   Redis (hot cache) │  │   LLM Provider (pluggable)    │    │
│  └─────────────────────┘  └────────────┬──────────────────┘    │
│                                        │                        │
│  ┌─────────────────────────────────────▼──────────────────┐    │
│  │  Validation Layer  (Pydantic · JSON Schema · Assertions)│    │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Five execution layers, each with a single responsibility:**

1. **Interface Layer** — HTTP ingress via FastAPI. API key auth, rate limiting, request validation.
2. **Orchestration Layer** — Parses workflow DAGs, manages state transitions, dispatches tasks, handles retries and escalation.
3. **Execution Layer** — Celery workers that call LLMs with rendered system prompts and enforce JSON output.
4. **Validation Layer** — Pydantic schema enforcement on every agent output before DAG advancement.
5. **Memory Layer** — PostgreSQL for durable persistence + Redis for hot context across steps.

---

## Agent Contract System

Every agent in SYNDICATE AI is defined by a **YAML contract** — not a markdown persona. Each contract specifies exactly what the agent accepts, produces, and how it fails.

```yaml
# agents/engineering/distributed-systems-architect.yaml

id: "engineering.distributed-systems-architect"
name: "Distributed Systems Architect"
version: "1.0.0"
division: "engineering"

role_definition:
  mandate: "Design scalable, fault-tolerant backend systems and APIs."
  authority_level: "EXECUTION"

input_schema:
  type: object
  required: [project_brief, scale_requirements]
  properties:
    project_brief: { type: string }
    scale_requirements: { type: object }

output_schema:
  type: object
  required: [agent_id, workflow_id, step_id, status, data]
  properties:
    data:
      required: [architecture_pattern, service_map, data_model, risk_register]

execution:
  temperature: 0.1        # Low = deterministic
  max_tokens: 8192
  output_format: "json"   # Enforced

failure:
  max_retries: 2
  retry_strategy: "exponential_backoff"
  failure_handler: "orchestration.workflow-controller"

success_metrics:
  primary: "All required output fields populated and schema-valid"
  assertions:
    - field: "data.service_map"
      rule: "min_length:2"
    - field: "data.risk_register"
      rule: "min_length:3"
```

---

## Workflow DAGs

Workflows are defined as YAML DAGs — not markdown runbooks. The engine executes them deterministically.

```yaml
# workflows/startup-mvp.yaml

id: "startup-mvp"
name: "Startup MVP Pipeline"
version: "1.0.0"
initial_step: "market-analysis"

steps:
  - name: "market-analysis"
    agent_id: "product.market-intelligence-analyst"
    on_success: "system-architecture"
    on_failure: "ESCALATE"
    timeout_seconds: 120

  - name: "system-architecture"
    agent_id: "engineering.distributed-systems-architect"
    input_mappings:
      - from_step: "market-analysis"
        from_field: "target_domain"
        to_field: "project_brief"
    on_success: "ui-design"
    on_failure: "ESCALATE"

  - name: "ui-design"
    agent_id: "design.visual-systems-designer"
    parallel_with: ["seo-strategy"]
    on_success: "qa-audit"

  - name: "seo-strategy"
    agent_id: "marketing.organic-search-engineer"
    on_success: "qa-audit"

  - name: "qa-audit"
    agent_id: "testing.production-readiness-auditor"
    on_success: null  # terminal step
```

---

## Agent Catalog

SYNDICATE AI ships with **30+ production agents** across 8 divisions. All renamed from vague titles to professional designations.

### Engineering Division

| Agent ID | Role | Capabilities |
|---|---|---|
| `engineering.distributed-systems-architect` | Distributed Systems Architect | system-design, api-contracts, data-modeling, risk-analysis |
| `engineering.ui-engineer` | UI Engineer | react, vue, angular, css-systems, core-web-vitals |
| `engineering.principal-software-engineer` | Principal Software Engineer | laravel, livewire, advanced-patterns, architecture |
| `engineering.platform-reliability-engineer` | Platform Reliability Engineer | ci-cd, kubernetes, docker, cloud-infra |
| `engineering.ml-systems-engineer` | ML Systems Engineer | model-deployment, pipelines, embeddings, fine-tuning |
| `engineering.appsec-architect` | Application Security Architect | threat-modeling, secure-code-review, sast, pen-testing |
| `engineering.mobile-platform-engineer` | Mobile Platform Engineer | ios, android, react-native, flutter |
| `engineering.sre-commander` | Site Reliability Commander | incident-management, post-mortems, on-call |
| `engineering.poc-engineer` | Proof-of-Concept Engineer | rapid-prototyping, mvp, hackathon |
| `engineering.docs-engineer` | Developer Documentation Engineer | api-docs, tutorials, runbooks |

### Design Division

| Agent ID | Role | Capabilities |
|---|---|---|
| `design.visual-systems-designer` | Visual Systems Designer | component-libraries, design-systems, figma |
| `design.user-intelligence-analyst` | User Intelligence Analyst | user-testing, behavioral-analysis, research |
| `design.design-systems-architect` | Design Systems Architect | css-architecture, token-systems, implementation |
| `design.brand-identity-strategist` | Brand Identity Strategist | brand-strategy, identity, positioning |
| `design.interaction-experience-designer` | Interaction Experience Designer | micro-interactions, animations, gamification, delight |

### Marketing Division

| Agent ID | Role | Capabilities |
|---|---|---|
| `marketing.growth-systems-engineer` | Growth Systems Engineer | acquisition, viral-loops, conversion-optimization |
| `marketing.organic-search-engineer` | Organic Search Engineer | technical-seo, aeo, schema-markup, link-building |
| `marketing.content-systems-strategist` | Content Systems Strategist | editorial-calendars, multi-platform, brand-storytelling |
| `marketing.community-growth-specialist` | Community Growth Specialist | reddit, forums, authentic-engagement |
| `marketing.social-authority-strategist` | Social Authority Strategist | twitter, linkedin, thought-leadership |

### Product · PM · Testing · Support

| Agent ID | Role | Division |
|---|---|---|
| `product.market-intelligence-analyst` | Market Intelligence Analyst | product |
| `product.backlog-architect` | Product Backlog Architect | product |
| `product.voc-analyst` | Voice of Customer Analyst | product |
| `pm.program-director` | Program Director | pm |
| `pm.delivery-lead` | Delivery Lead | pm |
| `pm.scope-governance-manager` | Scope Governance Manager | pm |
| `testing.qa-verification-engineer` | QA Verification Engineer | testing |
| `testing.production-readiness-auditor` | Production Readiness Auditor | testing |
| `support.customer-success-engineer` | Customer Success Engineer | support |
| `support.bi-analyst` | Business Intelligence Analyst | support |
| `orchestration.workflow-controller` | Workflow Execution Controller | orchestration |

---

## Agent State Lifecycle

Every agent execution follows a deterministic state machine:

```
PENDING ──► ACTIVE ──► VERIFIED ──► COMMITTED
                │
                ▼
            RETRYING ──► (attempt < max) ──► ACTIVE
                │
                ▼ (attempt >= max)
            ESCALATED
```

---

## Quick Start

### Prerequisites

- Docker + Docker Compose
- An OpenAI-compatible API key (OpenAI, Anthropic via proxy, or Ollama)

### 1. Clone and configure

```bash
git clone https://github.com/NeoCodeSmith/syndicate-ai.git
cd syndicate-ai
cp .env.example .env
# Edit .env — add your LLM API key
```

### 2. Start the stack

```bash
docker compose up -d
```

This starts: FastAPI (port 8000), Celery worker, PostgreSQL, Redis, Grafana (port 3000).

### 3. Verify

```bash
curl http://localhost:8000/health
# {"status": "healthy", "version": "1.0.0"}
```

### 4. Run your first workflow

```bash
# Start the startup-mvp workflow
curl -X POST http://localhost:8000/api/v1/workflows/startup-mvp/execute \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "context": {
      "project_brief": "B2B SaaS for invoice automation",
      "target_market": "SMB accounting teams"
    }
  }'

# Check status
curl http://localhost:8000/api/v1/executions/{execution_id} \
  -H "X-API-Key: your-api-key"
```

### 5. Explore the API

Interactive docs at: **http://localhost:8000/docs**

---

## Project Structure

```
syndicate-ai/
├── src/
│   └── syndicate/
│       ├── api/
│       │   └── main.py              # FastAPI routes + auth + middleware
│       ├── core/
│       │   └── models.py            # All Pydantic models + enums
│       ├── orchestration/
│       │   └── engine.py            # DAG executor + state machine
│       ├── execution/
│       │   └── engine.py            # LLM caller + Celery tasks
│       ├── memory/
│       │   └── store.py             # Redis + PostgreSQL memory
│       ├── registry/
│       │   └── agent_registry.py    # YAML agent loader + capability router
│       └── validation/
│           └── engine.py            # Pydantic schema + assertion runner
│
├── agents/                          # YAML agent contract definitions
│   ├── engineering/
│   ├── design/
│   ├── marketing/
│   ├── product/
│   ├── pm/
│   ├── testing/
│   ├── support/
│   └── orchestration/
│
├── workflows/                       # YAML DAG workflow definitions
│   └── examples/
│       ├── startup-mvp.yaml
│       ├── marketing-campaign.yaml
│       └── enterprise-feature.yaml
│
├── docs/
│   ├── architecture/
│   │   ├── overview.md
│   │   ├── agent-contracts.md
│   │   └── workflow-dags.md
│   ├── api/
│   │   └── reference.md
│   └── guides/
│       ├── getting-started.md
│       ├── writing-agents.md
│       └── building-workflows.md
│
├── tests/
│   ├── unit/
│   └── integration/
│
├── .github/
│   └── workflows/
│       └── ci.yml
│
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── requirements-dev.txt
├── .env.example
├── pyproject.toml
└── README.md
```

---

## API Reference

### Workflows

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/workflows/{id}/execute` | Start a workflow execution |
| `GET` | `/api/v1/executions/{id}` | Get execution status |
| `GET` | `/api/v1/executions/{id}/steps` | Get all step results |
| `POST` | `/api/v1/executions/{id}/abort` | Abort a running execution |

### Agents

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/agents` | List all registered agents |
| `GET` | `/api/v1/agents/{id}` | Get full agent contract |
| `POST` | `/api/v1/agents/{id}/invoke` | Invoke a single agent directly |

### System

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `GET` | `/metrics` | Prometheus metrics |
| `GET` | `/docs` | OpenAPI interactive docs |

All endpoints require the `X-API-Key` header.

**Standard response codes:** `200` · `202` · `400` · `401` · `403` · `404` · `429` · `500`

---

## Configuration

```env
# .env.example

# ─── LLM Provider ───────────────────────────────────────────────
LLM_BASE_URL=https://api.anthropic.com/v1
LLM_API_KEY=your-api-key-here
LLM_MODEL=claude-opus-4-6

# ─── Database ───────────────────────────────────────────────────
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=syndicate
POSTGRES_USER=syndicate
POSTGRES_PASSWORD=change-me-in-production

# ─── Redis ──────────────────────────────────────────────────────
REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/1
CELERY_RESULT_BACKEND=redis://redis:6379/2

# ─── API Auth ───────────────────────────────────────────────────
SYNDICATE_API_KEYS=sk-your-key-1,sk-your-key-2

# ─── Execution ──────────────────────────────────────────────────
MAX_STEPS_PER_WORKFLOW=100
DEFAULT_STEP_TIMEOUT_SECONDS=300
CELERY_WORKER_CONCURRENCY=4

# ─── Observability ──────────────────────────────────────────────
LOG_LEVEL=INFO
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
```

---

## Writing a Custom Agent

Create a YAML file in `agents/{division}/`:

```yaml
id: "engineering.my-custom-agent"
name: "My Custom Agent"
version: "1.0.0"
division: "engineering"

role_definition:
  mandate: "One sentence: what this agent does."
  scope_in: "What problems it solves"
  scope_out: "What it does NOT do"
  authority_level: "EXECUTION"   # ADVISORY | EXECUTION | APPROVAL

capabilities:
  - "my-capability-1"
  - "my-capability-2"

input_schema:
  type: object
  required: [required_field]
  properties:
    required_field:
      type: string
      description: "Description of what this field is"

output_schema:
  type: object
  required: [agent_id, workflow_id, step_id, status, data]
  properties:
    data:
      type: object
      required: [result]
      properties:
        result: { type: string }

execution:
  system_prompt_template: |
    You are a [role]. Your task is: {input.required_field}
    Return JSON only. No prose.
  max_tokens: 2048
  temperature: 0.2
  output_format: "json"

failure:
  conditions:
    - "data.result is null or empty"
  max_retries: 3
  retry_strategy: "exponential_backoff"
  failure_handler: "orchestration.workflow-controller"

success_metrics:
  primary: "data.result is populated and non-empty"
  assertions:
    - field: "data.result"
      rule: "not_null"

tone:
  style: "technical"
  voice: "Precise and direct."
```

No code required. Drop the file and restart — the registry picks it up automatically.

---

## Building a Custom Workflow

```yaml
# workflows/my-workflow.yaml

id: "my-workflow"
name: "My Custom Workflow"
version: "1.0.0"
description: "What this workflow accomplishes"
initial_step: "first-step"

context_schema:                  # Validates initial inputs
  type: object
  required: [input_field]
  properties:
    input_field: { type: string }

steps:
  - name: "first-step"
    agent_id: "engineering.my-custom-agent"
    input_static:
      mode: "analysis"
    on_success: "second-step"
    on_failure: "ESCALATE"
    timeout_seconds: 120

  - name: "second-step"
    agent_id: "testing.production-readiness-auditor"
    input_mappings:
      - from_step: "first-step"
        from_field: "result"
        to_field: "artifact_to_review"
    on_success: null              # Terminal step
    on_failure: "ABORT"
```

---

## Observability

SYNDICATE AI emits OpenTelemetry traces, Prometheus metrics, and structured JSON logs on every operation.

**Key metrics:**
- `syndicate_workflow_executions_total` — workflows started by status
- `syndicate_step_duration_seconds` — p50/p95/p99 per agent
- `syndicate_llm_tokens_total` — token consumption by agent and model
- `syndicate_validation_failures_total` — schema failures by agent
- `syndicate_retry_total` — retries by agent and strategy

Grafana dashboard included at `docker compose up` on port 3000.

---

## Deployment

### Docker Compose (Development / Single-Host)

```bash
docker compose up -d
docker compose logs -f api worker
```

### Production (Kubernetes)

Helm chart in `deploy/helm/syndicate-ai/`. See [deployment guide](docs/guides/deployment.md).

```bash
helm install syndicate-ai deploy/helm/syndicate-ai/ \
  --namespace syndicate \
  --values deploy/helm/syndicate-ai/values.prod.yaml
```

### Health Checks

```
GET /health             → {"status": "healthy"}
GET /health/ready       → database + redis connectivity
GET /health/live        → process alive
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

**Quick contribution guide:**
1. Fork → feature branch → PR
2. For new agents: add YAML contract + unit test
3. For new workflows: add YAML + integration test
4. All PRs must pass CI (lint + typecheck + tests)

---

## License

MIT — see [LICENSE](LICENSE).

---

<div align="center">

Built by [NeoCodeSmith](https://github.com/NeoCodeSmith) · **SYNDICATE AI**

</div>
