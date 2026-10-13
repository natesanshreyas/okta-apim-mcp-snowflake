# Claude Desktop setup — connect to the MCP endpoint through APIM + Okta

This is where the **user configures the MCP endpoint and authentication**. Claude
Desktop signs the user in through Okta (OAuth 2.0 / OIDC, Authorization Code +
PKCE), caches the resulting **access token**, and attaches it as a Bearer token on
every MCP call to the APIM gateway.

## 1. Locate the Claude Desktop config file

| OS | Path |
|---|---|
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| Linux | `~/.config/Claude/claude_desktop_config.json` |

(Open it from the app: **Settings → Developer → Edit Config**.)

## 2. Copy the example config and fill in your values

Use [`../claude-desktop/config-example.json`](../claude-desktop/config-example.json).
It contains two options:

### Option A — native remote MCP server with OAuth (newer Claude Desktop)

Claude Desktop connects directly to the APIM HTTPS MCP endpoint and runs the Okta
OAuth flow itself. Fill in:

- `url`: `https://<YOUR_APIM_GATEWAY_HOST>/mcp-snowflake/mcp`
- `oauth.issuer` / `authorizationUrl` / `tokenUrl`: your Okta authz server endpoints
- `oauth.clientId`: your Okta **public** client ID (`OKTA_CLIENT_ID`)
- `oauth.scopes`: must include `snowflake.query`

### Option B — local OAuth bridge (`mcp-remote`)

If your Claude Desktop build does not yet support remote OAuth MCP servers, use the
`mcp-remote` stdio bridge (requires Node.js). It performs the Okta OAuth flow and
proxies to the remote APIM HTTPS endpoint. Fill in the same APIM URL, Okta authz
server, client ID, and scopes in the `args`.

## 3. Restart Claude Desktop and sign in

1. Fully quit and relaunch Claude Desktop.
2. The `snowflake-via-apim` server should appear. On first use Claude Desktop opens
   a browser to Okta; sign in and consent to `snowflake.query`.
3. Okta returns an access token; Claude Desktop caches it and attaches
   `Authorization: Bearer <token>` to MCP calls hitting APIM.

## 4. Use it

Ask Claude something that needs the data, e.g.:

> "List the Snowflake tables, then tell me which region has the most customers."

Claude will call the MCP tools (`snowflake_list_tables`, `snowflake_describe`,
`snowflake_query`). Every call flows through APIM, which validates the Okta token
before the MCP server/Snowflake are touched.

## What the user is actually configuring

| Field | Meaning |
|---|---|
| `url` | **The MCP endpoint** — the APIM gateway URL for this API |
| `oauth.*` | **Authentication** — the Okta authorization server + public client |
| `scopes` | Must include `snowflake.query` so APIM allows the call |

No API key or password is stored in the config — only public identifiers (client
ID, URLs). The sensitive credential is the short-lived Okta access token, which
Claude Desktop obtains at runtime and never persists in the config file.

## Troubleshooting

- **401 from APIM**: token missing/expired, wrong audience, or missing
  `snowflake.query` scope. Re-check the Okta access policy/rule and the APIM
  named values (`OKTA_ISSUER`, `OKTA_AUDIENCE`).
- **Browser never opens / redirect fails**: confirm the redirect URI in the Okta
  app matches what the client uses (e.g. `http://localhost:53682/callback`).
- **Server not listed**: JSON syntax error in the config, or Claude Desktop needs a
  full restart.
- **429**: per-user rate limit (60/min) — expected governance behavior.
