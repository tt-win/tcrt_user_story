"""Old search spec — Playwright async, pre-POM.

Kept around because the e2e team still references it. Lifted straight
from someone's local sandbox; will be retired once the new search
coverage lands.
"""
import asyncio


async def test_search_returns_results_for_known_keyword():
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        page = await b.new_page()
        await page.goto("https://acme.test/search")
        await page.locator('input[name="q"]').fill("otter")
        await page.locator('button[type="submit"]').click()
        await page.wait_for_timeout(800)
        cards = await page.locator('.result-card').count()
        assert cards > 0, f"expected at least one result, got {cards}"
        await b.close()


if __name__ == "__main__":
    asyncio.run(test_search_returns_results_for_known_keyword())
