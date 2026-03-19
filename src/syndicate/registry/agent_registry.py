"""
SYNDICATE AI — Agent Registry
File: src/syndicate/registry/agent_registry.py
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from syndicate.core.models import AgentDefinition

logger = logging.getLogger(__name__)


class AgentRegistry:
    """Loads YAML agent contracts on startup. O(1) lookup by agent_id."""

    def __init__(self, agents_dir: Path) -> None:
        self._agents: dict[str, AgentDefinition] = {}
        self._load(agents_dir)

    def _load(self, agents_dir: Path) -> None:
        count = 0
        for f in Path(agents_dir).rglob("*.yaml"):
            try:
                raw = yaml.safe_load(f.read_text())
                agent = AgentDefinition.model_validate(raw)
                self._agents[agent.id] = agent
                count += 1
            except Exception as exc:
                logger.warning(f"Skipping {f}: {exc}")
        logger.info(f"AgentRegistry: loaded {count} agents from {agents_dir}")

    def get(self, agent_id: str) -> AgentDefinition | None:
        return self._agents.get(agent_id)

    def list_all(self) -> list[AgentDefinition]:
        return list(self._agents.values())

    def by_capability(self, cap: str) -> list[AgentDefinition]:
        return [a for a in self._agents.values() if cap in a.capabilities]

    def by_division(self, div: str) -> list[AgentDefinition]:
        return [a for a in self._agents.values() if a.division == div]

    def route(self, capabilities: list[str]) -> str | None:
        best, score = None, 0
        for aid, agent in self._agents.items():
            s = len(set(capabilities) & set(agent.capabilities))
            if s > score:
                score, best = s, aid
        return best
