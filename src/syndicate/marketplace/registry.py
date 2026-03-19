"""
SYNDICATE AI — Agent Marketplace
File: src/syndicate/marketplace/registry.py

Community marketplace for sharing and discovering agent contracts.
Agents can be published, rated, installed, and version-pinned.

Marketplace tiers:
  official  — shipped with SYNDICATE AI, maintained by core team
  verified  — community agents that passed security + quality review
  community — unreviewed community submissions

Publish flow:
  1. Author writes agent YAML contract
  2. Submits via CLI: syndicate marketplace publish my-agent.yaml
  3. CI validates schema, security scan, test coverage
  4. Verified tier requires manual review approval
  5. Installed agents live in ~/.syndicate/agents/ or org agents dir

Install flow:
  syndicate marketplace install engineering.blockchain-auditor
  syndicate marketplace install engineering.blockchain-auditor@2.1.0
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class MarketplaceAgent:
    """An agent listing in the marketplace."""

    agent_id: str
    name: str
    division: str
    version: str
    author: str
    author_org: str
    description: str
    capabilities: list[str]
    tier: str  # official | verified | community
    downloads: int
    rating: float  # 0.0 - 5.0
    rating_count: int
    tags: list[str]
    contract: dict[str, Any]  # full YAML as dict
    published_at: str
    updated_at: str
    verified: bool
    security_scan_passed: bool

    @property
    def install_command(self) -> str:
        return f"syndicate marketplace install {self.agent_id}@{self.version}"

    @property
    def tier_badge(self) -> str:
        badges = {
            "official": "🏛️ Official",
            "verified": "✅ Verified",
            "community": "👥 Community",
        }
        return badges.get(self.tier, self.tier)


@dataclass
class MarketplaceSearchResult:
    agents: list[MarketplaceAgent]
    total: int
    page: int
    per_page: int
    query: str
    filters: dict[str, Any] = field(default_factory=dict)


class AgentMarketplace:
    """
    Agent marketplace backed by Redis.
    Production would use a proper database with full-text search.
    This implementation uses Redis with JSON storage and manual filtering.

    For scale: replace Redis backend with PostgreSQL + pgvector
    for semantic search over agent descriptions.
    """

    def __init__(self, redis_client: Any) -> None:
        self._redis = redis_client

    # ── Search & Discovery ──────────────────────────────────────────────────

    def search(
        self,
        query: str = "",
        division: str | None = None,
        capability: str | None = None,
        tier: str | None = None,
        sort_by: str = "downloads",  # downloads | rating | updated_at
        page: int = 1,
        per_page: int = 20,
    ) -> MarketplaceSearchResult:
        """Search marketplace agents with optional filters."""
        all_agents = self._list_all_agents()

        # Filter
        filtered = all_agents
        if query:
            q = query.lower()
            filtered = [
                a
                for a in filtered
                if q in a.name.lower()
                or q in a.description.lower()
                or any(q in c for c in a.capabilities)
                or any(q in t for t in a.tags)
            ]
        if division:
            filtered = [a for a in filtered if a.division == division]
        if capability:
            filtered = [a for a in filtered if capability in a.capabilities]
        if tier:
            filtered = [a for a in filtered if a.tier == tier]

        # Sort
        reverse = True
        if sort_by == "downloads":
            filtered.sort(key=lambda a: a.downloads, reverse=reverse)
        elif sort_by == "rating":
            filtered.sort(key=lambda a: (a.rating, a.rating_count), reverse=reverse)
        elif sort_by == "updated_at":
            filtered.sort(key=lambda a: a.updated_at, reverse=reverse)

        # Paginate
        total = len(filtered)
        start = (page - 1) * per_page
        end = start + per_page
        page_agents = filtered[start:end]

        return MarketplaceSearchResult(
            agents=page_agents,
            total=total,
            page=page,
            per_page=per_page,
            query=query,
            filters={"division": division, "capability": capability, "tier": tier},
        )

    def get_agent(self, agent_id: str, version: str | None = None) -> MarketplaceAgent | None:
        """Get a specific marketplace agent, optionally pinned to a version."""
        if version:
            key = f"marketplace:agent:{agent_id}:{version}"
        else:
            # Get latest
            latest_key = f"marketplace:latest:{agent_id}"
            version = self._redis.get(latest_key)
            if not version:
                return None
            key = f"marketplace:agent:{agent_id}:{version}"

        data = self._redis.get(key)
        if not data:
            return None
        return self._dict_to_agent(json.loads(data))

    def get_versions(self, agent_id: str) -> list[str]:
        """List all available versions of a marketplace agent."""
        key = f"marketplace:versions:{agent_id}"
        versions = self._redis.lrange(key, 0, -1)
        return [v for v in (versions or [])]

    # ── Publish ─────────────────────────────────────────────────────────────

    def publish(
        self,
        contract: dict[str, Any],
        author: str,
        author_org: str,
        description: str,
        tags: list[str] | None = None,
        tier: str = "community",
    ) -> MarketplaceAgent:
        """
        Publish an agent contract to the marketplace.
        Runs basic validation before accepting.
        """
        import datetime

        agent_id = contract.get("id", "")
        if not agent_id:
            raise ValueError("Agent contract must have an 'id' field")

        # Validate the contract
        from syndicate.core.models import AgentDefinition

        AgentDefinition.model_validate(contract)  # raises on invalid

        version = contract.get("version", "1.0.0")
        now = datetime.datetime.utcnow().isoformat()

        agent = MarketplaceAgent(
            agent_id=agent_id,
            name=contract.get("name", agent_id),
            division=contract.get("division", "community"),
            version=version,
            author=author,
            author_org=author_org,
            description=description,
            capabilities=contract.get("capabilities", []),
            tier=tier,
            downloads=0,
            rating=0.0,
            rating_count=0,
            tags=tags or [],
            contract=contract,
            published_at=now,
            updated_at=now,
            verified=tier in ("official", "verified"),
            security_scan_passed=False,  # set to True after CI scan
        )

        # Store
        key = f"marketplace:agent:{agent_id}:{version}"
        self._redis.set(key, json.dumps(self._agent_to_dict(agent)))

        # Update latest pointer
        self._redis.set(f"marketplace:latest:{agent_id}", version)

        # Add to versions list
        self._redis.lpush(f"marketplace:versions:{agent_id}", version)

        # Add to division index
        self._redis.sadd(f"marketplace:division:{agent.division}", agent_id)

        # Add to global index
        self._redis.sadd("marketplace:all", f"{agent_id}:{version}")

        logger.info("Published marketplace agent %s@%s by %s", agent_id, version, author)
        return agent

    # ── Install ─────────────────────────────────────────────────────────────

    def install(
        self,
        agent_id: str,
        version: str | None = None,
        install_dir: str = "agents/community",
    ) -> dict[str, Any]:
        """
        Install a marketplace agent into the local agents directory.
        Returns the installation details.
        """
        import os

        agent = self.get_agent(agent_id, version)
        if not agent:
            raise ValueError(f"Agent '{agent_id}' not found in marketplace")

        # Write YAML to install_dir
        import yaml

        os.makedirs(install_dir, exist_ok=True)
        slug = agent_id.replace(".", "-")
        filename = f"{install_dir}/{slug}.yaml"

        with open(filename, "w") as f:
            yaml.dump(agent.contract, f, default_flow_style=False, sort_keys=False)

        # Increment download count
        self._increment_downloads(agent_id, agent.version)

        logger.info("Installed %s@%s to %s", agent_id, agent.version, filename)
        return {
            "agent_id": agent_id,
            "version": agent.version,
            "installed_to": filename,
            "note": "Restart server or hot-reload will pick up the new agent automatically",
        }

    # ── Rating ───────────────────────────────────────────────────────────────

    def rate(self, agent_id: str, rating: float, reviewer: str, review: str = "") -> float:
        """Rate an agent (1.0–5.0). Returns new average rating."""
        if not 1.0 <= rating <= 5.0:
            raise ValueError("Rating must be between 1.0 and 5.0")

        agent = self.get_agent(agent_id)
        if not agent:
            raise ValueError(f"Agent '{agent_id}' not found")

        # Recalculate rolling average
        new_count = agent.rating_count + 1
        new_avg = round(((agent.rating * agent.rating_count) + rating) / new_count, 2)

        agent.rating = new_avg
        agent.rating_count = new_count

        # Update stored agent
        key = f"marketplace:agent:{agent_id}:{agent.version}"
        self._redis.set(key, json.dumps(self._agent_to_dict(agent)))

        # Store review
        review_key = f"marketplace:reviews:{agent_id}"
        review_entry = json.dumps({"reviewer": reviewer, "rating": rating, "review": review})
        self._redis.lpush(review_key, review_entry)

        return new_avg

    # ── Private ─────────────────────────────────────────────────────────────

    def _list_all_agents(self) -> list[MarketplaceAgent]:
        all_keys = self._redis.smembers("marketplace:all")
        agents = []
        for key in all_keys or []:
            parts = key.rsplit(":", 1)
            if len(parts) == 2:
                agent_id, version = parts
                agent = self.get_agent(agent_id, version)
                if agent:
                    agents.append(agent)
        return agents

    def _increment_downloads(self, agent_id: str, version: str) -> None:
        agent = self.get_agent(agent_id, version)
        if agent:
            agent.downloads += 1
            key = f"marketplace:agent:{agent_id}:{version}"
            self._redis.set(key, json.dumps(self._agent_to_dict(agent)))

    def _agent_to_dict(self, a: MarketplaceAgent) -> dict[str, Any]:
        return {
            "agent_id": a.agent_id,
            "name": a.name,
            "division": a.division,
            "version": a.version,
            "author": a.author,
            "author_org": a.author_org,
            "description": a.description,
            "capabilities": a.capabilities,
            "tier": a.tier,
            "downloads": a.downloads,
            "rating": a.rating,
            "rating_count": a.rating_count,
            "tags": a.tags,
            "contract": a.contract,
            "published_at": a.published_at,
            "updated_at": a.updated_at,
            "verified": a.verified,
            "security_scan_passed": a.security_scan_passed,
        }

    def _dict_to_agent(self, d: dict[str, Any]) -> MarketplaceAgent:
        return MarketplaceAgent(**d)
