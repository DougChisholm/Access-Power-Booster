# run-all.ps1
# -----------
# Master orchestration script — Access to Power Platform
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
#   - Windows OS
#   - Python 3.9+ on PATH
#   - Microsoft Access Database Engine 2016 Redistributable installed
#   - Power Platform CLI (pac) on PATH
#   - pip install pyodbc requests msal
#   - .env file in project root (or environment variables set)
#
# Usage:
#   .\run-all.ps1
#   .\run-all.ps1 -SkipExtract   # if extraction already done
#   .\run-all.ps1 -DryRun        # validate without inserting/importing

param(
    [string]$DbPath       = "$PSScriptRoot\input\Database3.accdb",
    [string]$DataverseUrl = $env:DATAVERSE_URL,
    [switch]$SkipExtract,
    [switch]$SkipSchema,
    [switch]$SkipMigrate,
    [switch]$SkipApp,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptsDir = $PSScriptRoot + "\scripts"
$ProjectRoot = $PSScriptRoot

# ── Helpers ───────────────────────────────────────────────────────────────────

function Write-Banner ([string]$text) {
    Write-Host ""
    Write-Host ("=" * 60) -ForegroundColor Magenta
    Write-Host "  $text" -ForegroundColor Magenta
    Write-Host ("=" * 60) -ForegroundColor Magenta
}

function Assert-Success ([string]$step) {
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Step '$step' failed with exit code $LASTEXITCODE."
        exit $LASTEXITCODE
    }
}

function Load-DotEnv {
    $envFile = "$ProjectRoot\.env"
    if (Test-Path $envFile) {
        Write-Host "[run-all] Loading .env file..." -ForegroundColor DarkGray
        Get-Content $envFile | ForEach-Object {
            if ($_ -match "^\s*([^#=]+?)\s*=\s*(.*)\s*$") {
                $key = $matches[1]
                $val = $matches[2].Trim('"').Trim("'")
                [System.Environment]::SetEnvironmentVariable($key, $val, "Process")
            }
        }
    }
}

# ── Load env vars ─────────────────────────────────────────────────────────────

Load-DotEnv

# Re-read after .env load
if (-not $DataverseUrl) { $DataverseUrl = $env:DATAVERSE_URL }

if (-not $DataverseUrl) {
    Write-Error "DATAVERSE_URL is not set. Add it to .env or set the environment variable."
    exit 1
}

$env:DATAVERSE_URL = $DataverseUrl

# ── Check prerequisites ───────────────────────────────────────────────────────

Write-Banner "Checking Prerequisites"

foreach ($cmd in @("python", "pac")) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Write-Error "Required command not found: $cmd"
        exit 1
    }
}

$pythonVersion = python --version 2>&1
Write-Host "  Python: $pythonVersion"

$pacVersion = pac --version 2>&1
Write-Host "  pac:    $($pacVersion | Select-Object -First 1)"

if (-not (Test-Path $DbPath)) {
    Write-Error "Access database not found: $DbPath"
    exit 1
}
Write-Host "  DB:     $DbPath"

# ── Step 1 - Authenticate ─────────────────────────────────────────────────────

Write-Banner "Step 1 — Authenticating to Power Platform"
& "$ScriptsDir\auth.ps1" -Url $DataverseUrl
Assert-Success "auth"

# ── Step 2 - Extract Access DB ────────────────────────────────────────────────

if (-not $SkipExtract) {
    Write-Banner "Step 2 — Extracting Access Database"
    Push-Location $ScriptsDir
    python extract_access.py `
        --db "$DbPath" `
        --schema-dir "..\data\schema" `
        --tables-dir "..\data\tables"
    Assert-Success "extract_access"
    Pop-Location
} else {
    Write-Host "[run-all] Skipping extraction (--SkipExtract)" -ForegroundColor Yellow
}

# ── Step 3 - Generate Dataverse Schema ────────────────────────────────────────

if (-not $SkipSchema) {
    Write-Banner "Step 3 — Generating Dataverse Schema"
    Push-Location $ScriptsDir
    python generate_dataverse_schema.py
    Assert-Success "generate_dataverse_schema"
    Pop-Location
} else {
    Write-Host "[run-all] Skipping schema generation (--SkipSchema)" -ForegroundColor Yellow
}

# ── Step 4 - Create Dataverse Solution + Tables ───────────────────────────────

Write-Banner "Step 4 — Creating Dataverse Solution and Tables"
& "$ScriptsDir\create-solution.ps1"
Assert-Success "create-solution"

# ── Step 5 - Migrate Data ─────────────────────────────────────────────────────

if (-not $SkipMigrate) {
    Write-Banner "Step 5 — Migrating Data to Dataverse"
    Push-Location $ScriptsDir
    $migrateArgs = @()
    if ($DryRun) { $migrateArgs += "--dry-run" }
    python migrate_data.py @migrateArgs
    Assert-Success "migrate_data"
    Pop-Location
} else {
    Write-Host "[run-all] Skipping data migration (--SkipMigrate)" -ForegroundColor Yellow
}

# ── Step 6 - Generate Power App Source ───────────────────────────────────────

if (-not $SkipApp) {
    Write-Banner "Step 6 — Generating Power App Source Files"
    Push-Location $ScriptsDir
    python generate_powerapp.py
    Assert-Success "generate_powerapp"
    Pop-Location

    # ── Step 7 - Import Solution ───────────────────────────────────────────────
    Write-Banner "Step 7 — Importing Solution into Dataverse"
    if (-not $DryRun) {
        & "$ScriptsDir\import-solution.ps1"
        Assert-Success "import-solution"
    } else {
        Write-Host "[run-all] DryRun mode — skipping solution import." -ForegroundColor Yellow
    }
} else {
    Write-Host "[run-all] Skipping app generation and import (--SkipApp)" -ForegroundColor Yellow
}

# ── Done ──────────────────────────────────────────────────────────────────────

Write-Banner "ALL STEPS COMPLETE"
Write-Host ""
Write-Host "  Access DB    : $DbPath"                              -ForegroundColor White
Write-Host "  Dataverse Org: $DataverseUrl"                       -ForegroundColor White
Write-Host "  Data output  : $ProjectRoot\data\"                  -ForegroundColor White
Write-Host "  Schema output: $ProjectRoot\dataverse\"             -ForegroundColor White
Write-Host "  App source   : $ProjectRoot\powerapp\"              -ForegroundColor White
Write-Host ""
Write-Host "  Next: Open Power Apps Studio and connect data sources." -ForegroundColor Cyan
