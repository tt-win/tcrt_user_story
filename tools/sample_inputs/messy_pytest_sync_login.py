"""Login regression — Playwright sync + pytest (WIP).

Has a class-based layout because the previous version needed shared
setup. Lots of duplication, no POM yet, and the browser fixture is
declared inline (should be in conftest.py).
"""
import time

import pytest
from playwright.sync_api import Page, expect


URL = "https://staging.acme.test"


@pytest.fixture(scope="function")
def browser_page():
    """Throwaway per-test browser; should be in conftest.py."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()
        yield page
        browser.close()


class TestLogin:
    def test_user_can_log_in_with_email(self, browser_page: Page):
        page = browser_page
        page.goto(URL + "/login")
        page.locator('input[name="email"]').fill("user@example.com")
        page.locator('input[name="password"]').fill("Passw0rd!")
        page.locator('button:has-text("Sign in")').click()
        # give the page a moment
        time.sleep(2)
        expect(page).to_have_url("**/dashboard")
        expect(page.get_by_text("Welcome back")).to_be_visible()

    def test_user_can_log_in_with_2fa(self, browser_page: Page):
        page = browser_page
        page.goto(URL + "/login")
        page.locator('input[name="email"]').fill("twofa@example.com")
        page.locator('input[name="password"]').fill("Passw0rd!")
        page.locator('button:has-text("Sign in")').click()
        # 2FA step appears
        expect(page.get_by_text("Enter the 6-digit code")).to_be_visible(timeout=5000)
        page.locator('input[name="otp"]').fill("123456")
        page.locator('button:has-text("Verify")').click()
        time.sleep(1)
        expect(page).to_have_url("**/dashboard")

    def test_login_rejects_wrong_password(self, browser_page: Page):
        page = browser_page
        page.goto(URL + "/login")
        page.locator('input[name="email"]').fill("user@example.com")
        page.locator('input[name="password"]').fill("definitely-wrong")
        page.locator('button:has-text("Sign in")').click()
        time.sleep(1)
        err = page.locator('[role="alert"]')
        expect(err).to_be_visible()
        expect(err).to_contain_text("Invalid")

    def test_login_locks_after_five_wrong_attempts(self, browser_page: Page):
        page = browser_page
        for i in range(5):
            page.goto(URL + "/login")
            page.locator('input[name="email"]').fill("lockme@example.com")
            page.locator('input[name="password"]').fill(f"wrong-{i}")
            page.locator('button:has-text("Sign in")').click()
            time.sleep(0.5)
        err_text = page.locator('[role="alert"]').text_content()
        assert err_text and "locked" in err_text.lower(), f"expected lock, got: {err_text!r}"
