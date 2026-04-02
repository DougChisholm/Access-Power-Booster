# import-solution.ps1
# -------------------
# Step 3c - Pack and import the Power App solution into Dataverse
#
# Packs the Canvas App source files using pac canvas pack,
# then imports the solution using pac solution import.
#
# Prerequisites:
#   - pac CLI on PATH
#   - Authenticated via auth.ps1
#   - Power App source files in /powerapp/src/
#
# Usage:
#   .\import-solution.ps1
#   .\import-solution.ps1 -SolutionName "AccessMigration" -Async

param(
    [string]$SolutionName   = "AccessMigration",
    [string]$PowerAppSrcDir = "$PSScriptRoot\..\powerapp\src",
    [string]$PowerAppMsapp  = "$PSScriptRoot\..\powerapp\App.msapp",
    [string]$SolutionZip    = "$PSScriptRoot\..\powerapp\AccessMigration_solution.zip",
    [switch]$Async
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step ([string]$msg) {
    Write-Host "`n[import-solution] $msg" -ForegroundColor Cyan
}

# ── Validate ──────────────────────────────────────────────────────────────────

if (-not (Get-Command pac -ErrorAction SilentlyContinue)) {
    Write-Error "pac (Power Platform CLI) not found."
    exit 1
}

if (-not (Test-Path $PowerAppSrcDir)) {
    Write-Error "Power App source directory not found: $PowerAppSrcDir`nRun generate_powerapp.py first."
    exit 1
}

# ── 1. Pack Canvas App ────────────────────────────────────────────────────────

Write-Step "Packing Canvas App sources → $PowerAppMsapp"

pac canvas pack `
    --sources $PowerAppSrcDir `
    --msapp $PowerAppMsapp

if ($LASTEXITCODE -ne 0) {
    Write-Error "pac canvas pack failed."
    exit $LASTEXITCODE
}
Write-Host "  Canvas App packed." -ForegroundColor Green

# ── 2. Add app to solution ────────────────────────────────────────────────────

Write-Step "Creating solution package..."

$solutionDir = "$PSScriptRoot\..\powerapp\solution_src"
New-Item -ItemType Directory -Path $solutionDir -Force | Out-Null

# Create solution.xml
$solutionXml = @"
<?xml version="1.0" encoding="utf-8"?>
<ImportExportXml version="9.0.0.0007" SolutionPackageVersion="9.2" languagecode="1033" generatedBy="CrmLive" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <SolutionManifest>
    <UniqueName>$SolutionName</UniqueName>
    <LocalizedNames>
      <LocalizedName description="$SolutionName" languagecode="1033" />
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
      <!-- type="300" = Canvas App component type in Dataverse solution XML -->
      <!-- id is a placeholder GUID replaced by pac solution import -->
      <RootComponent type="300" id="{00000000-0000-0000-0000-000000000001}" behavior="0" />
    </RootComponents>
    <MissingDependencies />
  </SolutionManifest>
</ImportExportXml>
"@

Set-Content -Path "$solutionDir\solution.xml" -Value $solutionXml -Encoding UTF8

# Create [Content_Types].xml
$contentTypesXml = @"
<?xml version="1.0" encoding="utf-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="xml" ContentType="application/xml" />
  <Default Extension="msapp" ContentType="application/msapp" />
</Types>
"@
Set-Content -Path "$solutionDir\[Content_Types].xml" -Value $contentTypesXml -Encoding UTF8

# Copy msapp into solution
$canvasDir = "$solutionDir\CanvasApps"
New-Item -ItemType Directory -Path $canvasDir -Force | Out-Null
Copy-Item $PowerAppMsapp -Destination "$canvasDir\AccessMigratedApp.msapp" -Force

# Zip the solution
Write-Host "  Zipping solution..."
if (Test-Path $SolutionZip) { Remove-Item $SolutionZip -Force }
Compress-Archive -Path "$solutionDir\*" -DestinationPath $SolutionZip
Write-Host "  Solution zip created: $SolutionZip" -ForegroundColor Green

# ── 3. Import solution ────────────────────────────────────────────────────────

Write-Step "Importing solution into Dataverse..."

$importArgs = @(
    "solution", "import",
    "--path", $SolutionZip,
    "--force-overwrite"
)
if ($Async) {
    $importArgs += "--async"
}

pac @importArgs

if ($LASTEXITCODE -ne 0) {
    Write-Error "pac solution import failed."
    exit $LASTEXITCODE
}

Write-Host "`n✅ Solution imported successfully." -ForegroundColor Green
