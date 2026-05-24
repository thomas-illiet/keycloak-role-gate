# Script Usage

Use the main script from the repository root:

```bash
./scripts/rolegate-setup.sh
```

## Requirements

- Keycloak is reachable over HTTP from the machine running the script.
- The admin account can manage clients, roles, and authentication flows.
- The target realm already exists.
- The target OIDC client already exists.
- The required client role already exists on that client.

## Example

```bash
export REALM=my-realm
export TARGET_CLIENT_ID=my-product
export REQUIRED_ROLE=app-access
export KEYCLOAK_ADMIN=admin
export KEYCLOAK_ADMIN_PASSWORD=admin

./scripts/rolegate-setup.sh
```

The script creates or reuses a flow named:

```text
my-product-role-gated-browser
```

It then prints the activation details for the target client. To bind the flow
immediately, pass `--activate`:

```bash
./scripts/rolegate-setup.sh --activate
```

## Variables

| Variable | Default | Description |
| --- | --- | --- |
| `REALM` | required | Keycloak realm to configure |
| `TARGET_CLIENT_ID` | required | OIDC client to protect |
| `REQUIRED_ROLE` | required | Client role required to access the client |
| `KEYCLOAK_ADMIN` | required | Keycloak admin username |
| `KEYCLOAK_ADMIN_PASSWORD` | required | Keycloak admin password |
| `KC_SERVER_URL` | `http://localhost:8080` | Keycloak base URL used by the Admin REST client |
| `KEYCLOAK_ADMIN_REALM` | `master` | Realm used to authenticate the admin user |
| `KEYCLOAK_ADMIN_CLIENT_ID` | `admin-cli` | Client id used for the admin token request |
| `BASE_FLOW` | `browser` | Browser Flow copied by RoleGate |
| `FLOW_ALIAS` | `<client>-role-gated-browser` | Alias of the generated flow |
| `DENY_SUBFLOW_ALIAS` | derived from flow, client, and role | Alias of the generated deny subflow |
| `DENY_MESSAGE` | `Access denied: missing required role` | Message shown to blocked users |
| `RECREATE` | `false` | Delete and recreate the flow if it already exists |
| `ACTIVATE_CLIENT_FLOW` | `false` | Bind the generated flow to the target client |
| `KEYCLOAK_API_TIMEOUT` | `30` | HTTP timeout in seconds |

## Recreating A Flow

During development, you can force the script to recreate the generated flow:

```bash
RECREATE=true ./scripts/rolegate-setup.sh
```

Use this carefully against shared environments, because it deletes the existing
flow with the same alias before creating it again.
