# Run the S evaluation with the repository environment on Windows.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location -LiteralPath $projectRoot
$env:PYTHONPATH = Join-Path $projectRoot 'src'
$env:HF_HOME = Join-Path $projectRoot 'models/huggingface'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:LANGSMITH_TRACING = 'false'
$pythonRunner = Join-Path $projectRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonRunner)) { $pythonRunner = 'python' }
& $pythonRunner -m bugzilla_qa.evaluation.experiment @args
exit $LASTEXITCODE
