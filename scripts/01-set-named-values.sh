#!/usr/bin/env bash
# Create/refresh the APIM named values referenced by the MCP policy.
# Requires: az CLI logged in; env vars APIM_RG, APIM_NAME, OKTA_ISSUER,
#           OKTA_AUDIENCE, OKTA_JWKS_URI, MCP_BACKEND_URL.
set -euo pipefail

: "${APIM_RG:?set APIM_RG}"
: "${APIM_NAME:?set APIM_NAME}"
: "${OKTA_ISSUER:?set OKTA_ISSUER}"
: "${OKTA_AUDIENCE:?set OKTA_AUDIENCE}"
: "${OKTA_JWKS_URI:=${OKTA_ISSUER%/}/v1/keys}"
: "${MCP_BACKEND_URL:?set MCP_BACKEND_URL (backend MCP server URL)}"

set_nv () {
  local name="$1" value="$2"
  echo "  - $name"
  az apim nv show -g "$APIM_RG" --service-name "$APIM_NAME" --named-value-id "$name" >/dev/null 2>&1 \
    && az apim nv update -g "$APIM_RG" --service-name "$APIM_NAME" --named-value-id "$name" --value "$value" >/dev/null \
    || az apim nv create -g "$APIM_RG" --service-name "$APIM_NAME" --named-value-id "$name" \
         --display-name "$name" --value "$value" >/dev/null
}

echo "Setting named values on APIM '$APIM_NAME'..."
set_nv OKTA_ISSUER     "$OKTA_ISSUER"
set_nv OKTA_AUDIENCE   "$OKTA_AUDIENCE"
set_nv OKTA_JWKS_URI   "$OKTA_JWKS_URI"
set_nv MCP_BACKEND_URL "$MCP_BACKEND_URL"
echo "Done."
