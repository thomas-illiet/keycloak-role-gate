from __future__ import annotations

import os
import re

from playwright.sync_api import Page, expect

VALIDATION_APP_URL = os.getenv("ROLEGATE_VALIDATION_APP_URL", "http://localhost:8000")
VALIDATION_REALM = os.getenv("ROLEGATE_REALM", "role-gate-validation")
VALIDATION_PASSWORD = os.getenv("ROLEGATE_VALIDATION_USER_PASSWORD", "password")
EXPECTED_DENY_MESSAGE = os.getenv(
    "ROLEGATE_DENY_MESSAGE",
    "Access denied: missing required role",
)


def test_allowed_user_can_access_app(page: Page) -> None:
    page.goto(VALIDATION_APP_URL)

    _login(page, "allowed", VALIDATION_PASSWORD)

    expect(page.get_by_test_id("authenticated-app")).to_be_visible(timeout=20_000)
    expect(page.get_by_test_id("username")).to_have_text("allowed")


def test_blocked_user_is_denied_by_keycloak(page: Page) -> None:
    page.goto(VALIDATION_APP_URL)

    _login(page, "blocked", VALIDATION_PASSWORD)

    expect(page).to_have_url(
        re.compile(rf".*/realms/{re.escape(VALIDATION_REALM)}/.*"),
        timeout=20_000,
    )
    expect(page.get_by_text(EXPECTED_DENY_MESSAGE, exact=False)).to_be_visible(timeout=20_000)
    expect(page.get_by_test_id("authenticated-app")).not_to_be_visible()


def _login(page: Page, username: str, password: str) -> None:
    expect(page.locator("#username")).to_be_visible(timeout=20_000)
    page.locator("#username").fill(username)
    page.locator("#password").fill(password)
    page.locator("#kc-login").click()
