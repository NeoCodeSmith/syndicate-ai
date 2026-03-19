# Writing Agent Contracts

Agents in SYNDICATE AI are YAML files — not Python classes, not markdown personas. The runtime loads them at startup and validates them against `AgentDefinition`.

## Required Fields

| Field | Type | Description |
|---|---|---|
| `id` | string | Unique agent identifier. Convention: `{division}.{role-slug}` |
| `name` | string | Human-readable name |
| `version` | string | SemVer |
| `division` | string | Logical grouping |
| `capabilities` | string[] | Machine-readable tags used for capability routing |
| `role_definition` | object | mandate, scope_in, scope_out, authority_level |
| `input_schema` | JSON Schema | Defines exactly what this agent accepts |
| `output_schema` | JSON Schema | Defines exactly what this agent produces |
| `execution` | object | system_prompt_template, max_tokens, temperature |
| `failure` | object | conditions, max_retries, retry_strategy, failure_handler |
| `success_metrics` | object | primary metric + assertion list |
| `tone` | object | style + voice (guidance only, not execution) |

## Temperature Guidelines

| Use case | Temperature |
|---|---|
| Architecture, code generation | 0.0 – 0.15 |
| Analysis, research, QA | 0.15 – 0.25 |
| Content, copy, strategy | 0.25 – 0.45 |
| Creative, interaction design | 0.35 – 0.55 |

## Assertion Rules

| Rule | Description |
|---|---|
| `not_null` | Field must be present and non-null |
| `min_length:N` | Array or string must have length ≥ N |
| `max_length:N` | Array or string must have length ≤ N |
| `is_boolean` | Field must be a boolean |
| `is_number` | Field must be numeric |
| `valid_if: data.X == Y` | Only assert if condition is true |

## Step-by-Step: Creating a New Agent

1. Choose a division and `id` following the `{division}.{role}` convention.
2. Define `input_schema` — what does this agent need to do its job?
3. Define `output_schema` — what does it produce? Must wrap in the standard envelope.
4. Write the `system_prompt_template` using `{input.field}` placeholders.
5. Set `temperature` to the lowest value that produces useful output.
6. Define `success_metrics.assertions` — what must be true for output to pass?
7. Set a `failure_handler` — what agent runs if this one hits max retries?
8. Drop the file in `agents/{division}/`. Restart the stack. The registry loads it automatically.
