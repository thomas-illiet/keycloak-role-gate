# Caveats

## Token Validation Still Matters

The application must still validate received OIDC tokens correctly:

- signature;
- issuer;
- audience;
- expiration;
- nonce/state where applicable.

RoleGate decides whether a user may enter the client. It does not remove the
need for normal OIDC validation.

## Browser/OIDC Scope

RoleGate targets the Browser/OIDC login path. If your deployment uses other
Keycloak flows, such as Direct Grant, service accounts, or custom token flows,
review those separately.

## Client Role Requirement

The required role is a Keycloak client role. For a client `my-product` and role
`app-access`, the role reference is:

```text
my-product.app-access
```

Realm roles or application-internal roles are not equivalent.

## Existing SSO Sessions

Some deployments require strict revalidation for users who already have a
Keycloak SSO session. Depending on the exact behavior you need, a client-level
Browser Flow override may not be enough and a custom Keycloak provider can be
more appropriate.

## Fine-Grained Authorization

RoleGate is an entry gate for one client. It is not a full authorization model
for business actions inside the application.
