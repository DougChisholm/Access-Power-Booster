#!/usr/bin/env bash
# run-all.sh
# ----------
# Master orchestration script — Access to Power Platform (Linux version)
#
# Runs all steps end-to-end:
#   1. Authenticate to Power Platform
#   2. Extract Access DB (schema + data)
#   3. Generate Dataverse schema
#   4. Create Dataverse tables/solution
#   5. Migrate data
#   6. Generate Power App source
#   7. Import solution + app
#
# Prerequisites:
#   - mdbtools installed
#   - Python 3.9+ on PATH
#   - Power Platform CLI (pac) on PATH
#   - pip install requests msal
#   - .env file in project root (or environment variables set)
#
# Usage:
#   ./run-all.sh
#   ./run-all.sh --skip-extract   # if extraction already done
#   ./run-all.sh --dry-run        # validate without inserting/importing

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPTS_DIR="$SCRIPT_DIR/scripts"

# ── Parse arguments ──────────────────────────────────────────────────────────

DB_PATH="${SCRIPT_DIR}/input/Database3.accdb"
SKIP_EXTRACT=false
SKIP_SCHEMA=false
SKIP_MIGRATE=false
SKIP_APP=false
DRY_RUN=false

for arg in "$@"; do
    case "$arg" in
        --skip-extract) SKIP_EXTRACT=true ;;
        --skip-schema)  SKIP_SCHEMA=true ;;
        --skip-migrate) SKIP_MIGRATE=true ;;
        --skip-app)     SKIP_APP=true ;;
        --dry-run)      DRY_RUN=true ;;
        --db=*)         DB_PATH="${arg#*=}" ;;
        *)              echo "Unknown option: $arg" >&2; exit 1 ;;
    esac
done

# ── Helpers ──────────────────────────────────────────────────────────────────

banner() {
    echo ""
    echo "============================================================"
    echo "  $1"
    echo "============================================================"
}

# ── Load .env ────────────────────────────────────────────────────────────────

ENV_FILE="$SCRIPT_DIR/.env"
if [[ -f "$ENV_FILE" ]]; then
    echo "[run-all] Loading .env file..."
    set -a
    # shellcheck source=/dev/null
    source "$ENV_FILE"
    set +a
fi

DATAVERSE_URL="${DATAVERSE_URL:-}"

if [[ -z "$DATAVERSE_URL" ]]; then
    echo "ERROR: DATAVERSE_URL is not set. Add it to .env or set the environment variable." >&2
    exit 1
fi

export DATAVERSE_URL

# ── Check prerequisites ─────────────────────────────────────────────────────

banner "Checking Prerequisites"

for cmd in python3 pac; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "ERROR: Required command not found: $cmd" >&2
        exit 1
    fi
done

echo "  Python: $(python3 --version 2>&1)"
echo "  pac:    $(pac --version 2>&1 | head -1)"

if [[ ! -f "$DB_PATH" ]]; then
    echo "ERROR: Access database not found: $DB_PATH" >&2
    exit 1
fi
echo "  DB:     $DB_PATH"

# ── Step 1 - Authenticate ───────────────────────────────────────────────────

banner "Step 1 — Authenticating to Power Platform"
bash "$SCRIPTS_DIR/auth.sh" "$DATAVERSE_URL"

# ── Step 2 - Extract Access DB ──────────────────────────────────────────────

if [[ "$SKIP_EXTRACT" == false ]]; then
    banner "Step 2 — Extracting Access Database"
    pushd "$SCRIPTS_DIR" >/dev/null
    python3 extract_access_linux.py \
        --db "$DB_PATH" \
        --schema-dir ../data/schema \
        --tables-dir ../data/tables
    popd >/dev/null
else
    echo "[run-all] Skipping extraction (--skip-extract)"
fi

# ── Step 3 - Generate Dataverse Schema ──────────────────────────────────────

if [[ "$SKIP_SCHEMA" == false ]]; then
    banner "Step 3 — Generating Dataverse Schema"
    pushd "$SCRIPTS_DIR" >/dev/null
    python3 generate_dataverse_schema.py
    popd >/dev/null
else
    echo "[run-all] Skipping schema generation (--skip-schema)"
fi

# ── Step 4 - Create Dataverse Solution + Tables ─────────────────────────────

banner "Step 4 — Creating Dataverse Solution and Tables"
bash "$SCRIPTS_DIR/create-solution.sh"

# ── Step 5 - Migrate Data ───────────────────────────────────────────────────

if [[ "$SKIP_MIGRATE" == false ]]; then
    banner "Step 5 — Migrating Data to Dataverse"
    pushd "$SCRIPTS_DIR" >/dev/null
    migrate_args=()
    if [[ "$DRY_RUN" == true ]]; then
        migrate_args+=(--dry-run)
    fi
    python3 migrate_data.py "${migrate_args[@]}"
    popd >/dev/null
else
    echo "[run-all] Skipping data migration (--skip-migrate)"
fi

# ── Step 6 & 7 - Generate Power App + Import ────────────────────────────────

if [[ "$SKIP_APP" == false ]]; then
    banner "Step 6 — Generating Power App Source Files"
    pushd "$SCRIPTS_DIR" >/dev/null
    python3 generate_powerapp.py
    popd >/dev/null

    banner "Step 7 — Importing Solution into Dataverse"
    if [[ "$DRY_RUN" == false ]]; then
        bash "$SCRIPTS_DIR/import-solution.sh" || true
    else
        echo "[run-all] DryRun mode — skipping solution import."
    fi
else
    echo "[run-all] Skipping app generation and import (--skip-app)"
fi

# ── Done ─────────────────────────────────────────────────────────────────────

banner "ALL STEPS COMPLETE"
echo ""
echo "  Access DB    : $DB_PATH"
echo "  Dataverse Org: $DATAVERSE_URL"
echo "  Data output  : $SCRIPT_DIR/data/"
echo "  Schema output: $SCRIPT_DIR/dataverse/"
echo "  App source   : $SCRIPT_DIR/powerapp/"
echo ""
echo "  Next: Open Power Apps Studio and connect data sources."
