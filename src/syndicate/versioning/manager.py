"""
SYNDICATE AI — Workflow Versioning
File: src/syndicate/versioning/manager.py

Semantic versioning for workflow DAG definitions.
Every change to a workflow YAML is tracked with a version number,
diff, and change author. Rollback to any previous version in one call.

Version format: MAJOR.MINOR.PATCH (semver)
  MAJOR: breaking change (step removed, required field changed)
  MINOR: additive change (new step, new optional field)
  PATCH: non-structural change (description, timeout, tone)

Storage: Redis sorted set + JSON snapshots
Key: wf:versions:{workflow_id}  → sorted set of (version, timestamp)
Key: wf:snapshot:{workflow_id}:{version} → full YAML snapshot
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class WorkflowVersion:
    workflow_id: str
    version: str  # semver: "1.2.3"
    created_at: str
    created_by: str
    change_summary: str
    breaking_change: bool
    snapshot: dict[str, Any]  # full workflow definition at this version

    @property
    def semver_tuple(self) -> tuple[int, int, int]:
        parts = self.version.split(".")
        return (int(parts[0]), int(parts[1]), int(parts[2]))

    def is_newer_than(self, other: WorkflowVersion) -> bool:
        return self.semver_tuple > other.semver_tuple


@dataclass
class VersionDiff:
    from_version: str
    to_version: str
    steps_added: list[str]
    steps_removed: list[str]
    steps_modified: list[str]
    breaking: bool

    @property
    def summary(self) -> str:
        parts = []
        if self.steps_added:
            parts.append(f"+{len(self.steps_added)} steps")
        if self.steps_removed:
            parts.append(f"-{len(self.steps_removed)} steps")
        if self.steps_modified:
            parts.append(f"~{len(self.steps_modified)} modified")
        return ", ".join(parts) if parts else "no structural changes"


class WorkflowVersionManager:
    """
    Manages workflow version history with semantic versioning.

    Usage:
        manager = WorkflowVersionManager(redis_client)

        # Save a new version
        manager.save_version(
            workflow_id="startup-mvp",
            definition=wf_dict,
            created_by="akash@example.com",
            change_summary="Added QA step after architecture",
            bump="minor"
        )

        # List all versions
        versions = manager.list_versions("startup-mvp")

        # Rollback
        manager.rollback("startup-mvp", to_version="1.0.0")

        # Diff two versions
        diff = manager.diff("startup-mvp", "1.0.0", "1.1.0")
    """

    def __init__(self, redis_client: Any) -> None:
        self._redis = redis_client

    # ── Save ────────────────────────────────────────────────────────────────

    def save_version(
        self,
        workflow_id: str,
        definition: dict[str, Any],
        created_by: str = "system",
        change_summary: str = "",
        bump: str = "patch",  # major | minor | patch
    ) -> WorkflowVersion:
        """
        Save a new version of a workflow definition.
        Automatically increments semver based on bump type.
        """
        import datetime

        current = self.get_latest(workflow_id)
        if current:
            new_version = self._bump_version(current.version, bump)
        else:
            new_version = "1.0.0"

        # Compute diff if there's a previous version
        breaking = False
        if current:
            diff = self._compute_diff(current.snapshot, definition)
            breaking = diff.breaking

        version = WorkflowVersion(
            workflow_id=workflow_id,
            version=new_version,
            created_at=datetime.datetime.utcnow().isoformat(),
            created_by=created_by,
            change_summary=change_summary or f"Version {new_version}",
            breaking_change=breaking,
            snapshot=definition,
        )

        # Store snapshot
        snapshot_key = f"wf:snapshot:{workflow_id}:{new_version}"
        self._redis.set(snapshot_key, json.dumps(self._version_to_dict(version)))

        # Add to sorted set (score = unix timestamp for ordering)
        import time

        versions_key = f"wf:versions:{workflow_id}"
        self._redis.zadd(versions_key, {new_version: time.time()})

        logger.info(
            "Saved workflow version %s for '%s' (by %s)",
            new_version,
            workflow_id,
            created_by,
        )
        return version

    # ── Read ────────────────────────────────────────────────────────────────

    def get_latest(self, workflow_id: str) -> WorkflowVersion | None:
        """Get the most recent version of a workflow."""
        versions_key = f"wf:versions:{workflow_id}"
        # Get highest-scored (latest timestamp) member
        results = self._redis.zrange(versions_key, -1, -1)
        if not results:
            return None
        latest_ver = results[0]
        return self.get_version(workflow_id, latest_ver)

    def get_version(self, workflow_id: str, version: str) -> WorkflowVersion | None:
        """Get a specific version snapshot."""
        snapshot_key = f"wf:snapshot:{workflow_id}:{version}"
        data = self._redis.get(snapshot_key)
        if not data:
            return None
        return self._dict_to_version(json.loads(data))

    def list_versions(self, workflow_id: str) -> list[WorkflowVersion]:
        """List all versions in reverse chronological order."""
        versions_key = f"wf:versions:{workflow_id}"
        version_strings = self._redis.zrange(versions_key, 0, -1, rev=True)
        versions = []
        for v in version_strings:
            wv = self.get_version(workflow_id, v)
            if wv:
                versions.append(wv)
        return versions

    # ── Rollback ────────────────────────────────────────────────────────────

    def rollback(
        self,
        workflow_id: str,
        to_version: str,
        rolled_back_by: str = "system",
    ) -> WorkflowVersion:
        """
        Roll back a workflow to a previous version.
        Creates a new version entry (rollback is a forward operation).
        """
        target = self.get_version(workflow_id, to_version)
        if not target:
            raise ValueError(f"Version '{to_version}' not found for workflow '{workflow_id}'")

        return self.save_version(
            workflow_id=workflow_id,
            definition=target.snapshot,
            created_by=rolled_back_by,
            change_summary=f"Rollback to version {to_version}",
            bump="patch",
        )

    # ── Diff ────────────────────────────────────────────────────────────────

    def diff(self, workflow_id: str, from_version: str, to_version: str) -> VersionDiff:
        """Compare two versions of a workflow."""
        v_from = self.get_version(workflow_id, from_version)
        v_to = self.get_version(workflow_id, to_version)

        if not v_from:
            raise ValueError(f"Version '{from_version}' not found")
        if not v_to:
            raise ValueError(f"Version '{to_version}' not found")

        return self._compute_diff(v_from.snapshot, v_to.snapshot, from_version, to_version)

    # ── Private ─────────────────────────────────────────────────────────────

    def _bump_version(self, current: str, bump: str) -> str:
        major, minor, patch = (int(x) for x in current.split("."))
        if bump == "major":
            return f"{major + 1}.0.0"
        elif bump == "minor":
            return f"{major}.{minor + 1}.0"
        else:
            return f"{major}.{minor}.{patch + 1}"

    def _compute_diff(
        self,
        old_def: dict[str, Any],
        new_def: dict[str, Any],
        from_ver: str = "old",
        to_ver: str = "new",
    ) -> VersionDiff:
        old_steps = {s["name"]: s for s in old_def.get("steps", [])}
        new_steps = {s["name"]: s for s in new_def.get("steps", [])}

        added = [n for n in new_steps if n not in old_steps]
        removed = [n for n in old_steps if n not in new_steps]
        modified = [
            n
            for n in new_steps
            if n in old_steps and new_steps[n].get("agent_id") != old_steps[n].get("agent_id")
        ]

        breaking = len(removed) > 0 or len(modified) > 0

        return VersionDiff(
            from_version=from_ver,
            to_version=to_ver,
            steps_added=added,
            steps_removed=removed,
            steps_modified=modified,
            breaking=breaking,
        )

    def _version_to_dict(self, v: WorkflowVersion) -> dict[str, Any]:
        return {
            "workflow_id": v.workflow_id,
            "version": v.version,
            "created_at": v.created_at,
            "created_by": v.created_by,
            "change_summary": v.change_summary,
            "breaking_change": v.breaking_change,
            "snapshot": v.snapshot,
        }

    def _dict_to_version(self, d: dict[str, Any]) -> WorkflowVersion:
        return WorkflowVersion(
            workflow_id=d["workflow_id"],
            version=d["version"],
            created_at=d["created_at"],
            created_by=d["created_by"],
            change_summary=d["change_summary"],
            breaking_change=d["breaking_change"],
            snapshot=d["snapshot"],
        )
