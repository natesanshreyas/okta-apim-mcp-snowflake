#!/usr/bin/env bash
# Attach an Okta JWT-validation + governance policy to an imported API.
# Pattern B uses TWO policies; run once per API.
#
# Requires: az CLI logged in; env vars APIM_RG, APIM_NAME.
# Args (or env): API_ID, POLICY (path to policy xml).
#
# Usage:
#   API_ID=agent         POLICY=apim/policy/agent-api.xml     ./scripts/03-apply-policy.sh
#   API_ID=mcp-snowflake POLICY=apim/policy/mcp-snowflake.xml ./scripts/03-apply-policy.sh
set -euo pipefail

: "${APIM_RG:?set APIM_RG}"
: "${APIM_NAME:?set APIM_NAME}"
API_ID="${API_ID:-mcp-snowflake}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POLICY="${POLICY:-$SCRIPT_DIR/../apim/policy/mcp-snowflake.xml}"
[[ -f "$POLICY" ]] || POLICY="$SCRIPT_DIR/../$POLICY"

SUB_ID="$(az account show --query id -o tsv)"
ARM_TOKEN="$(az account get-access-token --query accessToken -o tsv)"
API_VER="2022-08-01"
URL="https://management.azure.com/subscriptions/$SUB_ID/resourceGroups/$APIM_RG/providers/Microsoft.ApiManagement/service/$APIM_NAME/apis/$API_ID/policies/policy?api-version=$API_VER"

echo "Applying policy '$POLICY' to API '$API_ID' on APIM '$APIM_NAME'..."
BODY="$(jq -n --rawfile xml "$POLICY" '{properties:{format:"xml",value:$xml}}')"
curl -sS -X PUT "$URL" \
  -H "Authorization: Bearer $ARM_TOKEN" \
  -H "Content-Type: application/json" \
  -d "$BODY" | jq -r '.name // .error.message // "applied"'
echo "Policy applied to '$API_ID'."
