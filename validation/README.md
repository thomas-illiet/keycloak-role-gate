# RoleGate Validation

This directory contains the local validation environment used by the root
`Makefile`.

The reusable Keycloak setup script lives at:

```bash
../scripts/rolegate-setup.sh
```

Run the validation from the repository root:

```bash
make validation
```

See the full validation documentation in
[`../docs/local-validation.md`](../docs/local-validation.md).
