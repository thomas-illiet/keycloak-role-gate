# Dependabot Updates

RoleGate uses Dependabot to propose Keycloak image upgrades through pull
requests.

The configuration lives in:

```text
.github/dependabot.yml
```

## Keycloak Image Updates

Dependabot monitors the Docker Compose manifest in:

```text
validation/docker-compose.yml
```

The Keycloak image is intentionally written as a direct image reference:

```yaml
image: quay.io/keycloak/keycloak:26.4.0
```

This allows the Docker Compose updater to detect the dependency and propose PRs
when a newer Keycloak tag is available.

## PR Validation

Dependabot PRs target the normal pull request workflow. The E2E validation runs
on every PR targeting `main`, so Keycloak upgrade proposals are validated before
they are merged.

## Scope

The Dependabot configuration is restricted to:

```text
quay.io/keycloak/keycloak
```

This keeps dependency PRs focused on Keycloak upgrades instead of updating every
Docker image used by the validation environment.
