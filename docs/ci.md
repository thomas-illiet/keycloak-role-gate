# Continuous Integration

The repository includes a GitHub Actions workflow for RoleGate validation:

```text
.github/workflows/e2e.yml
```

## Triggers

The E2E validation runs on:

- pushes to `main`;
- pull requests targeting `main`;
- manual runs through `workflow_dispatch`.

This includes Dependabot pull requests that update the Keycloak image.

## What The Workflow Runs

The workflow executes:

```bash
make e2e-ci
```

This target:

- installs the validation Python dependencies with `uv`;
- installs Playwright Chromium with Linux system dependencies;
- starts the Docker Compose validation stack;
- configures Keycloak with the RoleGate flow;
- runs the Playwright checks for `allowed` and `blocked` users.

If the validation fails, the workflow prints Docker Compose logs before
cleaning up containers and volumes.

## Badge

The root README shows the status of the latest `main` branch run for the E2E
workflow.
