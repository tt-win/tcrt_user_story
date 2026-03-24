from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import PROJECT_ROOT as CONFIG_PROJECT_ROOT, Settings
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


def test_html_report_service_uses_report_root_and_creates_tmp_dir(tmp_path):
    report_root = tmp_path / "html-reports"

    service = HTMLReportService(db_session=None, report_root=report_root)

    assert service.report_root == report_root
    assert service.tmp_root == report_root / ".tmp"
    assert service.tmp_root.exists()
