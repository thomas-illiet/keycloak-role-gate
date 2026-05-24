"""Tiny OIDC target app used by the Keycloak role-gated flow E2E suite."""

__all__ = ["__version__", "main"]

__version__ = "0.1.0"


def main() -> None:
    """Run the local FastAPI target app."""
    import uvicorn

    uvicorn.run("keycloak_role_gate_e2e.app:app", host="0.0.0.0", port=8000)
