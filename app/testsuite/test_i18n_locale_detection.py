from pathlib import Path


def test_i18n_language_detection_handles_safari_chinese_variants():
    script = Path("app/static/js/i18n.js").read_text(encoding="utf-8").lower()

    for marker in ["navigator.languages", "zh-hant", "zh-hans", "zh-tw", "zh-cn"]:
        assert marker in script, (
            f"app/static/js/i18n.js missing Safari locale handling marker: {marker}"
        )
