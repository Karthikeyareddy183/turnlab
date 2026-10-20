$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) { throw 'Create the virtual environment and install the API extras first. See docs/development.md.' }
if (-not (Test-Path -LiteralPath 'web/dist/index.html')) { throw 'Build the frontend first: cd web; npm ci; npm run build.' }
Write-Host 'TurnLab: http://127.0.0.1:8000 (Ctrl+C to stop). Configured Supabase metadata synchronization runs in the background.'
& ./.venv/Scripts/python.exe -m uvicorn turnlab.api:local_app --factory --host 127.0.0.1 --port 8000
exit $LASTEXITCODE
