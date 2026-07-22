"""Test Run Config status machine (including draft→completed multi-hop)."""

from __future__ import annotations

from datetime import datetime

import pytest

from app.models.test_run_config import TestRunStatus
from app.services.test_run_set_status import (
    _main_path_hops,
    apply_config_status_transition_sync,
)


class _FakeConfig:
    def __init__(self, status: TestRunStatus | str = TestRunStatus.DRAFT):
        self.status = status
        self.start_date = None
        self.end_date = None
        self.updated_at = None


def test_draft_to_completed_hops_via_active():
    cfg = _FakeConfig(TestRunStatus.DRAFT)
    apply_config_status_transition_sync(cfg, TestRunStatus.COMPLETED)
    assert cfg.status == TestRunStatus.COMPLETED
    assert isinstance(cfg.start_date, datetime)
    assert isinstance(cfg.end_date, datetime)


def test_draft_to_completed_coerces_string_status():
    """ORM edge: status may surface as plain str; path must still multi-hop."""
    cfg = _FakeConfig("draft")
    apply_config_status_transition_sync(cfg, "completed")
    assert cfg.status == TestRunStatus.COMPLETED
    assert cfg.start_date is not None
    assert cfg.end_date is not None


def test_main_path_hops_only_expands_forward_skips():
    assert _main_path_hops(TestRunStatus.DRAFT, TestRunStatus.COMPLETED) == [
        TestRunStatus.ACTIVE,
        TestRunStatus.COMPLETED,
    ]
    assert _main_path_hops(TestRunStatus.DRAFT, TestRunStatus.ACTIVE) is None
    assert _main_path_hops(TestRunStatus.ACTIVE, TestRunStatus.COMPLETED) is None
    assert _main_path_hops(TestRunStatus.COMPLETED, TestRunStatus.DRAFT) is None
    assert _main_path_hops(TestRunStatus.DRAFT, TestRunStatus.ARCHIVED) is None


def test_draft_to_active_still_works():
    cfg = _FakeConfig(TestRunStatus.DRAFT)
    apply_config_status_transition_sync(cfg, TestRunStatus.ACTIVE)
    assert cfg.status == TestRunStatus.ACTIVE
    assert cfg.end_date is None
    assert cfg.start_date is not None


def test_active_to_completed():
    cfg = _FakeConfig(TestRunStatus.ACTIVE)
    cfg.start_date = datetime.utcnow()
    apply_config_status_transition_sync(cfg, TestRunStatus.COMPLETED)
    assert cfg.status == TestRunStatus.COMPLETED
    assert cfg.end_date is not None


def test_same_status_is_noop():
    cfg = _FakeConfig(TestRunStatus.ACTIVE)
    cfg.start_date = datetime(2020, 1, 1)
    apply_config_status_transition_sync(cfg, TestRunStatus.ACTIVE)
    assert cfg.status == TestRunStatus.ACTIVE
    assert cfg.start_date == datetime(2020, 1, 1)


def test_illegal_completed_to_draft_still_blocked():
    cfg = _FakeConfig(TestRunStatus.COMPLETED)
    with pytest.raises(ValueError, match="不允許"):
        apply_config_status_transition_sync(cfg, TestRunStatus.DRAFT)


def test_illegal_completed_to_active_still_blocked():
    """Reopen is only archived→active/draft; completed cannot jump back to active."""
    cfg = _FakeConfig(TestRunStatus.COMPLETED)
    with pytest.raises(ValueError, match="不允許"):
        apply_config_status_transition_sync(cfg, TestRunStatus.ACTIVE)


def test_draft_to_archived_is_direct_not_via_completed():
    cfg = _FakeConfig(TestRunStatus.DRAFT)
    apply_config_status_transition_sync(cfg, TestRunStatus.ARCHIVED)
    assert cfg.status == TestRunStatus.ARCHIVED
