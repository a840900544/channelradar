$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

if (!(Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE) { exit $LASTEXITCODE }
}
$python = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
& $python -m pip install -r requirements.txt
if ($LASTEXITCODE) { exit $LASTEXITCODE }

if (Test-Path -LiteralPath '.env') {
    & $python -m radar.cli migrate
} else {
    & $python -m radar.cli init --local
}
if ($LASTEXITCODE) { exit $LASTEXITCODE }

& $python -m uvicorn radar.api:create_app --factory --host 127.0.0.1 --port 8000
exit $LASTEXITCODE
