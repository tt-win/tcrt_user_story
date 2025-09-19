from pathlib import Path


def test_requirements_has_no_duplicate_entries():
    project_root = Path(__file__).resolve().parents[2]
    requirements_path = project_root / "requirements.txt"
    assert requirements_path.exists(), "requirements.txt 應存在於專案根目錄"

    seen = set()
    duplicates = []

    for raw_line in requirements_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line in seen:
            duplicates.append(line)
        else:
            seen.add(line)

    assert not duplicates, f"發現重複依賴條目: {', '.join(duplicates)}"
