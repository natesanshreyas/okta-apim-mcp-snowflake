# Snowflake setup (real backend)

For the local demo you can skip this entirely — set `SNOWFLAKE_MODE=mock` and the
MCP server serves sample data. This doc covers connecting the MCP server to a
**real** Snowflake account using **key-pair authentication** (no static password
in the request path, no credentials committed to the repo).

## 1. Create demo objects

Run [`../mock-snowflake/seed.sql`](../mock-snowflake/seed.sql) in a Snowflake
worksheet (as a role that can create databases), or adapt it to your estate. It
creates `MCP_DEMO_DB.PUBLIC.CUSTOMERS` and `ORDERS`.

## 2. Create a least-privilege role, warehouse, and user

```sql
USE ROLE ACCOUNTADMIN;

CREATE WAREHOUSE IF NOT EXISTS MCP_DEMO_WH
  WAREHOUSE_SIZE = XSMALL AUTO_SUSPEND = 60 AUTO_RESUME = TRUE;

CREATE ROLE IF NOT EXISTS MCP_DEMO_ROLE;
GRANT USAGE ON WAREHOUSE MCP_DEMO_WH TO ROLE MCP_DEMO_ROLE;
GRANT USAGE ON DATABASE MCP_DEMO_DB TO ROLE MCP_DEMO_ROLE;
GRANT USAGE ON SCHEMA MCP_DEMO_DB.PUBLIC TO ROLE MCP_DEMO_ROLE;
-- Read-only to match the MCP server's read-only guardrail
GRANT SELECT ON ALL TABLES IN SCHEMA MCP_DEMO_DB.PUBLIC TO ROLE MCP_DEMO_ROLE;
GRANT SELECT ON FUTURE TABLES IN SCHEMA MCP_DEMO_DB.PUBLIC TO ROLE MCP_DEMO_ROLE;

CREATE USER IF NOT EXISTS MCP_DEMO_USER
  DEFAULT_ROLE = MCP_DEMO_ROLE
  DEFAULT_WAREHOUSE = MCP_DEMO_WH;
GRANT ROLE MCP_DEMO_ROLE TO USER MCP_DEMO_USER;
```

## 3. Generate an RSA key pair and register the public key

```bash
# Private key (encrypted). Store securely — Azure Key Vault in production.
openssl genrsa 2048 | openssl pkcs8 -topk8 -v2 aes-256-cbc -inform PEM \
  -out snowflake_rsa_key.p8
# Public key
openssl rsa -in snowflake_rsa_key.p8 -pubout -out snowflake_rsa_key.pub
```

Register the public key on the user (strip the header/footer lines):

```sql
ALTER USER MCP_DEMO_USER SET RSA_PUBLIC_KEY='MIIBIjANBgkqh...';
```

## 4. Point the MCP server at Snowflake

Set these (from Key Vault in production — never commit them):

```bash
export SNOWFLAKE_MODE=real
export SNOWFLAKE_ACCOUNT=xy12345.us-east-1
export SNOWFLAKE_USER=MCP_DEMO_USER
export SNOWFLAKE_ROLE=MCP_DEMO_ROLE
export SNOWFLAKE_WAREHOUSE=MCP_DEMO_WH
export SNOWFLAKE_DATABASE=MCP_DEMO_DB
export SNOWFLAKE_SCHEMA=PUBLIC
export SNOWFLAKE_PRIVATE_KEY_PATH=/secrets/snowflake_rsa_key.p8
export SNOWFLAKE_PRIVATE_KEY_PASSPHRASE=<the passphrase you set>

python server.py
```

## 5. Hardening (beyond the POC)

- **Network policy**: restrict Snowflake logins to the MCP server's egress IPs,
  or use Azure Private Link to Snowflake.
- **Key rotation**: Snowflake supports two registered keys (`RSA_PUBLIC_KEY` and
  `RSA_PUBLIC_KEY_2`) for zero-downtime rotation.
- **Row/column security**: apply Snowflake row access policies / masking so even a
  broad query returns only permitted data.
- **Query tagging**: set `ALTER SESSION SET QUERY_TAG` with the Okta `sub` (passed
  by APIM via `X-Auth-Subject`) so Snowflake query history attributes usage to the
  end user for audit.
