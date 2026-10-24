$ErrorActionPreference = 'Stop'
$forgeRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $forgeRoot
uv run python scripts/prepare-model-runtime.py
if ($LASTEXITCODE -ne 0) { throw 'Runtime preparation failed.' }
uv run python scripts/prepare-free-model.py
if ($LASTEXITCODE -ne 0) { throw 'Model preparation failed.' }
$forgeRuntime = Join-Path $forgeRoot '.forge/models/runtime/llama-server.exe'
$forgeModel = Join-Path $forgeRoot '.forge/models/qwen2.5-coder-7b-instruct-q4_k_m.gguf'
& $forgeRuntime --model $forgeModel --alias forge-qwen-coder-7b --host 127.0.0.1 --port 8788 --ctx-size 16384 --parallel 1 --n-gpu-layers 99 --no-webui --log-disable --jinja
