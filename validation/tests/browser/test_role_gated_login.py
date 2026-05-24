from __future__ import annotations

import os
import re

from playwright.sync_api import Page, expect

APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:8000")
REALM = os.getenv("REALM", "role-gate-validation")
PASSWORD = os.getenv("VALIDATION_USER_PASSWORD", "password")
DENY_MESSAGE = os.getenv("DENY_MESSAGE", "Access denied: missing required role")


def test_allowed_user_can_access_app(page: Page) -> None:
    page.goto(APP_BASE_URL)

    _login(page, "allowed", PASSWORD)

    expect(page.get_by_test_id("authenticated-app")).to_be_visible(timeout=20_000)
    expect(page.get_by_test_id("username")).to_have_text("allowed")


def test_blocked_user_is_denied_by_keycloak(page: Page) -> None:
    page.goto(APP_BASE_URL)

    _login(page, "blocked", PASSWORD)

    expect(page).to_have_url(re.compile(rf".*/realms/{re.escape(REALM)}/.*"), timeout=20_000)
    expect(page.get_by_text(DENY_MESSAGE, exact=False)).to_be_visible(timeout=20_000)
    expect(page.get_by_test_id("authenticated-app")).not_to_be_visible()


def _login(page: Page, username: str, password: str) -> None:
    expect(page.locator("#username")).to_be_visible(timeout=20_000)
    page.locator("#username").fill(username)
    page.locator("#password").fill(password)
    page.locator("#kc-login").click()
