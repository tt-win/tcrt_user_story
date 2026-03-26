from pathlib import Path
import sys
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import PROJECT_ROOT as CONFIG_PROJECT_ROOT, Settings
from app.services.attachment_storage import (
    build_attachment_metadata,
    build_attachment_url,
    get_attachment_access_url,
    get_attachments_root_dir,
    normalize_attachment_metadata,
    resolve_attachment_metadata_path,
)
from app.services.html_report_service import HTMLReportService


def _write_config(path: Path, extra_yaml: str = "") -> None:
    path.write_text(
        "app:\n  port: 9999\nopenrouter:\n  api_key: ''\n" + extra_yaml,
        encoding="utf-8",
    )


def test_reports_root_defaults_to_project_generated_report(tmp_path, monkeypatch):
    monkeypatch.delenv("REPORTS_ROOT_DIR", raising=False)

    config_path = tmp_path / "config.yaml"
    _write_config(config_path)

    loaded = Settings.from_env_and_file(str(config_path))

    assert loaded.reports.root_dir == ""
    assert loaded.reports.resolve_root_dir(CONFIG_PROJECT_ROOT) == CONFIG_PROJECT_ROOT / "generated_report"


def test_reports_root_can_be_loaded_from_config(tmp_path, monkeypatch):
    monkeypatch.delenv("REPORTS_ROOT_DIR", raising=False)

    configured_root = tmp_path / "custom-reports"
    config_path = tmp_path / "config.yaml"
    _write_config(
        config_path,
        f"reports:\n  root_dir: '{configured_root}'\n",
    )

    loaded = Settings.from_env_and_file(str(config_path))

    assert loaded.reports.resolve_root_dir(CONFIG_PROJECT_ROOT) == configured_root


def test_reports_root_env_overrides_config(tmp_path, monkeypatch):
    env_root = tmp_path / "env-reports"
    monkeypatch.setenv("REPORTS_ROOT_DIR", str(env_root))

    config_path = tmp_path / "config.yaml"
    _write_config(
        config_path,
        f"reports:\n  root_dir: '{tmp_path / 'config-reports'}'\n",
    )

    loaded = Settings.from_env_and_file(str(config_path))

    assert loaded.reports.root_dir == str(env_root)
    assert loaded.reports.resolve_root_dir(CONFIG_PROJECT_ROOT) == env_root


def test_attachments_root_env_overrides_config(tmp_path, monkeypatch):
    env_root = tmp_path / "env-attachments"
    monkeypatch.setenv("ATTACHMENTS_ROOT_DIR", str(env_root))

    config_path = tmp_path / "config.yaml"
    _write_config(
        config_path,
        f"attachments:\n  root_dir: '{tmp_path / 'config-attachments'}'\n",
    )

    loaded = Settings.from_env_and_file(str(config_path))

    assert loaded.attachments.root_dir == str(env_root)
    assert loaded.attachments.resolve_root_dir(CONFIG_PROJECT_ROOT) == env_root


def test_attachment_metadata_normalizes_to_relative_path(tmp_path, monkeypatch):
    root_dir = tmp_path / "attachments"
    stored_path = root_dir / "test-cases" / "1" / "TC-1" / "proof.png"
    stored_path.parent.mkdir(parents=True, exist_ok=True)
    stored_path.write_bytes(b"ok")

    metadata = build_attachment_metadata(
        root_dir=root_dir,
        stored_path=stored_path,
        original_name="proof.png",
        stored_name="proof.png",
        size=2,
        content_type="image/png",
        uploaded_at="2026-03-26T00:00:00",
    )

    assert metadata["relative_path"] == "test-cases/1/TC-1/proof.png"
    assert "absolute_path" not in metadata
    assert build_attachment_url(metadata["relative_path"]) == "/attachments/test-cases/1/TC-1/proof.png"


def test_attachment_metadata_legacy_absolute_path_fallback(tmp_path, monkeypatch):
    root_dir = tmp_path / "attachments"
    monkeypatch.setenv("ATTACHMENTS_ROOT_DIR", str(root_dir))
    stored_path = root_dir / "test-runs" / "1" / "2" / "3" / "proof.png"
    stored_path.parent.mkdir(parents=True, exist_ok=True)
    stored_path.write_bytes(b"ok")

    metadata = {
        "name": "proof.png",
        "stored_name": "proof.png",
        "absolute_path": str(stored_path),
    }

    normalized = normalize_attachment_metadata(metadata, project_root=CONFIG_PROJECT_ROOT)
    resolved = resolve_attachment_metadata_path(normalized, project_root=CONFIG_PROJECT_ROOT)

    assert normalized["relative_path"] == "test-runs/1/2/3/proof.png"
    assert "absolute_path" not in normalized
    assert resolved == stored_path.resolve()


def test_attachment_metadata_rejects_path_escape(tmp_path, monkeypatch):
    root_dir = tmp_path / "attachments"
    monkeypatch.setenv("ATTACHMENTS_ROOT_DIR", str(root_dir))

    with pytest.raises(ValueError):
        normalize_attachment_metadata({"relative_path": "../etc/passwd"}, project_root=CONFIG_PROJECT_ROOT)


def test_attachment_metadata_remote_entry_keeps_url_without_path():
    metadata = {
        "file_token": "abc123",
        "name": "remote.png",
        "url": "https://example.com/files/remote.png",
        "tmp_url": "https://example.com/tmp/remote.png",
    }

    normalized = normalize_attachment_metadata(metadata, allow_missing_path=True)

    assert normalized == metadata
    assert get_attachment_access_url(normalized) == "https://example.com/files/remote.png"


def test_html_report_service_uses_report_root_and_creates_tmp_dir(tmp_path):
    report_root = tmp_path / "html-reports"

    service = HTMLReportService(db_session=None, report_root=report_root)

    assert service.report_root == report_root
    assert service.tmp_root == report_root / ".tmp"
    assert service.tmp_root.exists()
