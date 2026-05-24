# RoleGate Validation

This directory contains the local validation environment used by the root
`Makefile`.

The reusable Keycloak setup script lives at:

```bash
../scripts/keycloak-create-client-role-flow.sh
```

Run the validation from the repository root:

```bash
make e2e
```

See the full validation documentation in
[`../docs/local-validation.md`](../docs/local-validation.md).
