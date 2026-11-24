# Run the offline tests with coverage on Windows, the same way CI does.
# Some research code is Linux-only, so this runs scripts/testing/test_coverage.sh in a Linux
# container. It tests the files in this folder, including changes you haven't committed.
#
#   .\scripts\testing\test_coverage.ps1                # all offline tests + coverage
#   .\scripts\testing\test_coverage.ps1 tests/a_api    # extra arguments go to pytest
#
# Needs Docker Desktop running. Reports: results\coverage\html\index.html, coverage.xml, junit.xml.
# Two timing tests in tests/b_ci and tests/b_dashboard can fail on slower Docker Desktop machines.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$out = Join-Path $root "results\coverage"
New-Item -ItemType Directory -Force -Path $out | Out-Null

$dockerArgs = @(
    "run", "--rm",
    "-v", "${root}:/src:ro",
    "-v", "${out}:/out",
    "-v", "bugzilla-pip-cache:/root/.cache/pip",
    "-e", "COVERAGE_OUT=/out",
    "python:3.11",
    "bash", "/src/scripts/testing/test_coverage.sh", "--container"
) + $args
& docker @dockerArgs
$code = $LASTEXITCODE

Write-Host ""
Write-Host "Coverage report: $out\html\index.html"
exit $code
