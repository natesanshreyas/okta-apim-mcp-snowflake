#!/usr/bin/env bash
# Attach the Okta JWT-validation + governance policy to the imported API.
# Requires: az CLI logged in; env vars APIM_RG, APIM_NAME.
# Optional: API_ID (default mcp-snowflake).
set -euo pipefail

: "${APIM_RG:?set APIM_RG}"
: "${APIM_NAME:?set APIM_NAME}"
API_ID="${API_ID:-mcp-snowflake}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POLICY="$SCRIPT_DIR/../apim/policy/mcp-snowflake.xml"

# Get an ARM token and PUT the policy at API scope via the REST API.
# (az apim api policy is not consistently available across CLI versions, so use REST.)
SUB_ID="$(az account show --query id -o tsv)"
ARM_TOKEN="$(az account get-access-token --query accessToken -o tsv)"
API_VER="2022-08-01"

URL="https://management.azure.com/subscriptions/$SUB_ID/resourceGroups/$APIM_RG/providers/Microsoft.ApiManagement/service/$APIM_NAME/apis/$API_ID/policies/policy?api-version=$API_VER"

echo "Applying policy to API '$API_ID' on APIM '$APIM_NAME'..."
BODY="$(jq -n --rawfile xml "$POLICY" '{properties:{format:"xml",value:$xml}}')"

curl -sS -X PUT "$URL" \
  -H "Authorization: Bearer $ARM_TOKEN" \
  -H "Content-Type: application/json" \
  -d "$BODY" | jq -r '.name // .error.message // "applied"'

echo "Policy applied."
