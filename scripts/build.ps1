#!/usr/bin/env pwsh
# Convenience wrapper: build the Blender extension zip into dist/.
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
python (Join-Path $PSScriptRoot "build_extension.py") @args
