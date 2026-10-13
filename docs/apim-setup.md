# APIM setup — add the MCP API to your EXISTING APIM instance

This POC does **not** provision a new APIM. It adds a new API + policy onto an
APIM instance you already run, so APIM becomes the centralized security and
governance gateway for the MCP/Snowflake capability.

What gets added:

- A new API (path suffix `mcp-snowflake`) imported from [`openapi.yaml`](openapi.yaml).
- Named values: `OKTA_ISSUER`, `OKTA_AUDIENCE`, `OKTA_JWKS_URI`, `MCP_BACKEND_URL`.
- The inbound/outbound policy [`policy/mcp-snowflake.xml`](policy/mcp-snowflake.xml)
  that validates the Okta JWT, rate-limits per user, strips the caller token, and
  emits telemetry.

## Prerequisites

- `az` CLI logged into the subscription that owns your APIM.
- Your existing APIM resource group + name.
- The Okta values from [`okta-setup.md`](okta-setup.md).
- A reachable MCP backend URL (local tunnel for demo, or a deployed MCP server).

## Steps

```bash
# From the repo root
export APIM_RG=<your-apim-resource-group>
export APIM_NAME=<your-existing-apim-name>

export OKTA_ISSUER=https://example.okta.com/oauth2/aus1a2b3c4d5e6f7g8h9
export OKTA_AUDIENCE=api://mcp-snowflake
export OKTA_JWKS_URI=$OKTA_ISSUER/v1/keys
export MCP_BACKEND_URL=https://<your-mcp-server-host>/mcp

# 1. Create/refresh the named values the policy references
./scripts/01-set-named-values.sh

# 2. Import the OpenAPI as a new API named "mcp-snowflake"
./scripts/02-import-api-into-existing-apim.sh

# 3. Attach the JWT-validation + governance policy to that API
./scripts/03-apply-policy.sh
```

## What the policy enforces (summary)

1. **`validate-jwt`** against Okta's OIDC metadata/JWKS — rejects missing, expired,
   wrong-issuer, wrong-audience, or unsigned tokens with **401** before any backend
   call.
2. **`required-claims`** — the token must carry scope `snowflake.query` in `scp`.
3. **`rate-limit-by-key`** keyed on the Okta `sub` — 60 req/min/user.
4. **Token stripping** — the caller's Okta bearer is deleted before forwarding; APIM
   authenticates to the backend via managed identity (preferred) so the user token
   never reaches the backend.
5. **Telemetry** — inbound/outbound traces carry `user-sub`, `user-email`,
   `status-code`, `elapsed-ms` for per-user governance/FinOps KQL.

## Backend authentication options

The commented `authentication-managed-identity` block in the policy is the
recommended way for APIM to authenticate to an Entra-protected MCP backend
(Container App / App Service). Set `resource` to the backend app's Application ID
URI and grant APIM's managed identity access. If instead your MCP backend trusts
the network boundary (private VNet), you can omit backend auth — but never forward
the user's Okta token downstream.

## Testing through APIM

```bash
# Obtain an Okta access token (Auth Code + PKCE) first — see okta-setup.md.
export TOKEN=<okta_access_token>

# MCP initialize call through APIM (should 200 with a valid token, 401 without)
curl -i -X POST "https://$APIM_NAME.azure-api.net/mcp-snowflake/mcp" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"curl","version":"1"}}}'

# Negative test: no token -> expect HTTP 401 from APIM, backend never reached
curl -i -X POST "https://$APIM_NAME.azure-api.net/mcp-snowflake/mcp" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}'
```

## Notes on MCP over APIM

MCP's Streamable HTTP transport is a single POST endpoint carrying JSON-RPC, with
optional SSE responses. APIM proxies it transparently. If you enable response
buffering globally, ensure SSE/streamed responses are allowed to pass through for
tools that stream. For most request/response tool calls (like these Snowflake
queries) standard proxying is sufficient.
