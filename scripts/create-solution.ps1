# create-solution.ps1
# --------------------
# Step 3b - Create a Dataverse solution and add tables defined in /dataverse/
#
# Uses Power Platform CLI (pac) and the Dataverse Web API.
#
# Prerequisites:
#   - Authenticated via auth.ps1
#   - pac CLI on PATH
#   - DATAVERSE_URL environment variable set
#
# Usage:
#   .\create-solution.ps1
#   .\create-solution.ps1 -SolutionName "AccessMigration" -PublisherPrefix "auto"

param(
    [string]$SolutionName   = "AccessMigration",
    [string]$PublisherName  = "AccessMigrationPublisher",
    [string]$PublisherPrefix = "auto",
    [string]$DataverseUrl   = $env:DATAVERSE_URL,
    [string]$TableSchemaDir = "$PSScriptRoot\..\dataverse\tables"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── Helpers ──────────────────────────────────────────────────────────────────

function Write-Step ([string]$msg) {
    Write-Host "`n[create-solution] $msg" -ForegroundColor Cyan
}

function Invoke-DataverseApi {
    param(
        [string]$Method,
        [string]$Path,
        [object]$Body = $null
    )
    $token = (pac auth token 2>$null) | Select-Object -Last 1
    if (-not $token -or $token -notmatch "^ey") {
        # Fall back: use az account get-access-token
        $rawToken = az account get-access-token --resource $DataverseUrl --query accessToken -o tsv 2>$null
        $token = $rawToken
    }

    $headers = @{
        "Authorization"    = "Bearer $token"
        "Content-Type"     = "application/json"
        "OData-MaxVersion" = "4.0"
        "OData-Version"    = "4.0"
        "Accept"           = "application/json"
    }

    $uri = "$DataverseUrl/api/data/v9.2/$Path"
    $params = @{ Method = $Method; Uri = $uri; Headers = $headers }
    if ($Body) {
        $params.Body = ($Body | ConvertTo-Json -Depth 20 -Compress)
    }

    $response = Invoke-RestMethod @params
    return $response
}

# ── Validate ─────────────────────────────────────────────────────────────────

if (-not $DataverseUrl) {
    Write-Error "DATAVERSE_URL is not set."
    exit 1
}

if (-not (Test-Path $TableSchemaDir)) {
    Write-Error "Table schema directory not found: $TableSchemaDir`nRun generate_dataverse_schema.py first."
    exit 1
}

# ── 1. Ensure publisher exists ────────────────────────────────────────────────

Write-Step "Ensuring publisher '$PublisherPrefix' exists..."

$publishers = Invoke-DataverseApi -Method GET -Path "publishers?`$filter=uniquename eq '$PublisherName'"
if ($publishers.value.Count -eq 0) {
    Write-Host "  Creating publisher..."
    $pubBody = @{
        uniquename        = $PublisherName
        friendlyname      = $PublisherName
        customizationprefix = $PublisherPrefix
    }
    Invoke-DataverseApi -Method POST -Path "publishers" -Body $pubBody | Out-Null
    Write-Host "  Publisher created." -ForegroundColor Green
} else {
    Write-Host "  Publisher already exists." -ForegroundColor Yellow
}

# Re-fetch publisher id
$publisher = (Invoke-DataverseApi -Method GET -Path "publishers?`$filter=uniquename eq '$PublisherName'").value[0]
$publisherId = $publisher.publisherid

# ── 2. Create or reuse solution ───────────────────────────────────────────────

Write-Step "Ensuring solution '$SolutionName' exists..."

$solutions = Invoke-DataverseApi -Method GET -Path "solutions?`$filter=uniquename eq '$SolutionName'"
if ($solutions.value.Count -eq 0) {
    Write-Host "  Creating solution..."
    $solBody = @{
        uniquename   = $SolutionName
        friendlyname = $SolutionName
        version      = "1.0.0.0"
        "publisherid@odata.bind" = "/publishers($publisherId)"
    }
    Invoke-DataverseApi -Method POST -Path "solutions" -Body $solBody | Out-Null
    Write-Host "  Solution created." -ForegroundColor Green
} else {
    Write-Host "  Solution already exists." -ForegroundColor Yellow
}

# ── 3. Create tables ──────────────────────────────────────────────────────────

$schemaFiles = Get-ChildItem -Path $TableSchemaDir -Filter "*.json" | Sort-Object Name

foreach ($file in $schemaFiles) {
    $tableDef = Get-Content $file.FullName -Raw | ConvertFrom-Json
    $logicalName = $tableDef.LogicalName
    $displayName = $tableDef.DisplayName.LocalizedLabels[0].Label

    Write-Step "Processing table: $displayName ($logicalName)"

    # Check if table already exists
    $existing = $null
    try {
        $existing = Invoke-DataverseApi -Method GET -Path "EntityDefinitions(LogicalName='$logicalName')"
    } catch {
        $existing = $null
    }

    if ($existing) {
        Write-Host "  Table '$logicalName' already exists. Skipping creation." -ForegroundColor Yellow
    } else {
        Write-Host "  Creating table '$logicalName'..."
        # Build entity payload (strip helper properties not needed by API)
        $entityPayload = $tableDef | Select-Object -Property * -ExcludeProperty Columns, access_source_table, access_primary_keys
        Invoke-DataverseApi -Method POST -Path "EntityDefinitions" -Body $entityPayload | Out-Null
        Write-Host "  Table created." -ForegroundColor Green
    }

    # Create columns
    foreach ($col in $tableDef.Columns) {
        $colLogical = $col.LogicalName
        $colDisplay = $col.DisplayName.LocalizedLabels[0].Label

        # Skip helper props
        $colPayload = $col | Select-Object -Property * -ExcludeProperty access_source_column, access_source_type, is_primary_key_source

        $existingCol = $null
        try {
            $existingCol = Invoke-DataverseApi -Method GET -Path "EntityDefinitions(LogicalName='$logicalName')/Attributes(LogicalName='$colLogical')"
        } catch {
            $existingCol = $null
        }

        if ($existingCol) {
            Write-Host "    Column '$colLogical' already exists. Skipping." -ForegroundColor DarkGray
        } else {
            Write-Host "    Creating column: $colDisplay ($colLogical)"
            try {
                Invoke-DataverseApi -Method POST -Path "EntityDefinitions(LogicalName='$logicalName')/Attributes" -Body $colPayload | Out-Null
                Write-Host "    Column created." -ForegroundColor Green
            } catch {
                Write-Warning "    Failed to create column '$colLogical': $_"
            }
        }
    }
}

# ── 4. Create relationships ───────────────────────────────────────────────────

$relFile = "$PSScriptRoot\..\dataverse\relationships.json"
if (Test-Path $relFile) {
    Write-Step "Creating relationships..."
    $relationships = Get-Content $relFile -Raw | ConvertFrom-Json

    foreach ($rel in $relationships) {
        Write-Host "  Relationship: $($rel.SchemaName)"
        $relPayload = $rel | Select-Object -Property * -ExcludeProperty access_source
        try {
            Invoke-DataverseApi -Method POST -Path "RelationshipDefinitions" -Body $relPayload | Out-Null
            Write-Host "  Created." -ForegroundColor Green
        } catch {
            Write-Warning "  Relationship '$($rel.SchemaName)' may already exist or failed: $_"
        }
    }
}

Write-Host "`n✅ Solution and tables created successfully." -ForegroundColor Green
