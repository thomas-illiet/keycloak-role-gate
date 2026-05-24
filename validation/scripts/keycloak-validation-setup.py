#!/usr/bin/env python3
"""Prepare the local validation realm through Keycloak Admin REST.

The validation environment is allowed to create and destroy the test realm. It
uses the same Admin REST client as the reusable RoleGate script so CI exercises
the production setup path without depending on `kcadm.sh` inside the Keycloak
container.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

from scripts.rolegate_setup import (
    AdminConfig,
    KeycloakAdminClient,
    KeycloakApiError,
    RoleGateConfig,
    create_or_reuse_role_gate_flow,
)


@dataclass(frozen=True)
class ValidationConfig:
    """Environment-driven settings for the local validation realm."""

    server_url: str
    realm: str
    target_client_id: str
    required_role: str
    oidc_client_secret: str
    app_base_url: str
    redirect_uri: str
    flow_alias: str
    admin_username: str
    admin_password: str
    user_password: str
    reset_realm: bool

    @classmethod
    def from_env(cls) -> ValidationConfig:
        target_client_id = os.getenv("ROLEGATE_TARGET_CLIENT_ID", "python-app")
        app_base_url = os.getenv("ROLEGATE_VALIDATION_APP_URL", "http://localhost:8000")
        return cls(
            server_url=os.getenv("ROLEGATE_KEYCLOAK_URL", "http://localhost:8080"),
            realm=os.getenv("ROLEGATE_REALM", "role-gate-validation"),
            target_client_id=target_client_id,
            required_role=os.getenv("ROLEGATE_REQUIRED_ROLE", "app-access"),
            oidc_client_secret=os.getenv("ROLEGATE_VALIDATION_CLIENT_SECRET", "python-app-secret"),
            app_base_url=app_base_url,
            redirect_uri=os.getenv(
                "ROLEGATE_VALIDATION_REDIRECT_URI",
                f"{app_base_url}/auth/callback",
            ),
            flow_alias=os.getenv("ROLEGATE_FLOW_ALIAS", f"{target_client_id}-role-gated-browser"),
            admin_username=os.getenv("ROLEGATE_ADMIN_USERNAME", "admin"),
            admin_password=os.getenv("ROLEGATE_ADMIN_PASSWORD", "admin"),
            user_password=os.getenv("ROLEGATE_VALIDATION_USER_PASSWORD", "password"),
            reset_realm=_env_bool("ROLEGATE_VALIDATION_RESET_REALM", True),
        )


def main() -> int:
    """Create the realm, client, users, role mapping, and activated RoleGate flow."""
    config = ValidationConfig.from_env()
    admin = KeycloakAdminClient(
        AdminConfig(
            server_url=config.server_url,
            username=config.admin_username,
            password=config.admin_password,
        )
    )

    print("Waiting for Keycloak admin API...")
    _wait_for_keycloak(admin)

    if admin.realm_exists(config.realm):
        if config.reset_realm:
            print(f"Deleting existing validation realm {config.realm}...")
            admin.delete_realm(config.realm)
        else:
            print(
                f"Realm {config.realm} already exists and "
                "ROLEGATE_VALIDATION_RESET_REALM=false; reusing it."
            )

    if not admin.realm_exists(config.realm):
        print(f"Creating realm {config.realm}...")
        admin.create_realm(
            {
                "realm": config.realm,
                "enabled": True,
                "registrationAllowed": False,
                "sslRequired": "none",
            }
        )

    print(f"Creating OIDC client {config.target_client_id}...")
    client_uuid = _ensure_client(admin, config)

    print(f"Creating required client role {config.required_role}...")
    role = _ensure_client_role(admin, config, client_uuid)

    print("Creating test users...")
    allowed_user_id = _ensure_user(admin, config, "allowed", "Allowed", "User")
    _ensure_user(admin, config, "blocked", "Blocked", "User")

    print(f"Assigning {config.target_client_id}.{config.required_role} to allowed...")
    _ensure_role_mapping(admin, config, allowed_user_id, client_uuid, role)

    print("Creating and activating role-gated browser flow...")
    result = create_or_reuse_role_gate_flow(
        admin,
        RoleGateConfig(
            realm=config.realm,
            target_client_id=config.target_client_id,
            required_role=config.required_role,
            flow_alias=config.flow_alias,
            recreate=True,
            activate=True,
        ),
    )

    print(f"Activated flow {result.flow_alias} on client {config.target_client_id}.")
    print("Validation setup complete.")
    return 0


def _ensure_client(admin: KeycloakAdminClient, config: ValidationConfig) -> str:
    existing = admin.find_client(config.realm, config.target_client_id)
    if existing is None:
        admin.create_client(
            config.realm,
            {
                "clientId": config.target_client_id,
                "enabled": True,
                "protocol": "openid-connect",
                "publicClient": False,
                "clientAuthenticatorType": "client-secret",
                "secret": config.oidc_client_secret,
                "standardFlowEnabled": True,
                "directAccessGrantsEnabled": False,
                "serviceAccountsEnabled": False,
                "redirectUris": [config.redirect_uri],
                "webOrigins": [config.app_base_url],
                "attributes": {
                    "post.logout.redirect.uris": config.app_base_url,
                },
            },
        )
        existing = admin.find_client(config.realm, config.target_client_id)

    if existing is None or not isinstance(existing.get("id"), str):
        raise KeycloakApiError(f"Client was not found after creation: {config.target_client_id}")
    return existing["id"]


def _ensure_client_role(
    admin: KeycloakAdminClient, config: ValidationConfig, client_uuid: str
) -> dict[str, object]:
    try:
        return admin.get_client_role(config.realm, client_uuid, config.required_role)
    except KeycloakApiError as exc:
        if exc.status != 404:
            raise

    admin.create_client_role(
        config.realm,
        client_uuid,
        {
            "name": config.required_role,
            "description": "Required to access the Python validation target",
        },
    )
    return admin.get_client_role(config.realm, client_uuid, config.required_role)


def _ensure_user(
    admin: KeycloakAdminClient,
    config: ValidationConfig,
    username: str,
    first_name: str,
    last_name: str,
) -> str:
    user = admin.find_user(config.realm, username)
    if user is None:
        admin.create_user(
            config.realm,
            {
                "username": username,
                "email": f"{username}@example.test",
                "enabled": True,
                "emailVerified": True,
                "firstName": first_name,
                "lastName": last_name,
            },
        )
        user = admin.find_user(config.realm, username)

    if user is None or not isinstance(user.get("id"), str):
        raise KeycloakApiError(f"User was not found after creation: {username}")

    user_id = user["id"]
    admin.reset_user_password(config.realm, user_id, config.user_password)
    return user_id


def _ensure_role_mapping(
    admin: KeycloakAdminClient,
    config: ValidationConfig,
    user_id: str,
    client_uuid: str,
    role: dict[str, object],
) -> None:
    mappings = admin.get_client_role_mappings(config.realm, user_id, client_uuid)
    role_name = role.get("name")
    if any(mapping.get("name") == role_name for mapping in mappings):
        return
    admin.add_client_role_mapping(config.realm, user_id, client_uuid, [role])


def _wait_for_keycloak(admin: KeycloakAdminClient) -> None:
    for _ in range(60):
        try:
            admin.authenticate()
            return
        except KeycloakApiError:
            time.sleep(2)
    admin.authenticate()


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    raise SystemExit(main())
