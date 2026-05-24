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
