# Local Validation

The repository includes a local validation environment under `validation/`.
It verifies that the generated Keycloak flow accepts one user and blocks
another user.

This environment is optional. The reusable setup script is still:

```bash
./scripts/rolegate-setup.sh
```

## What It Starts

The validation environment creates:

- a Keycloak container;
- a small Python target application;
- a test realm named `role-gate-validation`;
- an OIDC client named `python-app`;
- a client role named `app-access`;
- user `allowed` with the role;
- user `blocked` without the role.

## Run Validation

From the repository root:

```bash
make validation
```

Useful targets:

```bash
make dev        # install Python dependencies and Playwright Chromium
make validation-up     # start the containers
make validation-setup  # configure Keycloak and activate the flow on the test client
make validation-test   # run the allowed/blocked browser checks
make validation-logs   # show Docker Compose logs
make validation-clean  # remove containers, volumes, and validation caches
```

## Defaults

- Keycloak: http://localhost:8080
- Validation app: http://localhost:8000
- Realm: `role-gate-validation`
- Client: `python-app`
- Required role: `app-access`
- Allowed user: `allowed` / `password`
- Blocked user: `blocked` / `password`

## Configuration

The validation environment reuses the main `ROLEGATE_` variables for the
Keycloak realm, client, role, and admin credentials. Settings that only exist
for the local validation app use the `ROLEGATE_VALIDATION_` prefix.

| Variable | Default | Description |
| --- | --- | --- |
| `ROLEGATE_KEYCLOAK_URL` | `http://localhost:8080` | Keycloak URL reached by setup scripts on the host |
| `ROLEGATE_ADMIN_USERNAME` | `admin` | Keycloak bootstrap and admin username |
| `ROLEGATE_ADMIN_PASSWORD` | `admin` | Keycloak bootstrap and admin password |
| `ROLEGATE_REALM` | `role-gate-validation` | Validation realm name |
| `ROLEGATE_TARGET_CLIENT_ID` | `python-app` | Validation OIDC client id |
| `ROLEGATE_REQUIRED_ROLE` | `app-access` | Required client role assigned to user `allowed` |
| `ROLEGATE_DENY_MESSAGE` | `Access denied: missing required role` | Message asserted by the blocked-user browser test |
| `ROLEGATE_FLOW_ALIAS` | `<client>-role-gated-browser` | Optional generated flow alias override |
| `ROLEGATE_VALIDATION_APP_URL` | `http://localhost:8000` | Browser-facing URL of the validation app |
| `ROLEGATE_VALIDATION_REDIRECT_URI` | `<app-url>/auth/callback` | OIDC callback URL registered on the validation client |
| `ROLEGATE_VALIDATION_CLIENT_SECRET` | `python-app-secret` | Secret configured on the validation OIDC client |
| `ROLEGATE_VALIDATION_USER_PASSWORD` | `password` | Password assigned to both validation users |
| `ROLEGATE_VALIDATION_RESET_REALM` | `true` | Delete and recreate the validation realm before setup |
| `ROLEGATE_VALIDATION_PUBLIC_KEYCLOAK_URL` | `http://localhost:8080` | Browser-facing Keycloak URL used by the app |
| `ROLEGATE_VALIDATION_INTERNAL_KEYCLOAK_URL` | `http://keycloak:8080` | Container-internal Keycloak URL used for token and JWKS calls |
| `ROLEGATE_VALIDATION_SESSION_SECRET` | `validation-session-secret-change-me` | Session signing secret for the validation app |
| `ROLEGATE_VALIDATION_OIDC_SCOPE` | `openid profile email` | OIDC scope requested by the validation app |

Example:

```bash
ROLEGATE_REALM=my-validation-realm \
ROLEGATE_TARGET_CLIENT_ID=my-python-app \
ROLEGATE_REQUIRED_ROLE=app-access \
make validation
```
