#!/usr/bin/env bash
# import-solution.sh
# ------------------
# Step 3c - Pack and import the Power App solution into Dataverse
#
# Packs the Canvas App source files using pac canvas pack,
# then imports the solution using pac solution import.
#
# Prerequisites:
#   - pac CLI on PATH
#   - Authenticated via auth.sh
#   - Power App source files in /powerapp/src/
#
# Usage:
#   ./scripts/import-solution.sh
#   ASYNC=1 ./scripts/import-solution.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

SOLUTION_NAME="${SOLUTION_NAME:-AccessMigration}"
POWERAPP_SRC_DIR="${POWERAPP_SRC_DIR:-$PROJECT_ROOT/powerapp/src}"
POWERAPP_MSAPP="${POWERAPP_MSAPP:-$PROJECT_ROOT/powerapp/App.msapp}"
SOLUTION_ZIP="${SOLUTION_ZIP:-$PROJECT_ROOT/powerapp/AccessMigration_solution.zip}"
ASYNC="${ASYNC:-}"

# ── Validate ─────────────────────────────────────────────────────────────────

if ! command -v pac &>/dev/null; then
    echo "ERROR: pac (Power Platform CLI) not found." >&2
    exit 1
fi

if [[ ! -d "$POWERAPP_SRC_DIR" ]]; then
    echo "ERROR: Power App source directory not found: $POWERAPP_SRC_DIR" >&2
    echo "Run generate_powerapp.py first." >&2
    exit 1
fi

# ── 1. Pack Canvas App ───────────────────────────────────────────────────────

echo ""
echo "[import-solution] Packing Canvas App sources → $POWERAPP_MSAPP"

# pac canvas pack is deprecated in pac CLI 2.6+; try the new command first
if pac canvas pack --help &>/dev/null 2>&1; then
    pac canvas pack \
        --sources "$POWERAPP_SRC_DIR" \
        --msapp "$POWERAPP_MSAPP" || {
        echo ""
        echo "WARNING: pac canvas pack failed. This command is deprecated in pac CLI 2.6+."
        echo "The Power App YAML source files have been generated at: $POWERAPP_SRC_DIR"
        echo ""
        echo "To complete the import manually:"
        echo "  1. Open https://make.powerapps.com"
        echo "  2. Create a new Canvas App"
        echo "  3. Use the generated screen files as reference for building screens"
        echo ""
        echo "Skipping solution pack and import steps."
        exit 0
    }
else
    echo ""
    echo "WARNING: pac canvas pack is not available."
    echo "The Power App YAML source files have been generated at: $POWERAPP_SRC_DIR"
    echo ""
    echo "To complete the import manually:"
    echo "  1. Open https://make.powerapps.com"
    echo "  2. Create a new Canvas App"
    echo "  3. Use the generated screen files as reference for building screens"
    echo ""
    echo "Skipping solution pack and import steps."
    exit 0
fi

echo "  Canvas App packed."

# ── 2. Add app to solution ───────────────────────────────────────────────────

echo ""
echo "[import-solution] Creating solution package..."

SOLUTION_DIR="$PROJECT_ROOT/powerapp/solution_src"
mkdir -p "$SOLUTION_DIR"

# Create solution.xml
cat > "$SOLUTION_DIR/solution.xml" <<EOF
<?xml version="1.0" encoding="utf-8"?>
<ImportExportXml version="9.0.0.0007" SolutionPackageVersion="9.2" languagecode="1033" generatedBy="CrmLive" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <SolutionManifest>
    <UniqueName>$SOLUTION_NAME</UniqueName>
    <LocalizedNames>
      <LocalizedName description="$SOLUTION_NAME" languagecode="1033" />
    </LocalizedNames>
    <Descriptions />
    <Version>1.0.0.0</Version>
    <Managed>0</Managed>
    <Publisher>
      <UniqueName>AccessMigrationPublisher</UniqueName>
      <LocalizedNames>
        <LocalizedName description="Access Migration Publisher" languagecode="1033" />
      </LocalizedNames>
      <Descriptions />
      <EMailAddress></EMailAddress>
      <SupportingWebsiteUrl></SupportingWebsiteUrl>
      <CustomizationPrefix>auto</CustomizationPrefix>
      <CustomizationOptionValuePrefix>10000</CustomizationOptionValuePrefix>
      <Addresses />
    </Publisher>
    <RootComponents>
      <RootComponent type="300" id="{00000000-0000-0000-0000-000000000001}" behavior="0" />
    </RootComponents>
    <MissingDependencies />
  </SolutionManifest>
</ImportExportXml>
EOF

# Create [Content_Types].xml
cat > "$SOLUTION_DIR/[Content_Types].xml" <<EOF
<?xml version="1.0" encoding="utf-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="xml" ContentType="application/xml" />
  <Default Extension="msapp" ContentType="application/msapp" />
</Types>
EOF

# Copy msapp into solution
CANVAS_DIR="$SOLUTION_DIR/CanvasApps"
mkdir -p "$CANVAS_DIR"
cp "$POWERAPP_MSAPP" "$CANVAS_DIR/AccessMigratedApp.msapp"

# Zip the solution
echo "  Zipping solution..."
rm -f "$SOLUTION_ZIP"
(cd "$SOLUTION_DIR" && zip -r "$SOLUTION_ZIP" .)
echo "  Solution zip created: $SOLUTION_ZIP"

# ── 3. Import solution ──────────────────────────────────────────────────────

echo ""
echo "[import-solution] Importing solution into Dataverse..."

import_args=(solution import --path "$SOLUTION_ZIP" --force-overwrite)
if [[ -n "$ASYNC" ]]; then
    import_args+=(--async)
fi

pac "${import_args[@]}"

echo ""
echo "✅ Solution imported successfully."
