# Okta → APIM → Azure model (agent) → MCP → Snowflake (Proof of Concept)

A reference proof-of-concept showing how an enterprise can let a user reach an
**MCP-based Snowflake capability** while **Azure API Management (APIM)** acts as the
centralized security and governance gateway, with **Okta** (OAuth 2.0 / OIDC) as the
identity provider — and the enterprise's **own Azure-hosted model as the agent** that
selects which MCP tools to call (**Pattern B**).

No static API keys are used anywhere in the request path. The user authenticates
through Okta; APIM validates the JWT (against Okta's JWKS) at **every hop** before any
backend is reached; and the end user's identity is carried all the way to Snowflake
via OAuth **On-Behalf-Of (OBO)** token exchange.

> **Full design walk-through:** [`docs/architecture.md`](docs/architecture.md).

## Architecture (Pattern B — the Azure model is the agent)

```
  +--------------+  1. OAuth2/OIDC (Auth Code + PKCE)   +------------------+
  | Chat client  | -----------------------------------> |  Okta            |
  | (UI / Claude |  <--- user access_token (aud=agent)  |  Authorization   |
  |  Desktop/CLI)|                                       |  Server          |
  +------+-------+                                       +------------------+
         | 2. POST /agent/chat  (Bearer user_token)              ^  OBO token
         v                                                       |  exchange
  +---------------------------------------------------+          |  (RFC 8693)
  | APIM - Agent API                                  |          |
  |   validate-jwt (aud=api://agent, scp=agent.invoke)|          |
  +---------------+-----------------------------------+          |
                  | 3. route to agent service                    |
                  v                                              |
  +---------------------------------------------------+          |
  | Agent service (Azure Container App / Foundry)     |----------+
  |   - calls Azure OpenAI  -> model SELECTS the tool |
  |   - OBO: user_token -> mcp_token (aud=mcp-...)    |
  +------+----------------------------+---------------+
         | 3a. reasoning              | 4. POST /mcp (Bearer mcp_token)
         v                            v
  +-------------------------+  +-------------------------------------------+
  | Azure OpenAI / Foundry  |  | APIM - MCP API                           |
  | (reasoning, tool-select)|  |  validate-jwt (aud=api://mcp-snowflake,  |
  +-------------------------+  |               scp=snowflake.query)       |
                              +---------------+---------------------------+
                                              | 5. route to MCP server
                                              v
                              +-------------------------------------------+
                              | MCP Server (FastMCP, Python)             |
                              |  snowflake_query / describe / list_tables|
                              +---------------+---------------------------+
                                              | 6. SQL (key-pair auth)
                                              v
                              +-------------------------------------------+
                              | Snowflake  (warehouse + db + schema)     |
                              +-------------------------------------------+
```

Both APIM APIs (`/agent` and `/mcp-snowflake`) live on your **existing** APIM
instance. The MCP server has no model — it only exposes tools; the Azure model does
all tool *selection*. Claude Desktop's native MCP connector (where Anthropic's model
would pick tools) is documented as an **alternative (Pattern A)** only.

## How the pieces map to the goal

| Requirement | Where it lives |
|---|---|
| Full Pattern B design | [`docs/architecture.md`](docs/architecture.md) |
| Okta OAuth2/OIDC, access tokens (not API keys), OBO | [`docs/okta-setup.md`](docs/okta-setup.md) |
| APIM validates JWT at the **agent** hop | [`apim/policy/agent-api.xml`](apim/policy/agent-api.xml) |
| APIM validates JWT at the **MCP** hop | [`apim/policy/mcp-snowflake.xml`](apim/policy/mcp-snowflake.xml) |
| Build into an **existing** APIM (both APIs) | [`apim/agent-openapi.yaml`](apim/agent-openapi.yaml), [`apim/openapi.yaml`](apim/openapi.yaml) + [`scripts/02-import-api-into-existing-apim.sh`](scripts/02-import-api-into-existing-apim.sh) |
| Azure model is the agent (reasoning + tool select) | [`llm-agent/agent_core.py`](llm-agent/agent_core.py), [`llm-agent/service.py`](llm-agent/service.py) |
| OBO token exchange (end-user identity → MCP) | [`llm-agent/obo.py`](llm-agent/obo.py) |
| MCP server exposing Snowflake | [`mcp-server/`](mcp-server) |
| Snowflake backend (mockable for local demo) | [`mcp-server/snowflake_client.py`](mcp-server/snowflake_client.py) + [`mock-snowflake/`](mock-snowflake) |
| Chat client sign-in + prompt (alt Pattern A) | [`claude-desktop/config-example.json`](claude-desktop/config-example.json) + [`docs/claude-desktop-setup.md`](docs/claude-desktop-setup.md) |

## Request flow in one paragraph

The chat client signs the user into Okta (Auth Code + PKCE) and gets an access token
for `api://agent`. It calls **APIM `/agent/chat`**, which validates the token and
routes to the **agent service**. The agent asks **Azure OpenAI** what to do; the model
replies "call `snowflake_query(...)`" — this is where tool *selection* happens. The
agent then performs an **OBO token exchange** at Okta, swapping the user token for one
scoped to `api://mcp-snowflake`, and calls **APIM `/mcp-snowflake/mcp`** with it. APIM
validates that token too, routes to the **MCP server**, which runs the query against
**Snowflake** (key-pair auth) and returns rows. The model composes the final answer.

## Quick start (local demo, mock Snowflake)

The local demo runs the MCP server and a mock Snowflake backend so you can exercise
the MCP tool flow without a Snowflake account (Okta/APIM are bypassed locally).

```bash
cd mcp-server
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export SNOWFLAKE_MODE=mock
python server.py          # MCP endpoint: http://localhost:8080/mcp

# in a second shell
cd mcp-server && source .venv/bin/activate
python ../scripts/local_mcp_smoke.py
```

### Run the agent service locally (Pattern B)

```bash
cd llm-agent
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# set Okta + Azure OpenAI + MCP_ENDPOINT env (see .env.example)
uvicorn service:app --host 0.0.0.0 --port 8081
# POST a question:
curl -s localhost:8081/agent/chat -H "Authorization: Bearer $OKTA_ACCESS_TOKEN" \
     -H 'Content-Type: application/json' \
     -d '{"question":"Which region has the most customers?"}'
```

## "Real" path (Okta + existing APIM)

1. **Okta** — create the authorization server, the `api://agent` + `api://mcp-snowflake`
   audiences, the `agent.invoke` + `snowflake.query` scopes, a **public** PKCE client
   (chat) and a **confidential** client (agent, for OBO). See
   [`docs/okta-setup.md`](docs/okta-setup.md).
2. **APIM** — import **both** APIs into your existing instance and attach policies:
   ```bash
   export APIM_RG=<rg> APIM_NAME=<existing-apim>
   export OKTA_ISSUER=https://<org>.okta.com/oauth2/<authz-server-id>
   export OKTA_AUDIENCE=api://mcp-snowflake OKTA_AGENT_AUDIENCE=api://agent
   export MCP_BACKEND_URL=https://<mcp-host>/mcp
   export AGENT_BACKEND_URL=https://<agent-host>/agent
   ./scripts/01-set-named-values.sh

   API_ID=agent API_PATH=agent SPEC=apim/agent-openapi.yaml \
     DISPLAY="MCP Snowflake Agent" ./scripts/02-import-api-into-existing-apim.sh
   API_ID=agent POLICY=apim/policy/agent-api.xml ./scripts/03-apply-policy.sh

   API_ID=mcp-snowflake API_PATH=mcp-snowflake SPEC=apim/openapi.yaml \
     DISPLAY="MCP Snowflake Gateway" ./scripts/02-import-api-into-existing-apim.sh
   API_ID=mcp-snowflake POLICY=apim/policy/mcp-snowflake.xml ./scripts/03-apply-policy.sh
   ```
3. **Deploy** the agent service and MCP server (Container Apps / App Service / AKS)
   with managed identity + Key Vault for secrets. Point `MCP_ENDPOINT` at the APIM
   MCP API, and `AGENT_BACKEND_URL` / `MCP_BACKEND_URL` at the deployed services.

## Security posture

- **No static API keys in the request path.** Okta access tokens authenticate the
  user to APIM; OBO mints a delegated token for the MCP hop; the agent authenticates
  to Azure OpenAI with its own managed identity.
- **JWT validated at the edge on BOTH hops.** `/agent` requires `agent.invoke`;
  `/mcp-snowflake` requires `snowflake.query`. Zero implicit trust between tiers.
- **End-user identity preserved to Snowflake** via OBO (`sub` → Snowflake `QUERY_TAG`).
- **Least privilege to Snowflake** (scoped role + key-pair auth).
- **No secrets committed.** See [`.env.example`](.env.example) and [`.gitignore`](.gitignore).

## Repository layout

```
okta-apim-mcp-snowflake/
├── README.md
├── .env.example / .gitignore
├── apim/
│   ├── agent-openapi.yaml           # Agent (front door) API surface
│   ├── openapi.yaml                 # MCP tool API surface
│   └── policy/
│       ├── agent-api.xml            # validate-jwt (aud=api://agent) + telemetry
│       └── mcp-snowflake.xml        # validate-jwt (aud=api://mcp-snowflake)
├── llm-agent/
│   ├── agent_core.py                # reasoning loop: model selects + calls MCP tools
│   ├── obo.py                       # Okta OBO (RFC 8693) token exchange
│   ├── service.py                   # FastAPI agent service (APIM backend)
│   └── requirements.txt
├── mcp-server/
│   ├── server.py                    # FastMCP server exposing Snowflake tools
│   ├── snowflake_client.py          # real (key-pair) + mock backends
│   ├── auth.py                      # optional defense-in-depth token check
│   └── requirements.txt
├── mock-snowflake/seed.sql          # sample data the mock backend serves
├── scripts/
│   ├── 01-set-named-values.sh
│   ├── 02-import-api-into-existing-apim.sh   # run once per API
│   ├── 03-apply-policy.sh                     # run once per API
│   └── local_mcp_smoke.py
├── claude-desktop/config-example.json         # alternative Pattern A front-end
└── docs/
    ├── architecture.md              # Pattern B design (read this first)
    ├── okta-setup.md
    ├── apim-setup.md
    ├── claude-desktop-setup.md
    └── snowflake-setup.md
```

## Disclaimer

This is a demonstration POC. Review and harden (private networking, Key Vault, WAF,
token binding, Snowflake network policies, audit retention) before any production use.
MCP client schemas and remote-MCP OAuth support evolve quickly — verify against current
Anthropic/Azure docs before fleet rollout.
