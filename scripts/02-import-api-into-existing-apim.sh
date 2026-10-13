#!/usr/bin/env bash
# Import an OpenAPI spec as a NEW API into your EXISTING APIM instance.
# Pattern B uses TWO APIs; run this once per API (see usage below).
#
# Requires: az CLI logged in; env vars APIM_RG, APIM_NAME.
# Args (or env): API_ID, API_PATH, SPEC (path to OpenAPI), DISPLAY.
#
# Usage:
#   # Agent (front door) API:
#   API_ID=agent API_PATH=agent SPEC=apim/agent-openapi.yaml \
#     DISPLAY="MCP Snowflake Agent" ./scripts/02-import-api-into-existing-apim.sh
#   # MCP tool API:
#   API_ID=mcp-snowflake API_PATH=mcp-snowflake SPEC=apim/openapi.yaml \
#     DISPLAY="MCP Snowflake Gateway" ./scripts/02-import-api-into-existing-apim.sh
set -euo pipefail

: "${APIM_RG:?set APIM_RG}"
: "${APIM_NAME:?set APIM_NAME}"
API_ID="${API_ID:-mcp-snowflake}"
API_PATH="${API_PATH:-$API_ID}"
DISPLAY="${DISPLAY:-$API_ID}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPEC="${SPEC:-$SCRIPT_DIR/../apim/openapi.yaml}"
# Allow SPEC to be given relative to repo root.
[[ -f "$SPEC" ]] || SPEC="$SCRIPT_DIR/../$SPEC"

echo "Importing API '$API_ID' (path '/$API_PATH') from '$SPEC' into APIM '$APIM_NAME'..."
az apim api import \
  --resource-group "$APIM_RG" \
  --service-name "$APIM_NAME" \
  --api-id "$API_ID" \
  --path "$API_PATH" \
  --specification-format OpenApi \
  --specification-path "$SPEC" \
  --display-name "$DISPLAY" \
  --protocols https

echo "Imported '$API_ID'. Next: apply its policy with scripts/03-apply-policy.sh"
