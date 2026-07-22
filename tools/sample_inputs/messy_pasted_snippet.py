"""Forgot-password modal — small ad-hoc verification.

A teammate pasted this in chat asking 'does this look right?'. It
should pomify as a single short test, probably under tests/ui/.
"""
from playwright.sync_api import Page


def smoke(page: Page):
    page.goto("https://acme.test/login")
    page.locator('a:has-text("Forgot password?")').click()
    page.locator('input[name="email"]').fill("qa@example.com")
    page.locator('button:has-text("Send reset link")').click()
    import time
    time.sleep(1)
    page.wait_for_selector("text=Check your inbox")
