"""
OAuth 2.0 On-Behalf-Of (RFC 8693 token exchange) against Okta.

The agent service is a CONFIDENTIAL Okta client. For each downstream call to the
MCP API it exchanges the end user's access token (subject_token) for a NEW token
scoped to the MCP API (audience api://mcp-snowflake, scope snowflake.query). The
new token still carries the original user's identity (sub/email), so end-user
authorization and audit are preserved all the way to Snowflake.

Env:
  OKTA_ISSUER              https://<org>.okta.com/oauth2/<authz-server-id>
  OKTA_AGENT_CLIENT_ID     confidential client id of the agent service
  OKTA_AGENT_CLIENT_SECRET confidential client secret (source from Key Vault)
  OKTA_MCP_AUDIENCE        api://mcp-snowflake
"""

import os
import time

import httpx

_TOKEN_EXCHANGE = "urn:ietf:params:oauth:grant-type:token-exchange"
_ACCESS_TOKEN_TYPE = "urn:ietf:params:oauth:token-type:access_token"

# Small in-process cache so we don't hit Okta on every tool call for the same user.
_cache: dict[str, tuple[str, float]] = {}


async def exchange_for_mcp_token(user_token: str) -> str:
    """Exchange a user access token for an MCP-scoped token via Okta OBO.

    Returns the downstream access token string.
    """
    issuer = os.environ["OKTA_ISSUER"].rstrip("/")
    client_id = os.environ["OKTA_AGENT_CLIENT_ID"]
    client_secret = os.environ["OKTA_AGENT_CLIENT_SECRET"]
    audience = os.environ.get("OKTA_MCP_AUDIENCE", "api://mcp-snowflake")
    scope = os.environ.get("OKTA_MCP_SCOPE", "snowflake.query")

    cache_key = f"{hash(user_token)}:{audience}:{scope}"
    cached = _cache.get(cache_key)
    if cached and cached[1] > time.time() + 30:
        return cached[0]

    data = {
        "grant_type": _TOKEN_EXCHANGE,
        "subject_token": user_token,
        "subject_token_type": _ACCESS_TOKEN_TYPE,
        "requested_token_type": _ACCESS_TOKEN_TYPE,
        "audience": audience,
        "scope": scope,
    }

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{issuer}/v1/token",
            data=data,
            auth=(client_id, client_secret),  # confidential client auth
            headers={"Accept": "application/json"},
        )
    if resp.status_code != 200:
        raise RuntimeError(
            f"OBO token exchange failed ({resp.status_code}): {resp.text}"
        )
    body = resp.json()
    token = body["access_token"]
    expires_in = int(body.get("expires_in", 300))
    _cache[cache_key] = (token, time.time() + expires_in)
    return token
