$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
& ./.venv/Scripts/python.exe -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Push-Location -LiteralPath web
try { npm run build; $buildExit = $LASTEXITCODE } finally { Pop-Location }
if ($buildExit -ne 0) { exit $buildExit }
& ./.venv/Scripts/python.exe -m turnlab doctor
exit $LASTEXITCODE
