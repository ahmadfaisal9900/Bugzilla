param(
    [ValidateRange(1, 34)]
    [int]$Limit = 34,
    [string]$Model = 'qwen2.5:1.5b-instruct-q4_K_M',
    [string]$SampleBundle = 'data/firefox-sample-seed317-20261102',
    [string]$OutputDirectory = 'outputs/phase06/development-verification',
    [string]$PythonExecutable = '',
    [ValidateRange(1, 600)]
    [int]$TimeoutSeconds = 60,
    [switch]$DryRun,
    [switch]$SkipTests
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$previousPythonPath = $env:PYTHONPATH
Push-Location $repoRoot

function Invoke-Python {
    param([string[]]$Arguments, [string]$LogPath = '')
    $savedPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $lines = @(& $script:python @Arguments 2>&1)
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $savedPreference
    }
    $text = ($lines | ForEach-Object { "$_" }) -join [Environment]::NewLine
    if ($LogPath) {
        Add-Content -LiteralPath $LogPath -Value $text -Encoding UTF8
    }
    if ($exitCode -ne 0) {
        throw "Python failed with exit code $exitCode.$([Environment]::NewLine)$text"
    }
    return $text
}

function Invoke-Method {
    param([string]$Method, [switch]$Preflight)
    $arguments = @('-u', '-m', 'bugzilla_qa.evaluation.phase06', $Method,
                   '--limit', "$Limit", '--output', $script:outputRoot)
    if ($Method -eq 'm0') {
        $arguments += @('--review-bundle', $script:reviewFolder)
    }
    else {
        $arguments += @('--sample-bundle', $SampleBundle)
    }
    if ($Method -ne 'm3') {
        $arguments += @('--model', $Model, '--cpu', '--timeout', "$TimeoutSeconds",
                        '--max-requests', "$Limit")
    }
    if ($Preflight) {
        $arguments += '--dry-run'
        $text = Invoke-Python -Arguments $arguments
    }
    else {
        $arguments += '--resume'
        Write-Host "Running $Method on $Limit development questions..."
        $log = Join-Path $script:outputRoot "$Method.log"
        Add-Content -LiteralPath $log -Value "Started $([DateTime]::UtcNow.ToString('o'))" -Encoding UTF8
        $text = Invoke-Python -Arguments $arguments -LogPath $log
    }
    return $text | ConvertFrom-Json
}

try {
    $env:PYTHONPATH = Join-Path $repoRoot 'src'
    $script:reviewFolder = 'outputs/benchmark/phase05/agent_review/signoff/run-65c5be3381f66811'
    if ([IO.Path]::IsPathRooted($OutputDirectory)) {
        $script:outputRoot = [IO.Path]::GetFullPath($OutputDirectory)
    }
    else {
        $script:outputRoot = [IO.Path]::GetFullPath((Join-Path $repoRoot $OutputDirectory))
    }
    if ($PythonExecutable) {
        $script:python = (Resolve-Path -LiteralPath $PythonExecutable).Path
    }
    else {
        $script:python = Join-Path $repoRoot '.venv/Scripts/python.exe'
        if (!(Test-Path -LiteralPath $script:python)) {
            if ($DryRun) {
                throw 'The Python environment is missing. Run this script without -DryRun to create it.'
            }
            Write-Host 'Creating the Python environment...'
            & python -m venv (Join-Path $repoRoot '.venv')
            if ($LASTEXITCODE -ne 0) { throw 'Python environment setup failed.' }
        }
    }

    try {
        $null = Invoke-Python -Arguments @('-c', 'import duckdb, pytz, pytest')
    }
    catch {
        if ($DryRun) { throw 'Python dependencies are missing. Run without -DryRun to install them.' }
        Write-Host 'Installing the project dependencies...'
        Write-Host (Invoke-Python -Arguments @('-m', 'pip', 'install', '-r', 'requirements.txt', 'pytest'))
    }

    $methods = @('m3', 'm0', 'm3-llm')
    foreach ($method in $methods) {
        $check = Invoke-Method -Method $method -Preflight
        if ($check.state -ne 'DRY_RUN') {
            throw "Input check failed for $method. Missing inputs: $($check.missing_inputs -join ', ')"
        }
        if ($check.questions -lt $Limit) {
            throw "The quiz has $($check.questions) development questions, fewer than the requested $Limit."
        }
    }
    Write-Host "Input checks passed. The quiz has $($check.questions) development questions."
    if ($DryRun) {
        Write-Host "Dry run complete. A real run will attempt $Limit questions per method."
        return
    }

    $models = $null
    try {
        $models = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 5
    }
    catch {
        $ollama = Get-Command ollama -ErrorAction SilentlyContinue
        $ollamaPath = Join-Path $env:LOCALAPPDATA 'Programs/Ollama/ollama.exe'
        if ($ollama) { $ollamaPath = $ollama.Source }
        if (!(Test-Path -LiteralPath $ollamaPath)) {
            throw 'Ollama is unavailable. Open Ollama, then run the same command again.'
        }
        Write-Host 'Starting Ollama...'
        Start-Process -FilePath $ollamaPath -ArgumentList 'serve' -WindowStyle Hidden | Out-Null
        for ($attempt = 0; $attempt -lt 10; $attempt++) {
            Start-Sleep -Seconds 1
            try {
                $models = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2
                break
            }
            catch { }
        }
        if (!$models) { throw 'Ollama did not start. Open Ollama, then rerun the script.' }
    }
    $installed = @($models.models | Where-Object { $_.name -eq $Model })
    if ($installed.Count -ne 1) {
        throw "Model $Model is missing. Install it in Ollama before running this script."
    }

    $hashes = [ordered]@{}
    $files = @('scripts/run_phase06_verify.ps1', 'configs/phase05_sources.json',
               "$script:reviewFolder/signoff_queue.csv", "$script:reviewFolder/REVIEW_BUNDLE.json",
               "$SampleBundle/manifest.json")
    $files += @(Get-ChildItem src/bugzilla_qa/methods, src/bugzilla_qa/evaluation -Filter '*.py' |
                Sort-Object FullName | ForEach-Object { $_.FullName })
    foreach ($file in $files) {
        $hashes[$file] = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash
    }
    $settings = [ordered]@{
        limit = $Limit
        model = $Model
        model_digest = $installed[0].digest
        cpu = $true
        timeout_seconds = $TimeoutSeconds
        sample_bundle = $SampleBundle
        file_hashes = $hashes
    }
    $settingsJson = $settings | ConvertTo-Json -Depth 8 -Compress
    $settingsPath = Join-Path $script:outputRoot 'settings.json'
    if (Test-Path -LiteralPath $settingsPath) {
        $oldSettings = Get-Content -LiteralPath $settingsPath -Raw
        if ($oldSettings.Trim() -ne $settingsJson) {
            throw 'Settings or code changed. Use -OutputDirectory with a new folder to start a new run.'
        }
    }
    New-Item -ItemType Directory -Path $script:outputRoot -Force | Out-Null
    Set-Content -LiteralPath $settingsPath -Value $settingsJson -Encoding UTF8
    Write-Host "Results folder: $script:outputRoot"

    if (!$SkipTests) {
        Write-Host 'Checking the method and practice question tests...'
        $tests = @('-m', 'pytest', '-q', 'tests/test_phase06.py',
                   'tests/test_phase06_generation.py', 'tests/test_phase06_m3_intent.py',
                   'tests/test_phase06_shared_dev.py', 'tests/test_phase05_dev_supplement.py')
        Write-Host (Invoke-Python -Arguments $tests -LogPath (Join-Path $script:outputRoot 'tests.log'))
    }

    $results = @()
    $expectedIds = ''
    foreach ($method in $methods) {
        $report = Invoke-Method -Method $method
        $predictions = @(Get-Content -LiteralPath (Join-Path $report.output 'predictions.jsonl') |
                         ForEach-Object { $_ | ConvertFrom-Json })
        $scores = @(Get-Content -LiteralPath (Join-Path $report.output 'scores.jsonl') |
                    ForEach-Object { $_ | ConvertFrom-Json })
        $ids = @($predictions | ForEach-Object { $_.qid }) -join '|'
        $scoreIds = @($scores | ForEach-Object { $_.qid }) -join '|'
        if ($predictions.Count -ne $Limit -or $scores.Count -ne $Limit -or $ids -ne $scoreIds) {
            throw "$method did not produce $Limit matching answers and scores. See its log."
        }
        if ($expectedIds -and $ids -ne $expectedIds) {
            throw 'The methods used different questions. Check the individual outputs.'
        }
        $expectedIds = $ids
        $results += [pscustomobject]@{
            Method = $method
            Attempted = $predictions.Count
            Correct = @($scores | Where-Object { $_.verdict -eq 'CORRECT' }).Count
            Incorrect = @($scores | Where-Object { $_.verdict -eq 'INCORRECT' }).Count
            NeedsHuman = @($scores | Where-Object { $_.verdict -eq 'NEEDS_HUMAN' }).Count
            Failed = @($predictions | Where-Object { $_.status -ne 'OK' }).Count
            Output = $report.output
        }
    }
    $summary = [ordered]@{
        state = 'COMPLETE'
        finished_at_utc = [DateTime]::UtcNow.ToString('o')
        question_set = 'development'
        requested_per_method = $Limit
        model = $Model
        results = $results
    }
    $summary | ConvertTo-Json -Depth 8 |
        Set-Content -LiteralPath (Join-Path $script:outputRoot 'summary.json') -Encoding UTF8
    $table = $results | Select-Object Method, Attempted, Correct, Incorrect, NeedsHuman, Failed |
             Format-Table -AutoSize | Out-String
    $message = 'Attempted means processed, including failed responses. NeedsHuman requires manual scoring.'
    ($table + $message) | Set-Content -LiteralPath (Join-Path $script:outputRoot 'results.txt') -Encoding UTF8
    Write-Host $table
    Write-Host $message
    Write-Host "Finished. Open $script:outputRoot/results.txt"
}
catch {
    Write-Error $_ -ErrorAction Continue
    exit 1
}
finally {
    $env:PYTHONPATH = $previousPythonPath
    Pop-Location
}
