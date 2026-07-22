"""Quick smoke test for the new auth flow — WIP, do not promote.

Tossed together the morning of the release to verify signup / login /
logout work end-to-end on staging. Lots of duplication, magic strings,
and a couple of `wait_for_timeout` calls I meant to replace. Not
pytest-shaped, runs as a plain script. Will refactor when there's time.
— j.doe, 2025-03-14
"""
import asyncio
import time

from playwright.async_api import async_playwright

BASE = "https://staging.acme.test"


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        # 1) brand-new user signs up and lands on the dashboard
        await page.goto(BASE + "/signup")
        await page.locator('input[name="email"]').fill(
            f"alice+{int(time.time())}@example.com"
        )
        await page.locator("#password").fill("Passw0rd!")
        await page.locator('input[name="confirmPassword"]').fill("Passw0rd!")
        await page.locator('button:has-text("Create account")').click()
        # TODO(pomify): replace this with a real wait
        await page.wait_for_timeout(2000)
        assert "/dashboard" in page.url, (
            "expected redirect to /dashboard, got " + page.url
        )
        assert "Welcome" in await page.content(), "missing welcome banner"

        # 2) log out, then log back in with the same account
        await page.locator('button[data-testid="user-menu"]').click()
        await page.locator('a:has-text("Sign out")').click()
        await page.wait_for_timeout(500)

        await page.goto(BASE + "/login")
        await page.locator('input[name="email"]').fill("alice@example.com")
        await page.locator("#password").fill("Passw0rd!")
        await page.locator('button:has-text("Sign in")').click()
        await page.wait_for_timeout(2000)
        assert "/dashboard" in page.url, "login should land on /dashboard"

        # 3) log out, try wrong password, expect the error toast
        await page.locator('button[data-testid="user-menu"]').click()
        await page.locator('a:has-text("Sign out")').click()
        await page.wait_for_timeout(500)

        await page.goto(BASE + "/login")
        await page.locator('input[name="email"]').fill("alice@example.com")
        await page.locator("#password").fill("definitely-wrong")
        await page.locator('button:has-text("Sign in")').click()
        await page.wait_for_timeout(1000)
        err = await page.locator('[role="alert"]').text_content()
        assert err and "Invalid" in err, (
            "expected 'Invalid' in error toast, got: " + str(err)
        )

        # 4) and finally the locked-out case (5 wrong attempts)
        for i in range(5):
            await page.goto(BASE + "/login")
            await page.locator('input[name="email"]').fill("alice@example.com")
            await page.locator("#password").fill(f"wrong-{i}")
            await page.locator('button:has-text("Sign in")').click()
            await page.wait_for_timeout(800)
        locked = await page.locator('[role="alert"]').text_content()
        assert locked and "locked" in locked.lower(), (
            "expected account to be locked, got: " + str(locked)
        )

        await browser.close()
        print("OK - all four flows passed")


if __name__ == "__main__":
    asyncio.run(main())
