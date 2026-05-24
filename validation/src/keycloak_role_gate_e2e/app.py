"""FastAPI target app for the Keycloak E2E scenario.

The app deliberately avoids application-level RBAC. It only performs the
regular OIDC code flow and validates the ID token before creating a session.
The client-role access decision is enforced by Keycloak's authentication flow.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass
from html import escape
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import Response


@dataclass(frozen=True)
class Settings:
    """Runtime OIDC settings loaded from environment variables."""

    public_keycloak_url: str = os.getenv("OIDC_PUBLIC_KEYCLOAK_URL", "http://localhost:8080")
    internal_keycloak_url: str = os.getenv("OIDC_INTERNAL_KEYCLOAK_URL", "http://keycloak:8080")
    realm: str = os.getenv("OIDC_REALM", "role-gate-e2e")
    client_id: str = os.getenv("OIDC_CLIENT_ID", "python-app")
    client_secret: str = os.getenv("OIDC_CLIENT_SECRET", "python-app-secret")
    redirect_uri: str = os.getenv("OIDC_REDIRECT_URI", "http://localhost:8000/auth/callback")
    session_secret: str = os.getenv("APP_SESSION_SECRET", "dev-only-session-secret")
    scope: str = os.getenv("OIDC_SCOPE", "openid profile email")

    @property
    def issuer(self) -> str:
        return f"{self.public_keycloak_url.rstrip('/')}/realms/{self.realm}"

    @property
    def authorization_endpoint(self) -> str:
        return f"{self.issuer}/protocol/openid-connect/auth"

    @property
    def token_endpoint(self) -> str:
        return (
            f"{self.internal_keycloak_url.rstrip('/')}/realms/{self.realm}"
            "/protocol/openid-connect/token"
        )

    @property
    def jwks_endpoint(self) -> str:
        return (
            f"{self.internal_keycloak_url.rstrip('/')}/realms/{self.realm}"
            "/protocol/openid-connect/certs"
        )


settings = Settings()
app = FastAPI(title="Keycloak role-gate E2E target")
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    same_site="lax",
    https_only=False,
)


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> Response:
    user = request.session.get("user")
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    username = escape(str(user.get("preferred_username") or user.get("sub") or "unknown"))
    return HTMLResponse(
        f"""
        <!doctype html>
        <html lang="en">
          <head>
            <meta charset="utf-8">
            <title>Python target app</title>
            <style>
              body {{
                font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                margin: 0;
                min-height: 100vh;
                display: grid;
                place-items: center;
                background: #f8fafc;
                color: #0f172a;
              }}
              main {{
                width: min(560px, calc(100vw - 32px));
                border: 1px solid #cbd5e1;
                border-radius: 8px;
                padding: 32px;
                background: #ffffff;
                box-shadow: 0 16px 40px rgba(15, 23, 42, 0.08);
              }}
              h1 {{
                margin: 0 0 12px;
                font-size: 28px;
              }}
              p {{
                margin: 0;
                line-height: 1.5;
              }}
            </style>
          </head>
          <body>
            <main data-testid="authenticated-app">
              <h1>Python target app reached</h1>
              <p>Authenticated as <strong data-testid="username">{username}</strong>.</p>
            </main>
          </body>
        </html>
        """
    )


@app.get("/login")
async def login(request: Request) -> RedirectResponse:
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    request.session["oidc_state"] = state
    request.session["oidc_nonce"] = nonce

    query = urlencode(
        {
            "client_id": settings.client_id,
            "redirect_uri": settings.redirect_uri,
            "response_type": "code",
            "scope": settings.scope,
            "state": state,
            "nonce": nonce,
        }
    )
    return RedirectResponse(url=f"{settings.authorization_endpoint}?{query}", status_code=303)


@app.get("/auth/callback")
async def auth_callback(request: Request) -> Response:
    error = request.query_params.get("error")
    if error:
        description = request.query_params.get("error_description", error)
        return HTMLResponse(f"OIDC login failed: {escape(description)}", status_code=401)

    state = request.query_params.get("state")
    expected_state = request.session.pop("oidc_state", None)
    expected_nonce = request.session.pop("oidc_nonce", None)
    if not state or state != expected_state or not expected_nonce:
        return HTMLResponse("OIDC state validation failed", status_code=401)

    code = request.query_params.get("code")
    if not code:
        return HTMLResponse("OIDC callback is missing code", status_code=401)

    async with httpx.AsyncClient(timeout=15.0) as client:
        token_response = await client.post(
            settings.token_endpoint,
            data={
                "grant_type": "authorization_code",
                "client_id": settings.client_id,
                "client_secret": settings.client_secret,
                "code": code,
                "redirect_uri": settings.redirect_uri,
            },
        )
        if token_response.status_code >= 400:
            return HTMLResponse(
                f"OIDC token exchange failed: {escape(token_response.text)}",
                status_code=401,
            )
        tokens = token_response.json()

        jwks_response = await client.get(settings.jwks_endpoint)
        jwks_response.raise_for_status()
        claims = _decode_id_token(tokens["id_token"], jwks_response.json(), expected_nonce)

    request.session["user"] = {
        "sub": claims.get("sub"),
        "preferred_username": claims.get("preferred_username"),
        "email": claims.get("email"),
    }
    return RedirectResponse(url="/", status_code=303)


@app.post("/logout")
async def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)


def _decode_id_token(id_token: str, jwks: dict[str, Any], nonce: str) -> dict[str, Any]:
    header_b64, payload_b64, signature_b64 = _split_jwt(id_token)
    header = json.loads(_base64url_decode(header_b64))
    claims = json.loads(_base64url_decode(payload_b64))

    if header.get("alg") != "RS256":
        raise ValueError("Only RS256 ID tokens are supported")

    signing_key = next(
        (
            key
            for key in jwks.get("keys", [])
            if key.get("kid") == header.get("kid") and key.get("kty") == "RSA"
        ),
        None,
    )
    if not signing_key:
        raise ValueError("ID token signing key was not found in JWKS")

    signed_data = f"{header_b64}.{payload_b64}".encode()
    signature = _base64url_decode(signature_b64)
    _verify_rs256_signature(signed_data, signature, signing_key)
    _validate_claims(claims)
    if claims.get("nonce") != nonce:
        raise ValueError("ID token nonce validation failed")
    return claims


def _split_jwt(token: str) -> tuple[str, str, str]:
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid JWT structure")
    return parts[0], parts[1], parts[2]


def _base64url_decode(value: str) -> bytes:
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded.encode())


def _jwk_int(jwk: dict[str, Any], field: str) -> int:
    return int.from_bytes(_base64url_decode(str(jwk[field])), "big")


def _verify_rs256_signature(signed_data: bytes, signature: bytes, jwk: dict[str, Any]) -> None:
    modulus = _jwk_int(jwk, "n")
    exponent = _jwk_int(jwk, "e")
    key_size = (modulus.bit_length() + 7) // 8
    if len(signature) != key_size:
        raise ValueError("Invalid JWT signature length")

    encoded_message = pow(int.from_bytes(signature, "big"), exponent, modulus).to_bytes(
        key_size,
        "big",
    )
    digest_info = bytes.fromhex("3031300d060960864801650304020105000420")
    expected_tail = digest_info + hashlib.sha256(signed_data).digest()

    if not encoded_message.startswith(b"\x00\x01"):
        raise ValueError("Invalid JWT signature padding")

    try:
        separator_index = encoded_message.index(b"\x00", 2)
    except ValueError as exc:
        raise ValueError("Invalid JWT signature padding") from exc

    padding = encoded_message[2:separator_index]
    if len(padding) < 8 or any(byte != 0xFF for byte in padding):
        raise ValueError("Invalid JWT signature padding")

    actual_tail = encoded_message[separator_index + 1 :]
    if not hmac.compare_digest(actual_tail, expected_tail):
        raise ValueError("Invalid JWT signature")


def _validate_claims(claims: dict[str, Any]) -> None:
    now = int(time.time())
    leeway = 30

    if claims.get("iss") != settings.issuer:
        raise ValueError("ID token issuer validation failed")

    audience = claims.get("aud")
    if isinstance(audience, list):
        valid_audience = settings.client_id in audience
    else:
        valid_audience = audience == settings.client_id
    if not valid_audience:
        raise ValueError("ID token audience validation failed")

    expires_at = int(claims.get("exp", 0))
    if expires_at + leeway < now:
        raise ValueError("ID token has expired")

    not_before = claims.get("nbf")
    if not_before is not None and int(not_before) - leeway > now:
        raise ValueError("ID token is not valid yet")
