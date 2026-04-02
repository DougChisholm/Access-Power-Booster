# auth.ps1
# --------
# Step 3a - Authenticate to Power Platform CLI
#
# Prerequisites:
#   pac (Power Platform CLI) must be installed and on PATH
#   Set DATAVERSE_URL environment variable or pass -Url parameter
#
# Usage:
#   .\auth.ps1
#   .\auth.ps1 -Url "https://yourorg.crm.dynamics.com"

param(
    [string]$Url = $env:DATAVERSE_URL
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $Url) {
    Write-Error "DATAVERSE_URL is not set. Pass -Url or set the environment variable."
    exit 1
}

Write-Host "[auth] Authenticating to: $Url" -ForegroundColor Cyan

# Check if pac is available
if (-not (Get-Command pac -ErrorAction SilentlyContinue)) {
    Write-Error "Power Platform CLI (pac) not found. Install from: https://aka.ms/PowerAppsCLI"
    exit 1
}

# Create or update auth profile for the environment
pac auth create --url $Url

if ($LASTEXITCODE -ne 0) {
    Write-Error "Authentication failed (exit code $LASTEXITCODE)."
    exit $LASTEXITCODE
}

Write-Host "[auth] Authentication successful." -ForegroundColor Green
