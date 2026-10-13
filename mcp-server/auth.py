"""
Optional defense-in-depth Okta token validation for the MCP server itself.

APIM is the primary gateway and validates the Okta JWT before traffic ever
reaches this server. This module lets the MCP server OPTIONALLY re-validate the
token (zero-trust: don't blindly trust the network between APIM and backend).

Enable by setting VERIFY_OKTA_TOKEN=1 and the OKTA_ISSUER / OKTA_AUDIENCE env
vars. Validation fetches Okta's JWKS and verifies signature, issuer, audience,
expiry, and the snowflake.query scope.
"""

import os
import time
from functools import lru_cache
from urllib.request import urlopen
import json

REQUIRED_SCOPE = "snowflake.query"


class AuthError(Exception):
    pass


@lru_cache(maxsize=1)
def _jwks(jwks_uri: str, _ttl_bucket: int):
    with urlopen(jwks_uri, timeout=5) as r:  # noqa: S310 (trusted Okta URL)
        return json.loads(r.read())


def _openid_config(issuer: str) -> dict:
    url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    with urlopen(url, timeout=5) as r:  # noqa: S310
        return json.loads(r.read())


def verify_token(authorization_header: str) -> dict:
    """Verify an 'Authorization: Bearer <jwt>' header against Okta.

    Returns the decoded claims on success; raises AuthError otherwise.
    """
    if os.environ.get("VERIFY_OKTA_TOKEN", "0") != "1":
        # Trusting APIM's edge validation; no-op.
        return {}

    try:
        from jose import jwt  # python-jose
    except ImportError as e:  # pragma: no cover
        raise AuthError("python-jose not installed; pip install python-jose") from e

    if not authorization_header or not authorization_header.lower().startswith("bearer "):
        raise AuthError("Missing bearer token")
    token = authorization_header.split(" ", 1)[1].strip()

    issuer = os.environ["OKTA_ISSUER"]
    audience = os.environ["OKTA_AUDIENCE"]
    cfg = _openid_config(issuer)
    jwks = _jwks(cfg["jwks_uri"], int(time.time()) // 3600)

    try:
        claims = jwt.decode(
            token,
            jwks,
            audience=audience,
            issuer=issuer,
            options={"verify_at_hash": False},
        )
    except Exception as e:
        raise AuthError(f"Token validation failed: {e}") from e

    scopes = claims.get("scp") or claims.get("scope", "").split()
    if REQUIRED_SCOPE not in scopes:
        raise AuthError(f"Token missing required scope: {REQUIRED_SCOPE}")

    return claims
