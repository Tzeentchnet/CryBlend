#!/usr/bin/env pwsh
# Build and verify a Blender extension distribution zip end-to-end.

[CmdletBinding()]
param(
    [string]$Blender = "",
    [string]$Repository = "user_default",
    [switch]$SkipTests,
    [switch]$SkipInstallVerify
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$addonId = "cryengine_importer"
$moduleName = "bl_ext.$Repository.$addonId"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message"
}

function Resolve-BlenderPath {
    param([string]$Requested)

    if ($Requested) {
        if (-not (Test-Path -LiteralPath $Requested)) {
            throw "Blender executable not found: $Requested"
        }
        return (Resolve-Path -LiteralPath $Requested).Path
    }

    $cmd = Get-Command blender -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }

    $candidates = @(
        "C:\Program Files\Blender Foundation\Blender 5.1\blender.exe",
        "C:\Program Files\Blender Foundation\Blender 5.0\blender.exe"
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }

    throw "Blender executable not found. Pass -Blender or add blender to PATH."
}

function Get-ManifestVersion {
    $manifestPath = Join-Path $repoRoot "cryengine_importer\blender_manifest.toml"
    $manifestText = Get-Content -LiteralPath $manifestPath -Raw
    if ($manifestText -notmatch '(?m)^version\s*=\s*"([^"]+)"') {
        throw "Could not read extension version from $manifestPath"
    }
    return $Matches[1]
}

function Assert-ExitCode {
    param(
        [int]$Code,
        [string]$Message
    )
    if ($Code -ne 0) {
        throw "$Message (exit code $Code)"
    }
}

function Test-ExtensionZipLayout {
    param([string]$ZipPath)

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [System.IO.Compression.ZipFile]::OpenRead($ZipPath)
    try {
        $entries = @($zip.Entries | ForEach-Object { $_.FullName })
        if ($entries -notcontains "blender_manifest.toml") {
            throw "Distribution zip is invalid: blender_manifest.toml is not at archive root."
        }
        if ($entries -notcontains "__init__.py") {
            throw "Distribution zip is invalid: __init__.py is not at archive root."
        }
        if ($entries -contains "cryengine_importer/blender_manifest.toml") {
            throw "Distribution zip is invalid: nested cryengine_importer/ archive layout detected."
        }
        $badEntry = $entries | Where-Object {
            $_ -match '(^|/)__pycache__/' -or $_ -match '\.(pyc|pyo)$'
        } | Select-Object -First 1
        if ($badEntry) {
            throw "Distribution zip contains cache artifact: $badEntry"
        }
    }
    finally {
        $zip.Dispose()
    }
}

function Invoke-BlenderInstallVerify {
    param(
        [string]$BlenderPath,
        [string]$ZipPath
    )

    Write-Step "Install and enable extension in Blender repository '$Repository'"
    Write-Host "Close running Blender instances for this version before this step; locked extension files can cause WinError 5."
    & $BlenderPath --background --factory-startup --command extension install-file -r $Repository -e $ZipPath
    Assert-ExitCode $LASTEXITCODE "Blender extension install-file failed"

    $verifyScript = Join-Path ([System.IO.Path]::GetTempPath()) ("cryblend_dist_verify_{0}.py" -f [System.Guid]::NewGuid().ToString("N"))
    $verifySource = @"
import addon_utils
import bpy
import importlib
import sys

module_name = "$moduleName"
print("DIST_CHECK module", module_name)
print("DIST_CHECK before", addon_utils.check(module_name))
try:
    addon_utils.enable(module_name, default_set=True, persistent=True)
except Exception as exc:
    print("DIST_CHECK enable_error", repr(exc))
    sys.exit(2)
try:
    module = importlib.import_module(module_name)
except Exception as exc:
    print("DIST_CHECK import_error", repr(exc))
    sys.exit(2)
after = addon_utils.check(module_name)
operator_ok = hasattr(bpy.ops.import_scene, "cryengine")
file_handler_ok = hasattr(bpy.types, "IO_FH_cryengine") or any(
    cls.__name__ == "IO_FH_cryengine"
    for cls in bpy.types.FileHandler.__subclasses__()
)
print("DIST_CHECK after", after)
print("DIST_CHECK module_file", getattr(module, "__file__", ""))
print("DIST_CHECK operator", operator_ok)
print("DIST_CHECK file_handler", file_handler_ok)
bpy.ops.wm.save_userpref()
if not (after[0] and after[1] and operator_ok and file_handler_ok):
    sys.exit(2)
"@

    try {
        Set-Content -LiteralPath $verifyScript -Value $verifySource -Encoding UTF8
        Write-Step "Verify installed module loads as $moduleName"
        & $BlenderPath --background --python $verifyScript
        Assert-ExitCode $LASTEXITCODE "Installed extension verification failed"
    }
    finally {
        if (Test-Path -LiteralPath $verifyScript) {
            Remove-Item -LiteralPath $verifyScript -Force
        }
    }
}

Set-Location $repoRoot

$blenderPath = Resolve-BlenderPath $Blender
$version = Get-ManifestVersion
$zipPath = Join-Path $repoRoot "dist\cryengine_importer-$version.zip"

Write-Step "Using Blender: $blenderPath"

if (-not $SkipTests) {
    Write-Step "Run distribution layout tests"
    python -m pytest tests/parser/test_build_extension.py
    Assert-ExitCode $LASTEXITCODE "Distribution layout tests failed"
}

Write-Step "Build clean extension zip"
python (Join-Path $PSScriptRoot "build_extension.py") --clean
Assert-ExitCode $LASTEXITCODE "Extension build failed"

if (-not (Test-Path -LiteralPath $zipPath)) {
    throw "Expected distribution zip was not created: $zipPath"
}

Write-Step "Inspect archive root layout"
Test-ExtensionZipLayout $zipPath

Write-Step "Validate archive with Blender"
& $blenderPath --background --factory-startup --command extension validate $zipPath
Assert-ExitCode $LASTEXITCODE "Blender extension validation failed"

if (-not $SkipInstallVerify) {
    Invoke-BlenderInstallVerify -BlenderPath $blenderPath -ZipPath $zipPath
}

$zip = Get-Item -LiteralPath $zipPath
Write-Host ""
Write-Host "Distribution ready: $($zip.FullName) ($($zip.Length) bytes)"