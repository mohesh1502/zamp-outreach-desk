# Outreach Desk — start the console.
#   .\run.ps1            start on http://127.0.0.1:8000
#   .\run.ps1 -Port 8080 start on another port
#   .\run.ps1 -Install   install dependencies first

param(
    [int]$Port = 8000,
    [switch]$Install,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if ($Install) {
    Write-Host "Installing dependencies..." -ForegroundColor Cyan
    python -m pip install -r requirements.txt
}

if (-not (Test-Path ".env")) {
    Write-Host "No .env found. Copy .env.example to .env and add your Gemini key." -ForegroundColor Yellow
    exit 1
}

$url = "http://127.0.0.1:$Port"
Write-Host ""
Write-Host "  Outreach Desk" -ForegroundColor White
Write-Host "  $url" -ForegroundColor Cyan
Write-Host "  Ctrl+C to stop" -ForegroundColor DarkGray
Write-Host ""

if (-not $NoBrowser) {
    Start-Job -ScriptBlock { Start-Sleep -Seconds 2; Start-Process $using:url } | Out-Null
}

python -m uvicorn backend.main:app --host 127.0.0.1 --port $Port
