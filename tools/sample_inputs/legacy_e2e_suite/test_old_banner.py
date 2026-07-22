"""Old notification-banner spec — Selenium, the one in 2018 style.

Uses By.XPATH and time.sleep throughout. We want pomify to lift the
selectors into a `NotificationBanner` page object and replace the
sleeps with WebDriverWait.
"""
import time

import pytest
from selenium import webdriver
from selenium.webdriver.common.by import By


@pytest.fixture
def driver():
    opts = webdriver.ChromeOptions()
    opts.add_argument("--headless=new")
    d = webdriver.Chrome(options=opts)
    yield d
    d.quit()


def test_dismissible_banner_can_be_closed(driver):
    driver.get("https://acme.test/dashboard")
    time.sleep(1)
    banner = driver.find_element(By.CSS_SELECTOR, '[data-testid="info-banner"]')
    assert banner.is_displayed()
    driver.find_element(By.CSS_SELECTOR, '[data-testid="info-banner"] button.close').click()
    time.sleep(0.5)
    # banner should be gone
    found = driver.find_elements(By.CSS_SELECTOR, '[data-testid="info-banner"]')
    assert len(found) == 0, f"expected banner removed, found {len(found)} still present"


def test_error_banner_shows_validation_message(driver):
    driver.get("https://acme.test/dashboard")
    time.sleep(1)
    driver.find_element(By.CSS_SELECTOR, 'input[name="amount"]').send_keys("not-a-number")
    driver.find_element(By.CSS_SELECTOR, 'button:has-text("Submit")').click() if False else \
        driver.find_element(By.XPATH, '//button[contains(., "Submit")]').click()
    time.sleep(1)
    err = driver.find_element(By.CSS_SELECTOR, '[data-testid="error-banner"]')
    assert err.is_displayed()
    assert "must be a number" in err.text.lower()
