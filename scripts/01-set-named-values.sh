#!/usr/bin/env bash
# Create/refresh the APIM named values referenced by BOTH policies (Pattern B):
#   Agent API policy  -> OKTA_ISSUER, OKTA_AGENT_AUDIENCE, AGENT_BACKEND_URL
#   MCP API policy     -> OKTA_ISSUER, OKTA_AUDIENCE, OKTA_JWKS_URI, MCP_BACKEND_URL
# Requires: az CLI logged in.
set -euo pipefail

: "${APIM_RG:?set APIM_RG}"
: "${APIM_NAME:?set APIM_NAME}"
: "${OKTA_ISSUER:?set OKTA_ISSUER}"
: "${OKTA_AUDIENCE:?set OKTA_AUDIENCE (MCP API audience, e.g. api://mcp-snowflake)}"
: "${OKTA_AGENT_AUDIENCE:?set OKTA_AGENT_AUDIENCE (Agent API audience, e.g. api://agent)}"
: "${OKTA_JWKS_URI:=${OKTA_ISSUER%/}/v1/keys}"
: "${MCP_BACKEND_URL:?set MCP_BACKEND_URL (backend MCP server URL)}"
: "${AGENT_BACKEND_URL:?set AGENT_BACKEND_URL (agent service URL)}"

set_nv () {
  local name="$1" value="$2"
  echo "  - $name"
  az apim nv show -g "$APIM_RG" --service-name "$APIM_NAME" --named-value-id "$name" >/dev/null 2>&1 \
    && az apim nv update -g "$APIM_RG" --service-name "$APIM_NAME" --named-value-id "$name" --value "$value" >/dev/null \
    || az apim nv create -g "$APIM_RG" --service-name "$APIM_NAME" --named-value-id "$name" \
         --display-name "$name" --value "$value" >/dev/null
}

echo "Setting named values on APIM '$APIM_NAME'..."
set_nv OKTA_ISSUER          "$OKTA_ISSUER"
set_nv OKTA_AUDIENCE        "$OKTA_AUDIENCE"
set_nv OKTA_AGENT_AUDIENCE  "$OKTA_AGENT_AUDIENCE"
set_nv OKTA_JWKS_URI        "$OKTA_JWKS_URI"
set_nv MCP_BACKEND_URL      "$MCP_BACKEND_URL"
set_nv AGENT_BACKEND_URL    "$AGENT_BACKEND_URL"
echo "Done."
