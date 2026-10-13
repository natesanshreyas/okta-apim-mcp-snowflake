# Okta setup (OAuth 2.0 / OIDC) for the MCP → APIM demo

This configures Okta as the identity provider so Claude Desktop can obtain an
**OAuth access token** (not a static API key) that Azure API Management validates
before the MCP/Snowflake backend is reached.

You will create three things in Okta:

1. A **public OIDC application** (the client Claude Desktop uses).
2. A **custom Authorization Server** that mints access tokens for your API.
3. A **scope** (`snowflake.query`) and an **audience** APIM checks.

> You need an Okta org with API Access Management (custom authorization servers).
> Admin console: `https://<your-org>-admin.okta.com`.

---

## 1. Create the OIDC application (public client + PKCE)

Admin Console → **Applications → Applications → Create App Integration**

- Sign-in method: **OIDC - OpenID Connect**
- Application type: **Native Application** (public client; uses PKCE, no secret)
- App name: `Claude Desktop - MCP Snowflake`
- Grant types: **Authorization Code** + **Refresh Token**
- Sign-in redirect URIs (add the ones your client uses):
  - `http://localhost:53682/callback` (native loopback used by many MCP OAuth helpers)
  - `com.anthropic.claude://oauth/callback` (if Claude Desktop registers a custom scheme)
  - Add any additional loopback ports your `mcp-remote` bridge prints at runtime.
- Controlled access: assign to the demo users/group.

After creation note the **Client ID** → this is `OKTA_CLIENT_ID`. There is **no
client secret** (public client), so nothing secret is stored on the device.

---

## 2. Create a custom Authorization Server + audience

Admin Console → **Security → API → Authorization Servers → Add Authorization Server**

- Name: `mcp-snowflake`
- Audience: `api://mcp-snowflake`  ← this is `OKTA_AUDIENCE`, and APIM enforces it
- Description: `Access tokens for the MCP Snowflake gateway`

Note the resulting **Issuer URI**, e.g.
`https://example.okta.com/oauth2/aus1a2b3c4d5e6f7g8h9` → this is `OKTA_ISSUER`.
Its metadata/JWKS are published at:

- Metadata: `{OKTA_ISSUER}/.well-known/openid-configuration`
- JWKS:     `{OKTA_ISSUER}/v1/keys`  ← this is `OKTA_JWKS_URI` (APIM fetches it)

---

## 3. Add the `snowflake.query` scope

In the `mcp-snowflake` authorization server → **Scopes → Add Scope**

- Name: `snowflake.query`
- Display name: `Query Snowflake via MCP`
- Description: `Allows calling the Snowflake MCP tools through APIM`
- Leave "Require user consent" per your policy (prompt or implicit).

Optionally add an **Access Policy** + **Rule** on the authz server so the demo
app/users are allowed to request `snowflake.query`:

- **Access Policies → Add Policy** → assign to the `Claude Desktop - MCP Snowflake` app
- **Add Rule** → grant type Authorization Code, scopes `snowflake.query` (+ openid/profile/email)

---

## 4. (Optional) Put email in the access token

APIM telemetry uses the `email` claim if present. In the authz server →
**Claims → Add Claim**:

- Name: `email`
- Include in token type: **Access Token**
- Value type: Expression → `user.email`
- Include in: `snowflake.query` scope (or always)

---

## 5. Verify you can mint a token (PKCE)

The browser/PKCE flow is what Claude Desktop runs. To verify from a terminal you
can use any PKCE helper; conceptually:

```
GET {OKTA_ISSUER}/v1/authorize
    ?client_id={OKTA_CLIENT_ID}
    &response_type=code
    &scope=openid%20profile%20email%20snowflake.query
    &redirect_uri=http://localhost:53682/callback
    &state=xyz
    &code_challenge=<PKCE challenge>
    &code_challenge_method=S256
```

Exchange the returned `code` at `{OKTA_ISSUER}/v1/token` (with `code_verifier`)
to receive an `access_token`. Decode it at jwt.io and confirm:

- `iss` == `OKTA_ISSUER`
- `aud` == `api://mcp-snowflake`
- `scp` contains `snowflake.query`
- `exp` in the future

Those are exactly the checks the APIM `validate-jwt` policy performs.

---

## Values you now have

| Variable | Example | Used by |
|---|---|---|
| `OKTA_ISSUER` | `https://example.okta.com/oauth2/aus1a2b3...` | APIM policy, agent |
| `OKTA_AUDIENCE` | `api://mcp-snowflake` | APIM policy |
| `OKTA_JWKS_URI` | `{OKTA_ISSUER}/v1/keys` | APIM named value |
| `OKTA_CLIENT_ID` | `0oa1a2b3c4...` | Claude Desktop config |
| scope | `snowflake.query` | all layers |

No client secret and no API key are stored on the device — authentication is
entirely via the short-lived Okta access token.
