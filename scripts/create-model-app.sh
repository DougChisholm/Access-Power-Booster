#!/usr/bin/env bash
# create-model-app.sh
# -------------------
# Creates a Model-Driven App in Dataverse with forms and views
# for all migrated tables.
#
# Uses the Dataverse Web API to:
#   1. Create a model-driven app (AppModule)
#   2. Add all auto_ tables as app components
#   3. Publish the app
#
# Prerequisites:
#   - Authenticated (service principal in .env)
#   - Tables already created via create-solution.sh
#
# Usage:
#   ./scripts/create-model-app.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

DATAVERSE_URL="${DATAVERSE_URL:-}"
SOLUTION_NAME="${SOLUTION_NAME:-AccessMigration}"
APP_NAME="${APP_NAME:-AccessMigratedModelApp}"

if [[ -z "$DATAVERSE_URL" ]]; then
    echo "ERROR: DATAVERSE_URL is not set." >&2
    exit 1
fi

echo ""
echo "============================================================"
echo "  Creating Model-Driven App: $APP_NAME"
echo "============================================================"

# Use Python + MSAL for all Dataverse API interaction (reliable token + JSON handling)
python3 "$SCRIPT_DIR/create_model_app.py" \
    --url "$DATAVERSE_URL" \
    --solution "$SOLUTION_NAME" \
    --app-name "$APP_NAME"
