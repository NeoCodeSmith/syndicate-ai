# Architecture Overview

## Core Design Principle

Every component in SYNDICATE AI has a single, well-defined responsibility. No God classes. No narrative-driven behavior. All agent execution is governed by typed contracts, not prose instructions.

## The Five Layers

### 1. Interface Layer (`src/syndicate/api/`)
FastAPI application. Handles HTTP ingress, API key authentication, rate limiting, and request validation. **Stateless** — all state lives in the Orchestration and Memory layers.

### 2. Orchestration Layer (`src/syndicate/orchestration/`)
The DAG executor. Parses workflow YAML files into executable execution plans. Manages all state transitions (`PENDING → ACTIVE → VERIFIED → COMMITTED`). Dispatches Celery tasks. Enforces retry limits and escalation routing. **Does not call the LLM directly.**

### 3. Execution Layer (`src/syndicate/execution/`)
Celery workers that perform the actual LLM calls. Each task: loads the agent definition, renders the system prompt, calls the LLM provider, parses JSON output, runs schema validation. **Isolated** — each task has no access to other tasks' state.

### 4. Validation Layer (`src/syndicate/validation/`)
Two-pass validation on every agent output. Pass 1: JSON Schema (structural). Pass 2: success assertions (semantic). If either pass fails, the Orchestration Engine is notified to retry or escalate. **Nothing advances the DAG without passing validation.**

### 5. Memory Layer (`src/syndicate/memory/`)
Redis for hot context (sub-millisecond reads, TTL-based) + PostgreSQL for durable audit trail. Enables cross-step data passing via the `input_mappings` system in workflow DAGs. Agents never communicate directly — all data flows through Memory.

## State Machine

```
PENDING → ACTIVE → VERIFIED → COMMITTED
                ↘ RETRYING → ACTIVE (attempt < max)
                          ↘ ESCALATED (attempt >= max)
```

## Agent Communication Protocol

Agents never call each other. Data flows via Memory:

```
Agent A completes → Output stored in Redis (workflow:{id}:step:{name}:output)
                  → Orchestration Engine reads next step's input_mappings
                  → Fetches Agent A's output fields from Redis
                  → Constructs Agent B's input
                  → Dispatches Celery task for Agent B
```

## Workflow DAG

Workflows are YAML files. The engine never interprets natural language to decide what runs next — it reads `on_success` and `on_failure` fields deterministically.
