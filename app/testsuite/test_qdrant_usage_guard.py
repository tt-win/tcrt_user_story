from pathlib import Path


def test_qdrant_client_must_be_used_via_service_layer():
    project_root = Path(__file__).resolve().parents[2]
    app_root = project_root / "app"
    service_file = app_root / "services" / "qdrant_client.py"
    assert service_file.exists(), "Qdrant service 檔案應存在"

    offenders = []
    direct_markers = [
        "from qdrant_client import",
        "import qdrant_client",
        "QdrantClient(",
        "AsyncQdrantClient(",
    ]

    for py_file in app_root.rglob("*.py"):
        if py_file == service_file:
            continue
        if "testsuite" in py_file.parts:
            continue

        content = py_file.read_text(encoding="utf-8")
        if any(marker in content for marker in direct_markers):
            offenders.append(str(py_file.relative_to(project_root)))

    assert not offenders, (
        "偵測到直接使用 qdrant client 的檔案，"
        "請改為透過 app/services/qdrant_client.py："
        + ", ".join(offenders)
    )
