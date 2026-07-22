"""Selenium smoke for the new admin console.

Brought over from a colleague's sandbox. Lots of `time.sleep`, no
WebDriverWait, XPath locators that read like 2018. To be refactored
when the team agrees on a shared `pages/` skeleton.
"""
import time

import pytest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


ADMIN = "https://admin.acme.test"


@pytest.fixture(scope="function")
def driver():
    opts = webdriver.ChromeOptions()
    opts.add_argument("--headless=new")
    drv = webdriver.Chrome(options=opts)
    yield drv
    drv.quit()


def test_admin_can_log_in(driver):
    driver.get(ADMIN + "/login")
    # layout: 2 inputs, 1 button
    driver.find_element(By.XPATH, '//input[@placeholder="Email"]').send_keys("admin@example.com")
    driver.find_element(By.XPATH, '//input[@placeholder="Password"]').send_keys("Adm1nPass!")
    driver.find_element(By.XPATH, '//button[contains(., "Sign in")]').click()
    time.sleep(2)  # <- this should be WebDriverWait
    assert "/dashboard" in driver.current_url
    # the heading should say "Admin"
    h1 = driver.find_element(By.XPATH, '//h1').text
    assert "Admin" in h1, f"expected Admin heading, got: {h1!r}"


def test_admin_can_create_user(driver):
    driver.get(ADMIN + "/login")
    driver.find_element(By.XPATH, '//input[@placeholder="Email"]').send_keys("admin@example.com")
    driver.find_element(By.XPATH, '//input[@placeholder="Password"]').send_keys("Adm1nPass!")
    driver.find_element(By.XPATH, '//button[contains(., "Sign in")]').click()
    time.sleep(1)
    driver.get(ADMIN + "/users")
    driver.find_element(By.XPATH, '//button[contains(., "New user")]').click()
    time.sleep(0.5)
    driver.find_element(By.XPATH, '//input[@name="email"]').send_keys("newbie@example.com")
    driver.find_element(By.XPATH, '//select[@name="role"]').click()
    driver.find_element(By.XPATH, '//option[contains(., "Editor")]').click()
    driver.find_element(By.XPATH, '//button[@type="submit"]').click()
    time.sleep(1)
    # check the new row appeared
    rows = driver.find_elements(By.XPATH, '//tr[td[contains(., "newbie@example.com")]]')
    assert len(rows) == 1, f"expected exactly one matching row, got {len(rows)}"


def test_admin_sees_validation_error_for_duplicate_email(driver):
    driver.get(ADMIN + "/login")
    driver.find_element(By.XPATH, '//input[@placeholder="Email"]').send_keys("admin@example.com")
    driver.find_element(By.XPATH, '//input[@placeholder="Password"]').send_keys("Adm1nPass!")
    driver.find_element(By.XPATH, '//button[contains(., "Sign in")]').click()
    time.sleep(1)
    driver.get(ADMIN + "/users")
    driver.find_element(By.XPATH, '//button[contains(., "New user")]').click()
    time.sleep(0.5)
    # re-use the same email from previous test
    driver.find_element(By.XPATH, '//input[@name="email"]').send_keys("newbie@example.com")
    driver.find_element(By.XPATH, '//select[@name="role"]').click()
    driver.find_element(By.XPATH, '//option[contains(., "Editor")]').click()
    driver.find_element(By.XPATH, '//button[@type="submit"]').click()
    time.sleep(1)
    err = WebDriverWait(driver, 5).until(
        EC.visibility_of_element_located((By.CSS_SELECTOR, '[role="alert"]'))
    )
    msg = err.text
    assert "already exists" in msg.lower(), f"expected duplicate-email error, got: {msg!r}"
