from pathlib import Path
import re


def test_remove_unused_clear_tcg_cache():
    html = Path('app/templates/test_case_management.html').read_text(encoding='utf-8')
    pattern = re.compile(r'function\s+clearTCGCache\s*\(')
    assert not pattern.search(html), 'clearTCGCache should be removed if unused'


def test_ai_rewrite_entry_hidden_but_capability_assets_retained():
    html = Path('app/templates/test_case_management.html').read_text(encoding='utf-8')

    assert 'id="aiAssistUnifiedBtn"' not in html
    assert 'id="aiAssistModal"' in html
    assert '/static/js/test-case-management/ai-assist.js' in html
