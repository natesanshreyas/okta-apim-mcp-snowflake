#!/usr/bin/env bash
# Import the MCP OpenAPI as a NEW API into your EXISTING APIM instance.
# Requires: az CLI logged in; env vars APIM_RG, APIM_NAME.
# Optional: API_ID (default mcp-snowflake), API_PATH (default mcp-snowflake).
set -euo pipefail

: "${APIM_RG:?set APIM_RG}"
: "${APIM_NAME:?set APIM_NAME}"
API_ID="${API_ID:-mcp-snowflake}"
API_PATH="${API_PATH:-mcp-snowflake}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPEC="$SCRIPT_DIR/../apim/openapi.yaml"

echo "Importing API '$API_ID' (path '/$API_PATH') into APIM '$APIM_NAME'..."
az apim api import \
  --resource-group "$APIM_RG" \
  --service-name "$APIM_NAME" \
  --api-id "$API_ID" \
  --path "$API_PATH" \
  --specification-format OpenApi \
  --specification-path "$SPEC" \
  --display-name "MCP Snowflake Gateway" \
  --protocols https

echo "Imported. Next: ./scripts/03-apply-policy.sh"
