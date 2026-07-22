"""Old profile-edit spec — Playwright sync, but mixed with plain pytest.

This file mixes async and sync Playwright calls (oops). Pomify should
detect Playwright async and convert the sync one too, with a
`TODO(pomify): verify async conversion` comment.
"""
import pytest
from playwright.sync_api import Page


def test_profile_form_shows_current_email(page: Page):
    page.goto("https://acme.test/profile")
    page.locator('input[name="displayName"]').fill("QA Bot")
    page.locator('button:has-text("Save")').click()
    assert page.locator('text=Saved').is_visible()


async def test_profile_form_shows_current_email_async(page):
    """Accidentally async — should be flagged during pomify."""
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        page = await b.new_page()
        await page.goto("https://acme.test/profile")
        await page.locator('input[name="displayName"]').fill("QA Bot")
        await page.locator('button:has-text("Save")').click()
        await page.locator('text=Saved').wait_for()
        await b.close()
