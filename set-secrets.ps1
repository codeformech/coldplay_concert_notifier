# Copies the values from .env into this repo's GitHub Actions secrets.
#
#   .\set-secrets.ps1
#
# Values are piped straight to `gh` and never printed — you'll only see the
# names. Re-run it any time you rotate a key.

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$KEYS = @(
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "TICKETMASTER_API_KEY",
    "ANTHROPIC_API_KEY"
)

if (-not (Test-Path .env)) {
    Write-Host "No .env found in $PSScriptRoot" -ForegroundColor Red
    Write-Host "Copy .env.example to .env and fill it in first."
    exit 1
}

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Write-Host "GitHub CLI (gh) not found. Install it, or add the secrets" -ForegroundColor Red
    Write-Host "by hand: repo -> Settings -> Secrets and variables -> Actions."
    exit 1
}

# Parse .env into a lookup, ignoring comments and blank lines.
$values = @{}
foreach ($line in Get-Content .env) {
    if ($line -match '^\s*#' -or $line -notmatch '=') { continue }
    $parts = $line -split '=', 2
    $name = $parts[0].Trim()
    $value = $parts[1].Trim().Trim('"').Trim("'")
    if ($name) { $values[$name] = $value }
}

$missing = @()
foreach ($key in $KEYS) {
    $value = $values[$key]
    if ([string]::IsNullOrWhiteSpace($value)) {
        Write-Host "  SKIP  $key is empty in .env" -ForegroundColor Yellow
        $missing += $key
        continue
    }
    $value | gh secret set $key
    Write-Host "  set   $key ($($value.Length) chars)" -ForegroundColor Green
}

Write-Host ""
if ($missing.Count -gt 0) {
    Write-Host "Fill these in .env and re-run: $($missing -join ', ')" -ForegroundColor Yellow
    exit 1
}
Write-Host "All four secrets are set. Trigger a run with:" -ForegroundColor Green
Write-Host "  gh workflow run watch.yml"
