#!/usr/bin/env bash
# create-solution.sh
# ------------------
# Step 3b - Create a Dataverse solution and add tables defined in /dataverse/
#
# Uses Power Platform CLI (pac) and the Dataverse Web API via curl.
#
# Prerequisites:
#   - Authenticated via auth.sh
#   - pac CLI on PATH
#   - DATAVERSE_URL environment variable set
#
# Usage:
#   ./scripts/create-solution.sh
#   SOLUTION_NAME=MyMigration ./scripts/create-solution.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

SOLUTION_NAME="${SOLUTION_NAME:-AccessMigration}"
PUBLISHER_NAME="${PUBLISHER_NAME:-AccessMigrationPublisher}"
PUBLISHER_PREFIX="${PUBLISHER_PREFIX:-auto}"
DATAVERSE_URL="${DATAVERSE_URL:-}"
TABLE_SCHEMA_DIR="${TABLE_SCHEMA_DIR:-$PROJECT_ROOT/dataverse/tables}"

if [[ -z "$DATAVERSE_URL" ]]; then
    echo "ERROR: DATAVERSE_URL is not set." >&2
    exit 1
fi

if [[ ! -d "$TABLE_SCHEMA_DIR" ]]; then
    echo "ERROR: Table schema directory not found: $TABLE_SCHEMA_DIR" >&2
    echo "Run generate_dataverse_schema.py first." >&2
    exit 1
fi

# ── Helpers ──────────────────────────────────────────────────────────────────

get_token() {
    local token
    # Use MSAL with service principal credentials from .env
    token=$(python3 -c "
import msal, os
app = msal.ConfidentialClientApplication(
    os.environ['AZURE_CLIENT_ID'],
    authority='https://login.microsoftonline.com/' + os.environ['AZURE_TENANT_ID'],
    client_credential=os.environ['AZURE_CLIENT_SECRET'],
)
result = app.acquire_token_for_client(scopes=[os.environ['DATAVERSE_URL'] + '/.default'])
if 'access_token' in result:
    print(result['access_token'])
else:
    raise RuntimeError(result.get('error_description', 'Token acquisition failed'))
" 2>/dev/null) || true

    if [[ -z "$token" || "$token" != ey* ]]; then
        # Fallback: try az cli
        token=$(az account get-access-token --resource "$DATAVERSE_URL" --query accessToken -o tsv 2>/dev/null) || true
    fi
    if [[ -z "$token" ]]; then
        echo "ERROR: Could not obtain access token. Check AZURE_CLIENT_ID/SECRET/TENANT_ID in .env" >&2
        exit 1
    fi
    echo "$token"
}

dataverse_api() {
    local method="$1"
    local path="$2"
    local body="${3:-}"
    local token
    token=$(get_token)

    # Encode spaces for URL safety
    local encoded_path="${path// /%20}"
    local url="$DATAVERSE_URL/api/data/v9.2/$encoded_path"
    local args=(
        -s -S -g
        -X "$method"
        -H "Authorization: Bearer $token"
        -H "Content-Type: application/json"
        -H "OData-MaxVersion: 4.0"
        -H "OData-Version: 4.0"
        -H "Accept: application/json"
    )
    if [[ -n "$body" ]]; then
        args+=(-d "$body")
    fi

    curl "${args[@]}" "$url"
}

# ── 1. Ensure publisher exists ───────────────────────────────────────────────

echo ""
echo "[create-solution] Ensuring publisher '$PUBLISHER_PREFIX' exists..."

pub_result=$(dataverse_api GET "publishers?\$filter=uniquename eq '$PUBLISHER_NAME'")
pub_count=$(echo "$pub_result" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('value',[])))" 2>/dev/null || echo "0")

if [[ "$pub_count" == "0" ]]; then
    echo "  Creating publisher..."
    pub_body=$(python3 -c "
import json
print(json.dumps({
    'uniquename': '$PUBLISHER_NAME',
    'friendlyname': '$PUBLISHER_NAME',
    'customizationprefix': '$PUBLISHER_PREFIX'
}))
")
    dataverse_api POST "publishers" "$pub_body" >/dev/null
    echo "  Publisher created."
else
    echo "  Publisher already exists."
fi

# Get publisher ID
pub_result=$(dataverse_api GET "publishers?\$filter=uniquename eq '$PUBLISHER_NAME'")
PUBLISHER_ID=$(echo "$pub_result" | python3 -c "import sys,json; print(json.load(sys.stdin)['value'][0]['publisherid'])")

# ── 2. Create or reuse solution ─────────────────────────────────────────────

echo ""
echo "[create-solution] Ensuring solution '$SOLUTION_NAME' exists..."

sol_result=$(dataverse_api GET "solutions?\$filter=uniquename eq '$SOLUTION_NAME'")
sol_count=$(echo "$sol_result" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('value',[])))" 2>/dev/null || echo "0")

if [[ "$sol_count" == "0" ]]; then
    echo "  Creating solution..."
    sol_body=$(python3 -c "
import json
print(json.dumps({
    'uniquename': '$SOLUTION_NAME',
    'friendlyname': '$SOLUTION_NAME',
    'version': '1.0.0.0',
    'publisherid@odata.bind': '/publishers($PUBLISHER_ID)'
}))
")
    dataverse_api POST "solutions" "$sol_body" >/dev/null
    echo "  Solution created."
else
    echo "  Solution already exists."
fi

# ── 3. Create tables ────────────────────────────────────────────────────────

for file in "$TABLE_SCHEMA_DIR"/*.json; do
    [[ -f "$file" ]] || continue

    logical_name=$(python3 -c "import sys,json; print(json.load(open('$file'))['LogicalName'])")
    display_name=$(python3 -c "import sys,json; print(json.load(open('$file'))['DisplayName']['LocalizedLabels'][0]['Label'])")

    echo ""
    echo "[create-solution] Processing table: $display_name ($logical_name)"

    # Check if table exists
    existing=$(dataverse_api GET "EntityDefinitions(LogicalName='$logical_name')" 2>/dev/null || echo "NOT_FOUND")

    if [[ "$existing" == *"NOT_FOUND"* ]] || [[ "$existing" == *"Does Not Exist"* ]] || [[ "$existing" == *"0x80060002"* ]] || [[ "$existing" == *"error"* ]]; then
        echo "  Creating table '$logical_name'..."
        entity_payload=$(python3 -c "
import sys, json
d = json.load(open('$file'))
for k in ['Columns', 'access_source_table', 'access_primary_keys', 'PrimaryNameAttribute']:
    d.pop(k, None)
# Dataverse Web API: primary name attribute goes in 'Attributes' array
# with 'IsPrimaryName': true — not as a top-level 'PrimaryAttribute'
primary_attr = d.pop('PrimaryAttribute', None)
if primary_attr:
    primary_attr['IsPrimaryName'] = True
    primary_attr.setdefault('AttributeType', 'String')
    primary_attr.setdefault('AttributeTypeName', {'Value': 'StringType'})
    primary_attr.setdefault('FormatName', {'Value': 'Text'})
    d['Attributes'] = [primary_attr]
print(json.dumps(d))
")
        result=$(dataverse_api POST "EntityDefinitions" "$entity_payload")
        if echo "$result" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('error',{}).get('message',''))" 2>/dev/null | grep -q .; then
            error_msg=$(echo "$result" | python3 -c "import sys,json; print(json.load(sys.stdin)['error']['message'])" 2>/dev/null)
            echo "  ERROR creating table: $error_msg"
        else
            echo "  Table created."
        fi
    else
        echo "  Table '$logical_name' already exists. Skipping creation."
    fi

    # Create columns
    python3 -c "
import sys, json
d = json.load(open('$file'))
for col in d.get('Columns', []):
    sys.stdout.write(json.dumps(col) + '\n')
" | while IFS= read -r col_json; do
        col_logical=$(echo "$col_json" | python3 -c "import sys,json; print(json.load(sys.stdin)['LogicalName'])")
        col_display=$(echo "$col_json" | python3 -c "import sys,json; print(json.load(sys.stdin)['DisplayName']['LocalizedLabels'][0]['Label'])")

        # Strip helper props
        col_payload=$(echo "$col_json" | python3 -c "
import sys, json
d = json.load(sys.stdin)
for k in ['access_source_column', 'access_source_type', 'is_primary_key_source']:
    d.pop(k, None)
print(json.dumps(d))
")

        # Check if column exists
        col_existing=$(dataverse_api GET "EntityDefinitions(LogicalName='$logical_name')/Attributes(LogicalName='$col_logical')" 2>/dev/null || echo "NOT_FOUND")

        if [[ "$col_existing" == *"NOT_FOUND"* ]] || [[ "$col_existing" == *"Could not find"* ]] || [[ "$col_existing" == *"0x80060002"* ]]; then
            echo "    Creating column: $col_display ($col_logical)"
            dataverse_api POST "EntityDefinitions(LogicalName='$logical_name')/Attributes" "$col_payload" >/dev/null 2>&1 || \
                echo "    WARNING: Failed to create column '$col_logical'"
        else
            echo "    Column '$col_logical' already exists. Skipping."
        fi
    done
done

# ── 4. Create relationships ─────────────────────────────────────────────────

REL_FILE="$PROJECT_ROOT/dataverse/relationships.json"
if [[ -f "$REL_FILE" ]]; then
    echo ""
    echo "[create-solution] Creating relationships..."

    python3 -c "
import sys, json
rels = json.load(open('$REL_FILE'))
for rel in rels:
    sys.stdout.write(json.dumps(rel) + '\n')
" | while IFS= read -r rel_json; do
        schema_name=$(echo "$rel_json" | python3 -c "import sys,json; print(json.load(sys.stdin)['SchemaName'])")
        echo "  Relationship: $schema_name"

        rel_payload=$(echo "$rel_json" | python3 -c "
import sys, json
d = json.load(sys.stdin)
d.pop('access_source', None)
print(json.dumps(d))
")
        dataverse_api POST "RelationshipDefinitions" "$rel_payload" >/dev/null 2>&1 || \
            echo "  WARNING: Relationship '$schema_name' may already exist or failed."
    done
fi

echo ""
echo "✅ Solution and tables created successfully."
