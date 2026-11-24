# Start the API, the chat UI and the dashboard from your venv, all in this one terminal.
# Ctrl+C stops all three.
#
#   .\scripts\app\run_local.ps1                 # API + chat + dashboard
#   .\scripts\app\run_local.ps1 -NoDashboard    # API + chat only
#
# Uses serving_bundle\ and the keys in .env (GROQ_API_KEY, SERVING_API_KEY, ...).
# One-time setup:  python -m venv .venv  then  .venv\Scripts\pip install ".[serving,ui,dashboard]"
param([switch]$NoDashboard)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "No .venv found in $root. Create it and run: .venv\Scripts\pip install "".[serving,ui,dashboard]"""
}
if (-not (Test-Path (Join-Path $root "serving_bundle\manifest.json"))) {
    throw "serving_bundle\ is missing or incomplete in $root."
}

$env:PYTHONPATH = "src"
if (-not $env:BUNDLE_DIR) { $env:BUNDLE_DIR = "serving_bundle" }
$env:DASHBOARD_LAB_ENABLED = "false"
# The API and the chat both read SERVING_API_KEY from .env. A stale copy in this terminal
# would make them disagree (HTTP 401), so drop it.
Remove-Item Env:SERVING_API_KEY -ErrorAction SilentlyContinue
# Test settings left in this terminal (e.g. LLM_PROVIDER=mock from a pytest run) would make
# the API skip Groq and abstain on every question, so drop them too.
foreach ($name in "LLM_PROVIDER", "LANGSMITH_SOURCE") {
    Remove-Item "Env:$name" -ErrorAction SilentlyContinue
}

# An API or Streamlit left running from an earlier session would answer instead of the new one
# (with stale code), so refuse to start until those ports are free.
$ports = @(8000, 8501)
if (-not $NoDashboard) { $ports += 8502 }
$busy = Get-NetTCPConnection -LocalPort $ports -State Listen -ErrorAction SilentlyContinue
if ($busy) {
    foreach ($connection in $busy) {
        $owner = Get-Process -Id $connection.OwningProcess -ErrorAction SilentlyContinue
        Write-Host ("Port {0} is in use by {1} (PID {2})." -f $connection.LocalPort, $owner.ProcessName, $connection.OwningProcess)
    }
    Write-Host "Stop those first, e.g.:"
    Write-Host "  Get-NetTCPConnection -LocalPort $($ports -join ',') -State Listen | ForEach-Object { Stop-Process -Id `$_.OwningProcess -Force }"
    exit 1
}

function Start-Part([string]$arguments) {
    Start-Process -FilePath $python -ArgumentList $arguments -NoNewWindow -PassThru
}

$parts = @()
try {
    $parts += Start-Part "-m uvicorn bugzilla_serving.api.app:app --host 127.0.0.1 --port 8000"
    Write-Host "Starting the API on http://127.0.0.1:8000 ..."
    $deadline = (Get-Date).AddMinutes(4)
    while ($true) {
        try {
            Invoke-WebRequest "http://127.0.0.1:8000/v1/health" -UseBasicParsing -TimeoutSec 3 | Out-Null
            break
        } catch {
            if ($parts[0].HasExited) { throw "The API stopped while starting; see its output above." }
            if ((Get-Date) -gt $deadline) { throw "The API did not answer within 4 minutes." }
            Start-Sleep -Seconds 2
        }
    }

    $streamlit = "-m streamlit run {0} --server.port {1} --server.headless true"
    $parts += Start-Part ($streamlit -f "src/bugzilla_serving/chat_ui/app.py", 8501)
    if (-not $NoDashboard) {
        $parts += Start-Part ($streamlit -f "src/bugzilla_serving/dashboard/app.py", 8502)
    }

    Write-Host ""
    Write-Host "Chat:      http://localhost:8501"
    if (-not $NoDashboard) { Write-Host "Dashboard: http://localhost:8502" }
    Write-Host "Press Ctrl+C to stop everything."
    Write-Host ""
    Wait-Process -Id ($parts | ForEach-Object { $_.Id })
} finally {
    foreach ($part in $parts) {
        if (-not $part.HasExited) { Stop-Process -Id $part.Id -Force -ErrorAction SilentlyContinue }
    }
}
