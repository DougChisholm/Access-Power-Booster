#!/usr/bin/env bash
# auth.sh
# -------
# Step 3a - Authenticate to Power Platform CLI
#
# Prerequisites:
#   pac (Power Platform CLI) must be installed and on PATH
#   Set DATAVERSE_URL environment variable or pass as first argument
#
# Usage:
#   ./scripts/auth.sh
#   ./scripts/auth.sh "https://yourorg.crm.dynamics.com"

set -euo pipefail

URL="${1:-${DATAVERSE_URL:-}}"
TENANT="${AZURE_TENANT_ID:-}"
CLIENT_ID="${AZURE_CLIENT_ID:-}"
CLIENT_SECRET="${AZURE_CLIENT_SECRET:-}"

if [[ -z "$URL" ]]; then
    echo "ERROR: DATAVERSE_URL is not set. Pass as argument or set the environment variable." >&2
    exit 1
fi

echo "[auth] Authenticating to: $URL"

if ! command -v pac &>/dev/null; then
    echo "ERROR: Power Platform CLI (pac) not found. Install from: https://aka.ms/PowerAppsCLI" >&2
    exit 1
fi

# Use service principal (non-interactive) if credentials are available;
# otherwise fall back to interactive browser auth.
if [[ -n "$TENANT" && -n "$CLIENT_ID" && -n "$CLIENT_SECRET" ]]; then
    echo "[auth] Using service principal (non-interactive)..."
    pac auth create \
        --environment "$URL" \
        --tenant "$TENANT" \
        --applicationId "$CLIENT_ID" \
        --clientSecret "$CLIENT_SECRET"
else
    echo "[auth] No service principal configured — attempting interactive login..."
    pac auth create --environment "$URL"
fi

echo "[auth] Authentication successful."
