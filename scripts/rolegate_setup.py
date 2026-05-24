#!/usr/bin/env python3
"""Create a client-specific Keycloak Browser Flow using only Admin REST APIs.

RoleGate protects one OIDC client by copying a realm Browser Flow, adding a
conditional subflow, and denying login when the user does not have the required
client role.

This script intentionally does not call `kcadm.sh`, `docker compose exec`, or
any other Keycloak-side binary. It only needs:

- a reachable Keycloak base URL;
- an admin username and password;
- the target realm, client id, and required client role.

By default, the script creates or reuses the flow and prints the activation
details. Pass `--activate` to bind the generated Browser Flow directly to the
target client through a client-level Browser Flow override.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import sys
from dataclasses import asdict, dataclass
from typing import Any
from urllib import error, parse, request

DEFAULT_SERVER_URL = "http://localhost:8080"
DEFAULT_ADMIN_REALM = "master"
DEFAULT_ADMIN_CLIENT_ID = "admin-cli"
DEFAULT_BASE_FLOW = "browser"
DEFAULT_DENY_MESSAGE = "Access denied: missing required role"
DEFAULT_TIMEOUT = 30.0


class KeycloakApiError(RuntimeError):
    """Raised when Keycloak returns an unexpected response."""

    def __init__(self, message: str, *, status: int | None = None, body: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.body = body


@dataclass(frozen=True)
class AdminConfig:
    """Credentials and connection settings for Keycloak Admin REST."""

    server_url: str
    username: str
    password: str
    realm: str = DEFAULT_ADMIN_REALM
    client_id: str = DEFAULT_ADMIN_CLIENT_ID
    timeout: float = DEFAULT_TIMEOUT


@dataclass(frozen=True)
class RoleGateConfig:
    """Inputs required to create the RoleGate Browser Flow."""

    realm: str
    target_client_id: str
    required_role: str
    base_flow: str = DEFAULT_BASE_FLOW
    flow_alias: str = ""
    deny_subflow_alias: str = ""
    deny_message: str = DEFAULT_DENY_MESSAGE
    recreate: bool = False
    activate: bool = False

    def normalized(self) -> RoleGateConfig:
        """Fill aliases that depend on the target client and required role."""
        flow_alias = self.flow_alias or f"{self.target_client_id}-role-gated-browser"
        deny_subflow_alias = (
            self.deny_subflow_alias
            or f"{flow_alias}-deny-missing-{self.target_client_id}-{self.required_role}"
        )
        return RoleGateConfig(
            realm=self.realm,
            target_client_id=self.target_client_id,
            required_role=self.required_role,
            base_flow=self.base_flow,
            flow_alias=flow_alias,
            deny_subflow_alias=deny_subflow_alias,
            deny_message=self.deny_message,
            recreate=self.recreate,
            activate=self.activate,
        )


@dataclass(frozen=True)
class RoleGateResult:
    """Useful identifiers produced by the RoleGate setup."""

    realm: str
    target_client_id: str
    client_uuid: str
    required_role: str
    flow_alias: str
    flow_id: str
    activated: bool


class KeycloakAdminClient:
    """Small Admin REST client tailored to RoleGate setup operations.

    The implementation uses only Python's standard library so this repository's
    reusable script has no installation step. Each public method maps to one
    Keycloak Admin REST endpoint and validates the HTTP status that Keycloak is
    expected to return.
    """

    def __init__(self, config: AdminConfig) -> None:
        self.config = config
        self.server_url = config.server_url.rstrip("/")
        self._token: str | None = None

    def authenticate(self) -> None:
        """Fetch an admin access token with the password grant."""
        token_url = self._url(f"/realms/{_path(self.config.realm)}/protocol/openid-connect/token")
        payload = parse.urlencode(
            {
                "grant_type": "password",
                "client_id": self.config.client_id,
                "username": self.config.username,
                "password": self.config.password,
            }
        ).encode()
        req = request.Request(
            token_url,
            data=payload,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.config.timeout) as response:
                data = json.loads(response.read().decode())
        except error.HTTPError as exc:
            body = exc.read().decode(errors="replace")
            raise KeycloakApiError(
                f"Keycloak authentication failed with HTTP {exc.code}: {body}",
                status=exc.code,
                body=body,
            ) from exc
        except error.URLError as exc:
            raise KeycloakApiError(f"Cannot reach Keycloak at {token_url}: {exc}") from exc
        except (OSError, http.client.HTTPException) as exc:
            raise KeycloakApiError(f"Cannot reach Keycloak at {token_url}: {exc}") from exc

        access_token = data.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise KeycloakApiError("Keycloak token response did not contain access_token")
        self._token = access_token

    def realm_exists(self, realm: str) -> bool:
        """Return whether a realm exists."""
        try:
            self.get_json(f"/admin/realms/{_path(realm)}")
        except KeycloakApiError as exc:
            if exc.status == 404:
                return False
            raise
        return True

    def create_realm(self, body: dict[str, Any]) -> None:
        """Create a realm from a Keycloak RealmRepresentation payload."""
        self.post_json("/admin/realms", body, expected=(201,))

    def delete_realm(self, realm: str) -> None:
        """Delete a realm."""
        self.delete(f"/admin/realms/{_path(realm)}", expected=(204,))

    def find_client(self, realm: str, client_id: str) -> dict[str, Any] | None:
        """Find a client by its public `clientId`."""
        query = parse.urlencode({"clientId": client_id})
        clients = self.get_json(f"/admin/realms/{_path(realm)}/clients?{query}")
        for client in _expect_list(clients, "clients"):
            if client.get("clientId") == client_id:
                return _expect_dict(client, "client")
        return None

    def get_client(self, realm: str, client_uuid: str) -> dict[str, Any]:
        """Fetch a client by its internal UUID."""
        client = self.get_json(f"/admin/realms/{_path(realm)}/clients/{_path(client_uuid)}")
        return _expect_dict(client, "client")

    def create_client(self, realm: str, body: dict[str, Any]) -> None:
        """Create a client in a realm."""
        self.post_json(f"/admin/realms/{_path(realm)}/clients", body, expected=(201,))

    def get_client_role(self, realm: str, client_uuid: str, role_name: str) -> dict[str, Any]:
        """Fetch a client role by name."""
        role = self.get_json(
            f"/admin/realms/{_path(realm)}/clients/{_path(client_uuid)}/roles/{_path(role_name)}"
        )
        return _expect_dict(role, "client role")

    def create_client_role(self, realm: str, client_uuid: str, body: dict[str, Any]) -> None:
        """Create a client role."""
        self.post_json(
            f"/admin/realms/{_path(realm)}/clients/{_path(client_uuid)}/roles",
            body,
            expected=(201,),
        )

    def find_user(self, realm: str, username: str) -> dict[str, Any] | None:
        """Find a user by username."""
        query = parse.urlencode({"username": username, "exact": "true"})
        users = self.get_json(f"/admin/realms/{_path(realm)}/users?{query}")
        for user in _expect_list(users, "users"):
            if user.get("username") == username:
                return _expect_dict(user, "user")
        return None

    def create_user(self, realm: str, body: dict[str, Any]) -> None:
        """Create a user."""
        self.post_json(f"/admin/realms/{_path(realm)}/users", body, expected=(201,))

    def reset_user_password(self, realm: str, user_id: str, password: str) -> None:
        """Set a non-temporary password for a user."""
        self.put_json(
            f"/admin/realms/{_path(realm)}/users/{_path(user_id)}/reset-password",
            {"type": "password", "value": password, "temporary": False},
            expected=(204,),
        )

    def get_client_role_mappings(
        self, realm: str, user_id: str, client_uuid: str
    ) -> list[dict[str, Any]]:
        """Return client-role mappings assigned to a user."""
        mappings = self.get_json(
            "/admin/realms/"
            f"{_path(realm)}/users/{_path(user_id)}/role-mappings/clients/{_path(client_uuid)}"
        )
        return [_expect_dict(role, "role mapping") for role in _expect_list(mappings, "mappings")]

    def add_client_role_mapping(
        self, realm: str, user_id: str, client_uuid: str, roles: list[dict[str, Any]]
    ) -> None:
        """Assign one or more client roles to a user."""
        self.post_json(
            "/admin/realms/"
            f"{_path(realm)}/users/{_path(user_id)}/role-mappings/clients/{_path(client_uuid)}",
            roles,
            expected=(204,),
        )

    def get_flows(self, realm: str) -> list[dict[str, Any]]:
        """Return all authentication flows in a realm."""
        flows = self.get_json(f"/admin/realms/{_path(realm)}/authentication/flows")
        return [_expect_dict(flow, "flow") for flow in _expect_list(flows, "flows")]

    def flow_id_by_alias(self, realm: str, alias: str) -> str | None:
        """Find an authentication flow id by alias."""
        for flow in self.get_flows(realm):
            if flow.get("alias") == alias:
                flow_id = flow.get("id")
                return flow_id if isinstance(flow_id, str) else None
        return None

    def delete_flow(self, realm: str, flow_id: str) -> None:
        """Delete an authentication flow by id."""
        self.delete(
            f"/admin/realms/{_path(realm)}/authentication/flows/{_path(flow_id)}",
            expected=(204,),
        )

    def copy_flow(self, realm: str, base_flow_alias: str, new_name: str) -> None:
        """Copy an existing flow."""
        self.post_json(
            f"/admin/realms/{_path(realm)}/authentication/flows/{_path(base_flow_alias)}/copy",
            {"newName": new_name},
            expected=(201,),
        )

    def get_flow_executions(self, realm: str, flow_alias: str) -> list[dict[str, Any]]:
        """Return executions for a flow alias."""
        executions = self.get_json(
            f"/admin/realms/{_path(realm)}/authentication/flows/{_path(flow_alias)}/executions"
        )
        return [
            _expect_dict(execution, "flow execution")
            for execution in _expect_list(executions, "executions")
        ]

    def add_subflow(
        self,
        realm: str,
        parent_flow_alias: str,
        alias: str,
        description: str,
    ) -> None:
        """Add a basic subflow to a parent flow."""
        self.post_json(
            "/admin/realms/"
            f"{_path(realm)}/authentication/flows/{_path(parent_flow_alias)}/executions/flow",
            {
                "alias": alias,
                "type": "basic-flow",
                "provider": "basic-flow",
                "description": description,
            },
            expected=(201,),
        )

    def add_execution(self, realm: str, parent_flow_alias: str, provider_id: str) -> None:
        """Add an authenticator execution to a parent flow."""
        self.post_json(
            "/admin/realms/"
            f"{_path(realm)}/authentication/flows/{_path(parent_flow_alias)}/executions/execution",
            {"provider": provider_id},
            expected=(201,),
        )

    def update_execution_requirement(
        self, realm: str, parent_flow_alias: str, execution_id: str, requirement: str
    ) -> None:
        """Set a flow execution requirement such as REQUIRED or CONDITIONAL."""
        self.put_json(
            "/admin/realms/"
            f"{_path(realm)}/authentication/flows/{_path(parent_flow_alias)}/executions",
            {"id": execution_id, "requirement": requirement},
            expected=(204,),
        )

    def create_execution_config(
        self, realm: str, execution_id: str, alias: str, config: dict[str, str]
    ) -> None:
        """Create an authenticator config for an execution."""
        self.post_json(
            f"/admin/realms/{_path(realm)}/authentication/executions/{_path(execution_id)}/config",
            {"alias": alias, "config": config},
            expected=(201,),
        )

    def update_client_browser_flow_override(
        self, realm: str, client_uuid: str, flow_id: str
    ) -> None:
        """Bind a Browser Flow override to one client without changing the realm default."""
        client = self.get_client(realm, client_uuid)
        overrides = client.get("authenticationFlowBindingOverrides")
        if not isinstance(overrides, dict):
            overrides = {}
        overrides["browser"] = flow_id
        client["authenticationFlowBindingOverrides"] = overrides
        self.put_json(
            f"/admin/realms/{_path(realm)}/clients/{_path(client_uuid)}",
            client,
            expected=(204,),
        )

    def get_json(self, path: str) -> Any:
        """Perform a GET request and decode the JSON response."""
        body = self._request(path, method="GET", expected=(200,))
        return json.loads(body.decode() or "null")

    def post_json(
        self, path: str, payload: Any, *, expected: tuple[int, ...] = (200, 201, 204)
    ) -> bytes:
        """Perform a JSON POST request."""
        return self._request(path, method="POST", payload=payload, expected=expected)

    def put_json(self, path: str, payload: Any, *, expected: tuple[int, ...] = (200, 204)) -> bytes:
        """Perform a JSON PUT request."""
        return self._request(path, method="PUT", payload=payload, expected=expected)

    def delete(self, path: str, *, expected: tuple[int, ...] = (204,)) -> bytes:
        """Perform a DELETE request."""
        return self._request(path, method="DELETE", expected=expected)

    def _request(
        self,
        path: str,
        *,
        method: str,
        payload: Any | None = None,
        expected: tuple[int, ...],
        retry_on_unauthorized: bool = True,
    ) -> bytes:
        if self._token is None:
            self.authenticate()

        data = None
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._token}",
        }
        if payload is not None:
            data = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"

        req = request.Request(
            self._url(path),
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with request.urlopen(req, timeout=self.config.timeout) as response:
                body = response.read()
                status = response.status
        except error.HTTPError as exc:
            body = exc.read()
            if exc.code == 401 and retry_on_unauthorized:
                # Tokens are short lived in some deployments. Refresh once and retry.
                self.authenticate()
                return self._request(
                    path,
                    method=method,
                    payload=payload,
                    expected=expected,
                    retry_on_unauthorized=False,
                )
            message = _format_http_error(method, req.full_url, exc.code, body)
            raise KeycloakApiError(
                message, status=exc.code, body=body.decode(errors="replace")
            ) from exc
        except error.URLError as exc:
            raise KeycloakApiError(f"Cannot reach Keycloak at {req.full_url}: {exc}") from exc
        except (OSError, http.client.HTTPException) as exc:
            raise KeycloakApiError(f"Cannot reach Keycloak at {req.full_url}: {exc}") from exc

        if status not in expected:
            message = _format_http_error(method, req.full_url, status, body)
            raise KeycloakApiError(message, status=status, body=body.decode(errors="replace"))
        return body

    def _url(self, path: str) -> str:
        return f"{self.server_url}{path}"


def create_or_reuse_role_gate_flow(
    admin: KeycloakAdminClient, config: RoleGateConfig
) -> RoleGateResult:
    """Create or reuse the RoleGate flow and optionally activate it on the client."""
    config = config.normalized()
    client = admin.find_client(config.realm, config.target_client_id)
    if client is None:
        raise KeycloakApiError(
            f"Client not found in realm {config.realm}: {config.target_client_id}"
        )

    client_uuid = _string_field(client, "id", "client")
    admin.get_client_role(config.realm, client_uuid, config.required_role)

    existing_flow_id = admin.flow_id_by_alias(config.realm, config.flow_alias)
    if existing_flow_id and config.recreate:
        admin.delete_flow(config.realm, existing_flow_id)
        existing_flow_id = None

    if not existing_flow_id:
        _create_role_gate_flow(admin, config)

    flow_id = admin.flow_id_by_alias(config.realm, config.flow_alias)
    if flow_id is None:
        raise KeycloakApiError(f"Flow was not found after creation: {config.flow_alias}")

    if config.activate:
        admin.update_client_browser_flow_override(config.realm, client_uuid, flow_id)

    return RoleGateResult(
        realm=config.realm,
        target_client_id=config.target_client_id,
        client_uuid=client_uuid,
        required_role=config.required_role,
        flow_alias=config.flow_alias,
        flow_id=flow_id,
        activated=config.activate,
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line interface.

    Every option can also be supplied through the environment variable named in
    its help text. CLI arguments win over environment variables.
    """
    parser = argparse.ArgumentParser(
        prog=os.getenv("ROLEGATE_PROG"),
        description="Create a Keycloak client-role-gated Browser Flow using Admin REST.",
    )
    parser.add_argument(
        "--server-url",
        default=os.getenv("KC_SERVER_URL", DEFAULT_SERVER_URL),
        help=f"Keycloak base URL. Env: KC_SERVER_URL. Default: {DEFAULT_SERVER_URL}",
    )
    parser.add_argument("--realm", default=os.getenv("REALM"), help="Target realm. Env: REALM")
    parser.add_argument(
        "--target-client-id",
        default=os.getenv("TARGET_CLIENT_ID"),
        help="OIDC client id to protect. Env: TARGET_CLIENT_ID",
    )
    parser.add_argument(
        "--required-role",
        default=os.getenv("REQUIRED_ROLE"),
        help="Client role required for login. Env: REQUIRED_ROLE",
    )
    parser.add_argument(
        "--admin-username",
        default=os.getenv("KEYCLOAK_ADMIN"),
        help="Keycloak admin username. Env: KEYCLOAK_ADMIN",
    )
    parser.add_argument(
        "--admin-password",
        default=os.getenv("KEYCLOAK_ADMIN_PASSWORD"),
        help="Keycloak admin password. Env: KEYCLOAK_ADMIN_PASSWORD",
    )
    parser.add_argument(
        "--admin-realm",
        default=os.getenv("KEYCLOAK_ADMIN_REALM", DEFAULT_ADMIN_REALM),
        help=f"Realm used to authenticate the admin user. Env: KEYCLOAK_ADMIN_REALM. "
        f"Default: {DEFAULT_ADMIN_REALM}",
    )
    parser.add_argument(
        "--admin-client-id",
        default=os.getenv("KEYCLOAK_ADMIN_CLIENT_ID", DEFAULT_ADMIN_CLIENT_ID),
        help=f"Admin token client id. Env: KEYCLOAK_ADMIN_CLIENT_ID. "
        f"Default: {DEFAULT_ADMIN_CLIENT_ID}",
    )
    parser.add_argument(
        "--base-flow",
        default=os.getenv("BASE_FLOW", DEFAULT_BASE_FLOW),
        help=f"Browser Flow alias to copy. Env: BASE_FLOW. Default: {DEFAULT_BASE_FLOW}",
    )
    parser.add_argument(
        "--flow-alias",
        default=os.getenv("FLOW_ALIAS", ""),
        help="Generated flow alias. Env: FLOW_ALIAS. Default: <client>-role-gated-browser",
    )
    parser.add_argument(
        "--deny-subflow-alias",
        default=os.getenv("DENY_SUBFLOW_ALIAS", ""),
        help="Generated deny subflow alias. Env: DENY_SUBFLOW_ALIAS",
    )
    parser.add_argument(
        "--deny-message",
        default=os.getenv("DENY_MESSAGE", DEFAULT_DENY_MESSAGE),
        help=f"Message shown by Keycloak to blocked users. Env: DENY_MESSAGE. "
        f"Default: {DEFAULT_DENY_MESSAGE!r}",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        default=_env_bool("RECREATE", False),
        help="Delete and recreate the generated flow. Env: RECREATE=true",
    )
    parser.add_argument(
        "--activate",
        action="store_true",
        default=_env_bool("ACTIVATE_CLIENT_FLOW", False),
        help="Bind the generated flow to the target client. Env: ACTIVATE_CLIENT_FLOW=true",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.getenv("KEYCLOAK_API_TIMEOUT", str(DEFAULT_TIMEOUT))),
        help=f"HTTP timeout in seconds. Env: KEYCLOAK_API_TIMEOUT. Default: {DEFAULT_TIMEOUT}",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the result as JSON instead of human-readable text.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args(argv)

    for option, value in (
        ("--realm or REALM", args.realm),
        ("--target-client-id or TARGET_CLIENT_ID", args.target_client_id),
        ("--required-role or REQUIRED_ROLE", args.required_role),
        ("--admin-username or KEYCLOAK_ADMIN", args.admin_username),
        ("--admin-password or KEYCLOAK_ADMIN_PASSWORD", args.admin_password),
    ):
        if not value:
            parser.error(f"{option} is required")

    admin = KeycloakAdminClient(
        AdminConfig(
            server_url=args.server_url,
            username=args.admin_username,
            password=args.admin_password,
            realm=args.admin_realm,
            client_id=args.admin_client_id,
            timeout=args.timeout,
        )
    )
    config = RoleGateConfig(
        realm=args.realm,
        target_client_id=args.target_client_id,
        required_role=args.required_role,
        base_flow=args.base_flow,
        flow_alias=args.flow_alias,
        deny_subflow_alias=args.deny_subflow_alias,
        deny_message=args.deny_message,
        recreate=args.recreate,
        activate=args.activate,
    )

    try:
        result = create_or_reuse_role_gate_flow(admin, config)
    except KeycloakApiError as exc:
        print(f"RoleGate setup failed: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(asdict(result), indent=2, sort_keys=True))
    else:
        _print_result(result, args.server_url)
    return 0


def _create_role_gate_flow(admin: KeycloakAdminClient, config: RoleGateConfig) -> None:
    """Create the copied Browser Flow and its deny subflow."""
    admin.copy_flow(config.realm, config.base_flow, config.flow_alias)

    top_executions = admin.get_flow_executions(config.realm, config.flow_alias)
    forms_flow_alias = _forms_flow_alias(top_executions, config.flow_alias)

    admin.add_subflow(
        config.realm,
        forms_flow_alias,
        config.deny_subflow_alias,
        f"Reject users missing {config.target_client_id}.{config.required_role}",
    )
    deny_subflow_execution_id = _execution_id(
        admin.get_flow_executions(config.realm, forms_flow_alias),
        config.deny_subflow_alias,
        forms_flow_alias,
    )
    admin.update_execution_requirement(
        config.realm, forms_flow_alias, deny_subflow_execution_id, "CONDITIONAL"
    )

    admin.add_execution(config.realm, config.deny_subflow_alias, "conditional-user-role")
    condition_execution_id = _execution_id_by_provider(
        admin.get_flow_executions(config.realm, config.deny_subflow_alias),
        "conditional-user-role",
        config.deny_subflow_alias,
    )
    admin.update_execution_requirement(
        config.realm, config.deny_subflow_alias, condition_execution_id, "REQUIRED"
    )
    admin.create_execution_config(
        config.realm,
        condition_execution_id,
        "User lacks required client role",
        {
            "condUserRole": f"{config.target_client_id}.{config.required_role}",
            "negate": "true",
        },
    )

    admin.add_execution(config.realm, config.deny_subflow_alias, "deny-access-authenticator")
    deny_execution_id = _execution_id_by_provider(
        admin.get_flow_executions(config.realm, config.deny_subflow_alias),
        "deny-access-authenticator",
        config.deny_subflow_alias,
    )
    admin.update_execution_requirement(
        config.realm, config.deny_subflow_alias, deny_execution_id, "REQUIRED"
    )
    admin.create_execution_config(
        config.realm,
        deny_execution_id,
        "Deny missing role",
        {"denyErrorMessage": config.deny_message},
    )


def _print_result(result: RoleGateResult, server_url: str) -> None:
    print("Created or reused flow:")
    print(f"  realm: {result.realm}")
    print(f"  client id: {result.target_client_id}")
    print(f"  client uuid: {result.client_uuid}")
    print(f"  required role: {result.required_role}")
    print(f"  flow alias: {result.flow_alias}")
    print(f"  flow id: {result.flow_id}")
    print(f"  activated on client: {'yes' if result.activated else 'no'}")

    if not result.activated:
        activation_path = f"/admin/realms/{_path(result.realm)}/clients/{_path(result.client_uuid)}"
        print()
        print("Activation options:")
        print("  rerun with: --activate")
        print(f"  or PUT: {server_url.rstrip('/')}{activation_path}")
        print(
            "  payload: "
            + json.dumps({"authenticationFlowBindingOverrides": {"browser": result.flow_id}})
        )


def _forms_flow_alias(executions: list[dict[str, Any]], flow_alias: str) -> str:
    """Find the copied flow's forms subflow.

    Keycloak versions differ slightly in whether the useful display value lands
    in `displayName`, `alias`, or `flowAlias`. The fallback matches the alias
    Keycloak creates when copying the built-in Browser Flow.
    """
    for execution in executions:
        display = _display_name(execution)
        if execution.get("authenticationFlow") and display.lower().endswith(" forms"):
            return _flow_alias_or_display(execution, display)

    for execution in executions:
        display = _display_name(execution)
        if execution.get("authenticationFlow") and "forms" in display.lower():
            return _flow_alias_or_display(execution, display)

    return f"{flow_alias} forms"


def _execution_id(executions: list[dict[str, Any]], match: str, parent_flow_alias: str) -> str:
    for execution in executions:
        candidates = {
            execution.get("id"),
            execution.get("displayName"),
            execution.get("alias"),
            execution.get("flowAlias"),
            execution.get("providerId"),
        }
        if match in candidates:
            return _string_field(execution, "id", f"execution {match}")
    raise KeycloakApiError(f"Execution not found in flow {parent_flow_alias}: {match}")


def _execution_id_by_provider(
    executions: list[dict[str, Any]], provider_id: str, parent_flow_alias: str
) -> str:
    for execution in reversed(executions):
        if execution.get("providerId") == provider_id:
            return _string_field(execution, "id", f"execution provider {provider_id}")
    raise KeycloakApiError(
        f"Execution provider not found in flow {parent_flow_alias}: {provider_id}"
    )


def _display_name(execution: dict[str, Any]) -> str:
    value = execution.get("displayName") or execution.get("alias") or execution.get("flowAlias")
    return value if isinstance(value, str) else ""


def _flow_alias_or_display(execution: dict[str, Any], display: str) -> str:
    value = execution.get("flowAlias")
    return value if isinstance(value, str) and value else display


def _expect_dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise KeycloakApiError(f"Expected {label} to be an object")
    return value


def _expect_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise KeycloakApiError(f"Expected {label} to be a list")
    return value


def _string_field(value: dict[str, Any], field: str, label: str) -> str:
    field_value = value.get(field)
    if not isinstance(field_value, str) or not field_value:
        raise KeycloakApiError(f"Expected {label}.{field} to be a non-empty string")
    return field_value


def _format_http_error(method: str, url: str, status: int, body: bytes) -> str:
    text = body.decode(errors="replace")
    if len(text) > 1000:
        text = f"{text[:1000]}..."
    return f"{method} {url} failed with HTTP {status}: {text}"


def _path(value: str) -> str:
    return parse.quote(value, safe="")


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    raise SystemExit(main())
