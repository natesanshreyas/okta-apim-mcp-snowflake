# Architecture — Pattern B (Azure-hosted model is the agent)

This POC implements **Pattern B**: the enterprise's **Azure-hosted LLM is the
agent** that selects which MCP tools to call. Azure API Management is the
centralized security/governance gateway on **both** hops, Okta is the identity
provider, and the end user's identity is preserved all the way to Snowflake via
OAuth **On-Behalf-Of (OBO)** token exchange.

Why not use Claude Desktop's own model to pick tools? Because you want *your*
governed Azure model doing the reasoning and tool selection, with APIM policing
every hop — not a vendor model in someone else's cloud.

## Components

| # | Component | Role | Identity it holds |
|---|-----------|------|-------------------|
| 1 | Chat client (Claude Desktop custom connector, web UI, or CLI) | Signs the user in, sends the prompt | Okta **public** client (PKCE) |
| 2 | APIM — **Agent API** (`/agent/chat`) | Validates user JWT, rate-limits, routes to agent | — (validates `aud=api://agent`) |
| 3 | **Agent service** (Azure Container App / Foundry Agent Service) | The orchestrator: runs the tool-calling loop, does OBO | Okta **confidential** client |
| 4 | **Azure OpenAI** model | Reasoning + tool *selection* (returns tool calls, does not execute) | Agent's AAD identity / key |
| 5 | APIM — **MCP API** (`/mcp-snowflake/mcp`) | Validates the OBO JWT, routes to MCP server | — (validates `aud=api://mcp-snowflake`) |
| 6 | **MCP server** (FastMCP) | Exposes `snowflake_*` tools | Snowflake key-pair |
| 7 | **Snowflake** | Executes read-only SQL | per-user role (via query tag) |

The MCP server has **no model** — it only exposes tools. All tool *selection*
happens in component 4 (the Azure model), driven by component 3 (the agent).

## End-to-end sequence

```
 User            Chat client        APIM:/agent     Agent service      Azure OpenAI     APIM:/mcp      MCP server     Snowflake
  │  sign in (Okta PKCE)  │               │               │                 │               │              │             │
  │──────────────────────►│               │               │                 │               │              │             │
  │   access_token (aud=api://agent, scope=agent.invoke)   │                 │               │              │             │
  │                       │                               │                 │               │              │             │
  │  "which region has most customers?"                   │                 │               │              │             │
  │──────────────────────►│  POST /agent/chat  +Bearer    │                 │               │              │             │
  │                       │──────────────►│ validate-jwt  │                 │               │              │             │
  │                       │               │──────────────►│                 │               │              │             │
  │                       │               │               │ chat.completions (tools advertised)             │             │
  │                       │               │               │────────────────►│               │              │             │
  │                       │               │               │  tool_call: snowflake_query(sql) │              │             │
  │                       │               │               │◄────────────────│               │              │             │
  │                       │               │               │ OBO token exchange (user_token → mcp_token)      │             │
  │                       │               │               │────────────────►│ (Okta /token, grant=token-exchange)         │
  │                       │               │               │  mcp_token (aud=api://mcp-snowflake, scope=snowflake.query)    │
  │                       │               │               │◄────────────────│               │              │             │
  │                       │               │               │ tools/call  +Bearer mcp_token   │              │             │
  │                       │               │               │────────────────────────────────►│ validate-jwt │             │
  │                       │               │               │                 │               │─────────────►│  SELECT ... │
  │                       │               │               │                 │               │              │────────────►│
  │                       │               │               │                 │               │   rows       │◄────────────│
  │                       │               │               │ tool result ◄───────────────────│◄─────────────│             │
  │                       │               │               │ chat.completions (+tool result) │               │             │
  │                       │               │               │────────────────►│  final answer │               │             │
  │                       │               │  answer ◄──────│◄────────────────│               │               │             │
  │   answer ◄────────────│◄──────────────│               │                 │               │               │             │
```

## Identity & token model

Three OAuth identities, no static API keys in the request path:

1. **Chat client → Agent API** — user token.
   `aud=api://agent`, `scope=agent.invoke`. Obtained by the public PKCE client.
2. **Agent → MCP API** — OBO/delegated token.
   The agent is a *confidential* Okta client. On each tool call it performs
   **OAuth 2.0 Token Exchange (RFC 8693)** at Okta's `/token` endpoint:
   `grant_type=urn:ietf:params:oauth:grant-type:token-exchange`,
   `subject_token=<user token>`, `audience=api://mcp-snowflake`,
   `scope=snowflake.query`. Okta returns a new token that still carries the
   original user's `sub`/`email`. This is what preserves end-user identity to the
   backend.
3. **Agent → Azure OpenAI** — the agent's own AAD identity (managed identity) or
   an Azure OpenAI key from Key Vault. This is the model-inference credential, not
   part of the user-delegation chain.

APIM validates a JWT at **both** the `/agent` and `/mcp-snowflake` entry points,
so the model→MCP hop is independently authorized — defense in depth, zero implicit
trust between tiers.

## Where governance is enforced

| Control | Agent API hop | MCP API hop |
|---|---|---|
| Okta JWT validation | ✅ `aud=api://agent`, `scope=agent.invoke` | ✅ `aud=api://mcp-snowflake`, `scope=snowflake.query` |
| Per-user rate limit (`sub`) | ✅ | ✅ |
| Telemetry (user, latency, status) | ✅ | ✅ |
| End-user identity to Snowflake | — | ✅ via OBO `sub` → `QUERY_TAG` |

## Deployment shape

```
                    Okta (authz server: api://agent, api://mcp-snowflake)
                      ▲            ▲                        ▲
          PKCE user   │   OBO exchange (confidential)      │ JWKS (both APIM policies)
                      │            │                        │
  Chat client ──► APIM /agent ──► Agent service ──► APIM /mcp-snowflake ──► MCP server ──► Snowflake
                      │                │  └─► Azure OpenAI (reasoning)
                      └──── same APIM instance, two protected APIs ────┘
```

Both APIM APIs live on your **existing** APIM instance. The agent service and MCP
server are deployed as Azure Container Apps (or App Service/AKS) with managed
identity and Key Vault–sourced secrets.

## Relationship to Claude Desktop (Pattern A)

Claude Desktop's native MCP connector (Pattern A) is still documented in
`docs/claude-desktop-setup.md` for completeness, but in that mode **Anthropic's
model** does tool selection and the Azure model is bypassed. For this enterprise
design we use Pattern B; a chat client only plays the role of component 1 (sign-in
+ prompt), and all reasoning/tool-selection is done by the Azure model via the
agent service.
