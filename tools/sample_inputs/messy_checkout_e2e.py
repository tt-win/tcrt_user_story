"""End-to-end checkout flow — quick smoke, not pretty.

Crosses cart → shipping → payment → confirmation. Wrote it in a hurry
during the promo push, going to clean up next sprint.
— r.tanaka, 2025-04
"""
import asyncio

from playwright.async_api import async_playwright

HOST = "https://shop.example.dev"


async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context()
        page = await ctx.new_page()

        # seed a cart by adding from the listing page
        await page.goto(HOST + "/search?q=stuffed+otter")
        await page.locator('div.product-card').first.locator('button.add-to-cart').click()
        await page.wait_for_timeout(1000)
        assert "added" in (await page.locator('.toast').text_content() or "").lower()

        # cart
        await page.goto(HOST + "/cart")
        await page.locator('button:has-text("Checkout")').click()
        await page.wait_for_url("**/checkout/shipping")
        await page.wait_for_timeout(500)

        # shipping
        await page.locator('input[name="fullName"]').fill("Mei Lin")
        await page.locator('input[name="addr1"]').fill("No. 7, Lane 12, Roosevelt Rd.")
        await page.locator('input[name="city"]').fill("Taipei")
        await page.locator('select[name="country"]').select_option("TW")
        await page.locator('input[name="zip"]').fill("100")
        await page.locator('button:has-text("Continue to payment")').click()
        await page.wait_for_url("**/checkout/payment")
        await page.wait_for_timeout(500)

        # payment
        await page.locator('input[name="cardNumber"]').fill("4111111111111111")
        await page.locator('input[name="cardName"]').fill("MEI LIN")
        await page.locator('input[name="expiry"]').fill("12/30")
        await page.locator('input[name="cvc"]').fill("123")
        await page.locator('button:has-text("Place order")').click()
        await page.wait_for_url("**/checkout/confirmation")
        await page.wait_for_timeout(2000)

        order_id = await page.locator('[data-testid="order-id"]').text_content()
        assert order_id and order_id.startswith("ORD-"), f"bad order id: {order_id!r}"
        # did the success banner show?
        body = await page.content()
        assert "Thank you" in body, "missing thank-you banner"

        # bonus: an unhappy path — declined card
        await page.goto(HOST + "/cart")
        await page.locator('button:has-text("Checkout")').click()
        await page.wait_for_url("**/checkout/shipping")
        await page.locator('input[name="fullName"]').fill("Mei Lin")
        await page.locator('input[name="addr1"]').fill("No. 7")
        await page.locator('input[name="city"]').fill("Taipei")
        await page.locator('select[name="country"]').select_option("TW")
        await page.locator('input[name="zip"]').fill("100")
        await page.locator('button:has-text("Continue to payment")').click()
        await page.wait_for_url("**/checkout/payment")
        await page.locator('input[name="cardNumber"]').fill("4000000000000002")  # decline
        await page.locator('input[name="cardName"]').fill("MEI LIN")
        await page.locator('input[name="expiry"]').fill("12/30")
        await page.locator('input[name="cvc"]').fill("123")
        await page.locator('button:has-text("Place order")').click()
        await page.wait_for_timeout(1500)
        err = await page.locator('[role="alert"]').text_content()
        assert err and "declined" in err.lower(), f"expected decline error, got: {err!r}"

        await browser.close()
        print("checkout OK")


if __name__ == "__main__":
    asyncio.run(run())
