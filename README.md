# Okta → APIM → Azure LLM → MCP → Snowflake (Proof of Concept)

A reference proof-of-concept showing how an enterprise can let a user in **Claude
Desktop** reach an **MCP-based Snowflake capability** while **Azure API Management
(APIM)** acts as the centralized security and governance gateway, with **Okta**
(OAuth 2.0 / OIDC) as the identity provider.

No static API keys are used anywhere in the request path. The user authenticates
through Okta, Claude Desktop obtains an OAuth access token, and that token is
validated by APIM (JWT validation against Okta's JWKS) before any backend is
reached.

## Architecture

```
  ┌──────────────┐   1. OAuth2 / OIDC (Auth Code + PKCE)   ┌──────────────────┐
  │              │ ─────────────────────────────────────► │                  │
  │ Claude       │                                          │  Okta            │
  │ Desktop      │ ◄───────── access_token (JWT) ────────── │  Authorization   │
  │ (MCP client) │                                          │  Server          │
  └──────┬───────┘                                          └──────────────────┘
         │ 2. MCP calls (Streamable HTTP)
         │    Authorization: Bearer <okta_access_token>
         ▼
  ┌───────────────────────────────────────────────────────────────────────────┐
  │ Azure API Management  (centralized security + governance gateway)           │
  │   • validate-jwt against Okta JWKS   • require scope: snowflake.query       │
  │   • rate-limit per user (sub claim)  • emit per-user telemetry              │
  │   • strip caller token, auth to backend with managed identity / named value │
  └───────────────┬───────────────────────────────────────────┬────────────────┘
                  │ 3a. MCP tool traffic                        │ 3b. LLM traffic
                  ▼                                             ▼
  ┌──────────────────────────────┐              ┌──────────────────────────────┐
  │ MCP Server (FastMCP, Python) │              │ Azure-hosted LLM endpoint     │
  │   tool: snowflake_query      │              │ (Azure OpenAI / Foundry)      │
  │   tool: snowflake_describe   │              │ the "agent" that decides to   │
  └───────────────┬──────────────┘              │ call the MCP Snowflake tool   │
                  │ 4. SQL over Snowflake        └──────────────────────────────┘
                  ▼    connector (key-pair / OAuth, never static pw in path)
  ┌──────────────────────────────┐
  │ Snowflake                    │
  │   warehouse + db + schema    │
  └──────────────────────────────┘
```

## How the pieces map to the goal

| Requirement | Where it lives |
|---|---|
| Claude Desktop connects to MCP endpoint | [`claude-desktop/config-example.json`](claude-desktop/config-example.json) + [`docs/claude-desktop-setup.md`](docs/claude-desktop-setup.md) |
| Okta OAuth2/OIDC, access tokens (not API keys) | [`docs/okta-setup.md`](docs/okta-setup.md) |
| APIM validates JWT before backend | [`apim/policy/mcp-snowflake.xml`](apim/policy/mcp-snowflake.xml) |
| Build into an **existing** APIM instance | [`apim/openapi.yaml`](apim/openapi.yaml) + [`scripts/02-import-api-into-existing-apim.sh`](scripts/02-import-api-into-existing-apim.sh) |
| Azure-hosted LLM drives the MCP tool | [`llm-agent/`](llm-agent) |
| MCP server exposing Snowflake | [`mcp-server/`](mcp-server) |
| Snowflake backend (mockable for local demo) | [`mcp-server/snowflake_client.py`](mcp-server/snowflake_client.py) + [`mock-snowflake/`](mock-snowflake) |

## Quick start (local demo, mock Snowflake)

The local demo runs the MCP server and a mock Snowflake backend on your machine so
you can exercise the full MCP tool flow without a Snowflake account. APIM and Okta
are configured per the docs and are exercised in the "real" path.

```bash
# 1. Python env
cd mcp-server
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Point the MCP server at the mock Snowflake backend
export SNOWFLAKE_MODE=mock

# 3. Run the MCP server (Streamable HTTP on :8080)
python server.py
# -> MCP endpoint: http://localhost:8080/mcp

# 4. (new shell) exercise the tool through the local client harness
cd mcp-server && source .venv/bin/activate
python ../scripts/local_mcp_smoke.py
```

## "Real" path (Okta + existing APIM)

1. **Okta** — create an API Services / OIDC app + authorization server + a
   `snowflake.query` scope. See [`docs/okta-setup.md`](docs/okta-setup.md).
2. **APIM** — import the MCP API into your **existing** APIM instance and attach
   the JWT-validation policy:
   ```bash
   export APIM_RG=<your-rg> APIM_NAME=<your-existing-apim>
   export OKTA_ISSUER=https://<your-okta-domain>/oauth2/<authz-server-id>
   export OKTA_AUDIENCE=api://mcp-snowflake
   export MCP_BACKEND_URL=https://<your-mcp-server-host>/mcp
   ./scripts/01-set-named-values.sh
   ./scripts/02-import-api-into-existing-apim.sh
   ./scripts/03-apply-policy.sh
   ```
3. **Claude Desktop** — point it at the APIM MCP endpoint and the Okta app. See
   [`docs/claude-desktop-setup.md`](docs/claude-desktop-setup.md).
4. **Deploy the MCP server** behind APIM (Container Apps / App Service / AKS) with
   `SNOWFLAKE_MODE=real` and Snowflake key-pair credentials from Key Vault.

## Security posture

- **No static API keys in the request path.** Okta access tokens (JWT) authenticate
  the user to APIM; APIM authenticates to the backend via managed identity or an
  injected named value, never a client-held key.
- **JWT validated at the edge.** APIM rejects anything lacking a valid Okta token
  and the required `snowflake.query` scope (HTTP 401) before the backend is touched.
- **Least privilege to Snowflake.** The MCP server connects with a scoped role and
  key-pair auth; see [`docs/snowflake-setup.md`](docs/snowflake-setup.md).
- **No secrets committed.** All credentials come from env vars / Key Vault; see
  [`.env.example`](.env.example) and [`.gitignore`](.gitignore).

## Repository layout

```
okta-apim-mcp-snowflake/
├── README.md
├── .env.example
├── .gitignore
├── claude-desktop/
│   └── config-example.json         # Claude Desktop MCP + OAuth config
├── apim/
│   ├── openapi.yaml                # MCP API surface imported into existing APIM
│   └── policy/
│       └── mcp-snowflake.xml       # validate-jwt (Okta) + rate-limit + telemetry
├── mcp-server/
│   ├── server.py                   # FastMCP server exposing Snowflake tools
│   ├── snowflake_client.py         # real (key-pair) + mock backends
│   ├── auth.py                     # optional defense-in-depth token check
│   └── requirements.txt
├── llm-agent/
│   ├── agent.py                    # Azure OpenAI/Foundry agent that calls MCP tool
│   └── requirements.txt
├── mock-snowflake/
│   └── seed.sql                    # sample data the mock backend serves
├── scripts/
│   ├── 01-set-named-values.sh
│   ├── 02-import-api-into-existing-apim.sh
│   ├── 03-apply-policy.sh
│   └── local_mcp_smoke.py
└── docs/
    ├── okta-setup.md
    ├── apim-setup.md
    ├── claude-desktop-setup.md
    └── snowflake-setup.md
```

## Disclaimer

This is a demonstration POC. Review and harden (private networking, Key Vault,
WAF, token binding, Snowflake network policies, audit retention) before any
production use. MCP client config schemas and Claude Desktop remote-MCP OAuth
support evolve quickly — verify against current Anthropic docs before fleet rollout.
