# Script Usage

Use the main script from the repository root:

```bash
./scripts/keycloak-create-client-role-flow.sh
```

## Requirements

- Keycloak is running through Docker Compose.
- The Keycloak Compose service is named `keycloak`, or `COMPOSE_SERVICE` is set.
- `kcadm.sh` is available in the Keycloak container at
  `/opt/keycloak/bin/kcadm.sh`.
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

./scripts/keycloak-create-client-role-flow.sh
```

The script creates or reuses a flow named:

```text
my-product-role-gated-browser
```

It then prints the activation command for the target client.

## Variables

| Variable | Default | Description |
| --- | --- | --- |
| `REALM` | required | Keycloak realm to configure |
| `TARGET_CLIENT_ID` | required | OIDC client to protect |
| `REQUIRED_ROLE` | required | Client role required to access the client |
| `KEYCLOAK_ADMIN` | required | Keycloak admin username |
| `KEYCLOAK_ADMIN_PASSWORD` | required | Keycloak admin password |
| `COMPOSE_SERVICE` | `keycloak` | Docker Compose service name for Keycloak |
| `KC_SERVER_URL` | `http://localhost:8080` | Keycloak URL used by `kcadm.sh` |
| `BASE_FLOW` | `browser` | Browser Flow copied by RoleGate |
| `FLOW_ALIAS` | `<client>-role-gated-browser` | Alias of the generated flow |
| `DENY_MESSAGE` | `Access denied: missing required role` | Message shown to blocked users |
| `RECREATE` | `false` | Delete and recreate the flow if it already exists |

## Recreating A Flow

During development, you can force the script to recreate the generated flow:

```bash
RECREATE=true ./scripts/keycloak-create-client-role-flow.sh
```

Use this carefully against shared environments, because it deletes the existing
flow with the same alias before creating it again.
