"""
SYNDICATE AI — Workflow Registry
File: src/syndicate/registry/workflow_registry.py
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from syndicate.core.models import WorkflowDefinition

logger = logging.getLogger(__name__)


class WorkflowRegistry:
    """Loads all YAML workflow DAGs on startup. O(1) lookup by workflow ID."""

    def __init__(self, workflows_dir: Path) -> None:
        self._workflows: dict[str, WorkflowDefinition] = {}
        self._load_from_directory(workflows_dir)

    def _load_from_directory(self, workflows_dir: Path) -> None:
        count = 0
        for yaml_file in workflows_dir.rglob("*.yaml"):
            try:
                with open(yaml_file) as f:
                    raw = yaml.safe_load(f)
                wf = WorkflowDefinition.model_validate(raw)
                self._workflows[wf.id] = wf
                count += 1
            except Exception as exc:
                logger.warning(f"Failed to load workflow from {yaml_file}: {exc}")
        logger.info(f"Workflow Registry loaded {count} workflows from {workflows_dir}")

    def get(self, workflow_id: str) -> WorkflowDefinition | None:
        return self._workflows.get(workflow_id)

    def list_all(self) -> list[WorkflowDefinition]:
        return list(self._workflows.values())
