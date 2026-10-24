$ErrorActionPreference = 'Stop'
$forgeProjectRoot = Split-Path -Parent $PSScriptRoot
$forgeOutput = Join-Path $forgeProjectRoot 'dist'
New-Item -ItemType Directory -Path $forgeOutput -Force | Out-Null
$forgeManifest = Get-Content -Raw -LiteralPath (Join-Path $forgeProjectRoot 'extension/manifest.json') | ConvertFrom-Json
$forgePackagePath = Join-Path $forgeOutput ("forge-extension-" + $forgeManifest.version + '.zip')
Compress-Archive -Path (Join-Path $forgeProjectRoot 'extension/*') -DestinationPath $forgePackagePath -Force
Get-FileHash -Algorithm SHA256 -LiteralPath $forgePackagePath | ForEach-Object {
    ($_.Hash.ToLowerInvariant() + '  ' + (Split-Path -Leaf $forgePackagePath)) | Set-Content -LiteralPath ($forgePackagePath + '.sha256')
}
Write-Output $forgePackagePath
