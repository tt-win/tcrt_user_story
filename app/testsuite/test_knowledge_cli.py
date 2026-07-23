"""Unit tests for app.services.knowledge.__main__ CLI argument parsing.

Does not exercise the actual backfill loop (that needs a real DB and Qdrant,
covered by integration tests). Focus: CLI args, disabled-KG guard, error path.
"""

from __future__ import annotations

import pytest

from app.services.knowledge.__main__ import main


def test_main_requires_command() -> None:
    """Missing subcommand should exit with non-zero."""
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code != 0


def test_backfill_when_disabled(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    """If KG is disabled, exit with code 1 and print helpful message."""
    monkeypatch.setattr(
        "app.services.knowledge.__main__.is_knowledge_graph_enabled", lambda: False
    )
    rc = main(["backfill", "--entity", "test_cases"])
    assert rc == 1
    out = capsys.readouterr().err
    assert "KNOWLEDGE_GRAPH_ENABLED=true" in out
