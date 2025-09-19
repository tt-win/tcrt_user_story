from pathlib import Path


def test_deprecated_services_removed():
    project_root = Path(__file__).resolve().parents[2]
    deprecated_files = [
        project_root / "app/services/tcg_cache_manager.py",
    ]
    leftover = [str(path) for path in deprecated_files if path.exists()]
    assert not leftover, f"以下後端檔案應已移除: {', '.join(leftover)}"
