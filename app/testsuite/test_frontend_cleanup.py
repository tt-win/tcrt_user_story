from pathlib import Path
import re


def test_remove_unused_clear_tcg_cache():
    html = Path('app/templates/test_case_management.html').read_text(encoding='utf-8')
    pattern = re.compile(r'function\s+clearTCGCache\s*\(')
    assert not pattern.search(html), 'clearTCGCache should be removed if unused'
