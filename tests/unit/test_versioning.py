"""Unit tests for workflow versioning manager."""
from __future__ import annotations
from unittest.mock import MagicMock
import pytest
from syndicate.versioning.manager import WorkflowVersionManager


def make_redis_mock() -> MagicMock:
    store: dict = {}
    sorted_sets: dict = {}
    mock = MagicMock()

    def setval(key, value): store[key] = value
    def getval(key): return store.get(key)
    def zadd(key, mapping):
        if key not in sorted_sets:
            sorted_sets[key] = {}
        sorted_sets[key].update(mapping)
    def zrange(key, start, end, rev=False):
        if key not in sorted_sets:
            return []
        items = sorted(sorted_sets[key].items(), key=lambda x: x[1], reverse=rev)
        if end == -1:
            return [k for k, _ in items[start:]]
        return [k for k, _ in items[start:end+1]]

    mock.set.side_effect = setval
    mock.get.side_effect = getval
    mock.zadd.side_effect = zadd
    mock.zrange.side_effect = zrange
    return mock


WF_DEF = {
    "id": "test-wf",
    "name": "Test Workflow",
    "initial_step": "step-1",
    "steps": [{"name": "step-1", "agent_id": "engineering.ui-engineer"}],
}


class TestWorkflowVersionManager:
    def setup_method(self):
        self.manager = WorkflowVersionManager(make_redis_mock())

    def test_first_version_is_1_0_0(self):
        v = self.manager.save_version("test-wf", WF_DEF)
        assert v.version == "1.0.0"

    def test_patch_bump(self):
        self.manager.save_version("test-wf", WF_DEF)
        v2 = self.manager.save_version("test-wf", WF_DEF, bump="patch")
        assert v2.version == "1.0.1"

    def test_minor_bump(self):
        self.manager.save_version("test-wf", WF_DEF)
        v2 = self.manager.save_version("test-wf", WF_DEF, bump="minor")
        assert v2.version == "1.1.0"

    def test_major_bump(self):
        self.manager.save_version("test-wf", WF_DEF)
        v2 = self.manager.save_version("test-wf", WF_DEF, bump="major")
        assert v2.version == "2.0.0"

    def test_list_versions_reverse_chronological(self):
        self.manager.save_version("test-wf", WF_DEF)
        self.manager.save_version("test-wf", WF_DEF, bump="minor")
        versions = self.manager.list_versions("test-wf")
        assert len(versions) == 2
        assert versions[0].version == "1.1.0"  # newest first

    def test_get_latest(self):
        self.manager.save_version("test-wf", WF_DEF)
        self.manager.save_version("test-wf", WF_DEF, bump="minor")
        latest = self.manager.get_latest("test-wf")
        assert latest is not None
        assert latest.version == "1.1.0"

    def test_breaking_change_detected_on_step_removal(self):
        self.manager.save_version("test-wf", WF_DEF)
        wf_v2 = {**WF_DEF, "steps": []}  # removed all steps
        v2 = self.manager.save_version("test-wf", wf_v2, bump="major")
        assert v2.breaking_change is True

    def test_rollback_creates_new_version(self):
        self.manager.save_version("test-wf", WF_DEF)
        self.manager.save_version("test-wf", WF_DEF, bump="minor")
        rolled = self.manager.rollback("test-wf", to_version="1.0.0")
        assert rolled.version == "1.1.1"
        assert "Rollback" in rolled.change_summary

    def test_rollback_nonexistent_version_raises(self):
        self.manager.save_version("test-wf", WF_DEF)
        with pytest.raises(ValueError, match="not found"):
            self.manager.rollback("test-wf", to_version="9.9.9")
