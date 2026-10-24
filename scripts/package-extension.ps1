$ErrorActionPreference = 'Stop'
$forgeProjectRoot = Split-Path -Parent $PSScriptRoot
$forgeOutput = Join-Path $forgeProjectRoot 'dist'
New-Item -ItemType Directory -Path $forgeOutput -Force | Out-Null
Compress-Archive -Path (Join-Path $forgeProjectRoot 'extension/*') -DestinationPath (Join-Path $forgeOutput 'forge-extension-0.1.0.zip') -Force
Write-Output (Join-Path $forgeOutput 'forge-extension-0.1.0.zip')
