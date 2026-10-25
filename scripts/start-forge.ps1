$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
$forgePython = Join-Path (Get-Location) '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $forgePython)) {
    uv sync --extra dev --frozen
    if ($LASTEXITCODE -ne 0) { throw 'Forge dependency setup failed.' }
}
Write-Host 'Starting Forge at http://127.0.0.1:8787. Keep this window open.'
& $forgePython -m forge.cli serve --with-worker
if ($LASTEXITCODE -ne 0) { throw 'Forge stopped. Read the error above.' }
