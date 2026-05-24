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
export ROLEGATE_REALM=my-realm
export ROLEGATE_TARGET_CLIENT_ID=my-product
export ROLEGATE_REQUIRED_ROLE=app-access
export ROLEGATE_ADMIN_USERNAME=admin
export ROLEGATE_ADMIN_PASSWORD=admin

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

All environment variables exposed by the reusable setup script use the
`ROLEGATE_` prefix. CLI arguments still take precedence over environment
variables.

### Required

| Variable | Default | Description |
| --- | --- | --- |
| `ROLEGATE_REALM` | required | Keycloak realm to configure |
| `ROLEGATE_TARGET_CLIENT_ID` | required | OIDC client to protect |
| `ROLEGATE_REQUIRED_ROLE` | required | Client role required to access the client |
| `ROLEGATE_ADMIN_USERNAME` | required | Keycloak admin username |
| `ROLEGATE_ADMIN_PASSWORD` | required | Keycloak admin password |

### Optional

| Variable | Default | Description |
| --- | --- | --- |
| `ROLEGATE_KEYCLOAK_URL` | `http://localhost:8080` | Keycloak base URL used by the Admin REST client |
| `ROLEGATE_ADMIN_REALM` | `master` | Realm used to authenticate the admin user |
| `ROLEGATE_ADMIN_CLIENT_ID` | `admin-cli` | Client id used for the admin token request |
| `ROLEGATE_BASE_FLOW` | `browser` | Browser Flow copied by RoleGate |
| `ROLEGATE_FLOW_ALIAS` | `<client>-role-gated-browser` | Alias of the generated flow |
| `ROLEGATE_DENY_SUBFLOW_ALIAS` | derived from flow, client, and role | Alias of the generated deny subflow |
| `ROLEGATE_DENY_MESSAGE` | `Access denied: missing required role` | Message shown to blocked users |
| `ROLEGATE_RECREATE` | `false` | Delete and recreate the flow if it already exists |
| `ROLEGATE_ACTIVATE` | `false` | Bind the generated flow to the target client |
| `ROLEGATE_API_TIMEOUT` | `30` | HTTP timeout in seconds |

## Recreating A Flow

During development, you can force the script to recreate the generated flow:

```bash
ROLEGATE_RECREATE=true ./scripts/rolegate-setup.sh
```

Use this carefully against shared environments, because it deletes the existing
flow with the same alias before creating it again.
