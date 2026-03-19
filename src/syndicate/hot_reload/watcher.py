"""
SYNDICATE AI — Agent Hot Reload
File: src/syndicate/hot_reload/watcher.py

Watches the /agents directory for YAML changes and reloads
agent contracts without restarting the server.

This is a key developer experience feature — edit an agent YAML
and the change takes effect in under 1 second, no restart needed.
LangGraph and CrewAI require full restart on any agent code change.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


class AgentHotReloader:
    """
    File system watcher that reloads agent YAML contracts on change.

    Uses a polling approach (compatible with all OS/Docker environments).
    For production, set poll_interval=5 or higher to reduce I/O.

    Thread-safe: uses a lock on registry updates.
    """

    def __init__(
        self,
        agents_dir: Path,
        registry: Any,
        poll_interval: float = 1.0,
    ) -> None:
        self._agents_dir = agents_dir
        self._registry = registry
        self._poll_interval = poll_interval
        self._file_mtimes: dict[str, float] = {}
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        """Start the background watcher thread."""
        self._snapshot_mtimes()
        self._thread = threading.Thread(
            target=self._watch_loop,
            daemon=True,
            name="syndicate-hot-reload",
        )
        self._thread.start()
        logger.info(
            "Agent hot-reload started (watching %s, interval=%.1fs)",
            self._agents_dir,
            self._poll_interval,
        )

    def stop(self) -> None:
        """Stop the watcher thread."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5.0)
        logger.info("Agent hot-reload stopped")

    def _watch_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._check_for_changes()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Hot-reload error: %s", exc)
            time.sleep(self._poll_interval)

    def _snapshot_mtimes(self) -> None:
        for path in self._agents_dir.rglob("*.yaml"):
            self._file_mtimes[str(path)] = path.stat().st_mtime

    def _check_for_changes(self) -> None:
        current_files = {str(p): p.stat().st_mtime for p in self._agents_dir.rglob("*.yaml")}

        # Detect new or modified files
        for filepath, mtime in current_files.items():
            if filepath not in self._file_mtimes or self._file_mtimes[filepath] != mtime:
                self._reload_file(
                    Path(filepath), reason="modified" if filepath in self._file_mtimes else "added"
                )

        # Detect deleted files
        for filepath in list(self._file_mtimes.keys()):
            if filepath not in current_files:
                self._remove_agent(Path(filepath))
                del self._file_mtimes[filepath]

        self._file_mtimes = current_files

    def _reload_file(self, path: Path, reason: str) -> None:
        try:
            raw = yaml.safe_load(path.read_text())
            agent_id = raw.get("id", "")
            if not agent_id:
                logger.warning("Hot-reload skipped %s: missing 'id' field", path.name)
                return

            from syndicate.core.models import AgentDefinition

            agent = AgentDefinition.model_validate(raw)

            with self._lock:
                self._registry._agents[agent.id] = agent

            logger.info(
                "🔄 Hot-reloaded agent [%s] from %s (%s)",
                agent.id,
                path.name,
                reason,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Hot-reload FAILED for %s: %s — keeping previous version",
                path.name,
                exc,
            )

    def _remove_agent(self, path: Path) -> None:
        # Try to infer agent ID from path
        with self._lock:
            removed = [
                agent_id
                for agent_id, agent in list(self._registry._agents.items())
                if path.stem in agent_id
            ]
            for agent_id in removed:
                del self._registry._agents[agent_id]
                logger.info("🗑️  Removed agent [%s] (file deleted)", agent_id)
