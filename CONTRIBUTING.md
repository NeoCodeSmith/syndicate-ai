# Contributing to SYNDICATE AI

## Adding a New Agent

1. Pick a division (`engineering`, `design`, `marketing`, `product`, `pm`, `testing`, `support`, `orchestration`)
2. Create `agents/{division}/{role-slug}.yaml`
3. Follow the [agent contract guide](docs/guides/writing-agents.md)
4. Add a unit test to `tests/unit/`
5. Run `python scripts/validate_agents.py` — must pass
6. Open a PR

## Adding a New Workflow

1. Create `workflows/{name}.yaml`
2. Run `python scripts/validate_workflows.py` — must pass
3. Add an integration test
4. Open a PR

## Code Style

- Python 3.12+, strict type hints
- `ruff check` must pass with zero errors
- `mypy src/` must pass
- All PRs need green CI

## PR Requirements

- [ ] `validate_agents.py` passes
- [ ] `validate_workflows.py` passes
- [ ] `pytest tests/unit/` passes
- [ ] `ruff check` passes
- [ ] `mypy src/syndicate` passes
