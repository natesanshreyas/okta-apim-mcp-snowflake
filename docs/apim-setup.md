# APIM setup — add the Agent + MCP APIs to your EXISTING APIM instance

This POC does **not** provision a new APIM. It adds **two** new APIs + policies onto
an APIM instance you already run, so APIM becomes the centralized security and
governance gateway for Pattern B (the Azure model is the agent).

What gets added:

- **Agent API** — path suffix `agent`, from [`agent-openapi.yaml`](agent-openapi.yaml),
  policy [`policy/agent-api.xml`](policy/agent-api.xml). Validates the user token
  (`aud=api://agent`, scope `agent.invoke`) and routes to the agent service.
- **MCP API** — path suffix `mcp-snowflake`, from [`openapi.yaml`](openapi.yaml),
  policy [`policy/mcp-snowflake.xml`](policy/mcp-snowflake.xml). Validates the OBO
  token (`aud=api://mcp-snowflake`, scope `snowflake.query`) and routes to the MCP
  server.
- Named values: `OKTA_ISSUER`, `OKTA_AUDIENCE`, `OKTA_AGENT_AUDIENCE`,
  `OKTA_JWKS_URI`, `MCP_BACKEND_URL`, `AGENT_BACKEND_URL`.

## Prerequisites

- `az` CLI logged into the subscription that owns your APIM.
- Your existing APIM resource group + name.
- The Okta values from [`okta-setup.md`](okta-setup.md).
- Reachable agent-service and MCP-server backend URLs (tunnel for demo, or deployed).

## Steps

```bash
# From the repo root
export APIM_RG=<your-apim-resource-group>
export APIM_NAME=<your-existing-apim-name>

export OKTA_ISSUER=https://example.okta.com/oauth2/aus1a2b3c4d5e6f7g8h9
export OKTA_AUDIENCE=api://mcp-snowflake
export OKTA_AGENT_AUDIENCE=api://agent
export OKTA_JWKS_URI=$OKTA_ISSUER/v1/keys
export MCP_BACKEND_URL=https://<your-mcp-server-host>/mcp
export AGENT_BACKEND_URL=https://<your-agent-service-host>/agent

# 1. Create/refresh the named values both policies reference
./scripts/01-set-named-values.sh

# 2. Import + policy the AGENT API
API_ID=agent API_PATH=agent SPEC=apim/agent-openapi.yaml \
  DISPLAY="MCP Snowflake Agent" ./scripts/02-import-api-into-existing-apim.sh
API_ID=agent POLICY=apim/policy/agent-api.xml ./scripts/03-apply-policy.sh

# 3. Import + policy the MCP API
API_ID=mcp-snowflake API_PATH=mcp-snowflake SPEC=apim/openapi.yaml \
  DISPLAY="MCP Snowflake Gateway" ./scripts/02-import-api-into-existing-apim.sh
API_ID=mcp-snowflake POLICY=apim/policy/mcp-snowflake.xml ./scripts/03-apply-policy.sh
```

## What the policies enforce (summary)

Both policies run `validate-jwt` against Okta's OIDC metadata/JWKS and reject
missing/expired/wrong-issuer/wrong-audience/unsigned tokens with **401** before any
backend call. The Agent API requires `aud=api://agent` + scope `agent.invoke`; the
MCP API requires `aud=api://mcp-snowflake` + scope `snowflake.query` (the audience the
agent's OBO exchange mints).
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
