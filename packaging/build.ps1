<#
    WinWhispr Windows build script -- THE single entry point for packaging WinWhispr.

    Everything packaging-related lives under packaging/ (this script,
    winwhispr.spec, the PyInstaller runtime hook, and the Inno Setup script) so
    there is exactly one place to look and one command to run.

    Usage (from anywhere; run this script, don't invoke pyinstaller/iscc by hand):
        powershell -File packaging\build.ps1              # build the app bundle
        powershell -File packaging\build.ps1 -Installer    # also build the installer

    Requirements:
        - Python 3.10+ and uv (https://docs.astral.sh/uv/)
        - For -Installer: Inno Setup 6 (iscc.exe on PATH or default install path)

    Models are NOT bundled. They download + optimize into ~/.cache/winwhispr on
    first run (or via "WinWhispr.exe setup", which the installer triggers).

    Output:
        dist\WinWhispr\WinWhispr.exe                        (always)
        packaging\installer\Output\WinWhispr-Setup-*.exe (with -Installer)
#>
[CmdletBinding()]
param(
    [switch]$Installer
)

$ErrorActionPreference = "Stop"

# Resolve the project root (parent of this script's folder: packaging\..).
$PackagingDir = $PSScriptRoot
$ProjectRoot = Split-Path -Parent $PackagingDir
Set-Location $ProjectRoot
Write-Host "[build] Project root: $ProjectRoot"

# 1. Create / sync the virtual environment with runtime deps + PyInstaller.
Write-Host "[build] Installing runtime + build dependencies (incl. PyInstaller)..."
# --extra build pulls PyInstaller as a managed dependency so subsequent syncs
# don't uninstall it (which previously corrupted altgraph mid-build).
uv sync --extra build

# 2. Clean previous build output.
foreach ($dir in @("build", "dist")) {
    if (Test-Path $dir) {
        Write-Host "[build] Removing stale $dir/"
        Remove-Item -Recurse -Force $dir
    }
}

# 3. Build the one-directory bundle. --distpath/--workpath keep output at the
# project root regardless of the spec file living under packaging/.
Write-Host "[build] Running PyInstaller..."
uv run pyinstaller "packaging\winwhispr.spec" --noconfirm --distpath dist --workpath build

$exePath = Join-Path $ProjectRoot "dist\WinWhispr\WinWhispr.exe"
if (-not (Test-Path $exePath)) {
    throw "[build] Build failed: $exePath not found."
}
Write-Host "[build] Bundle ready: $exePath"

# 4. Optionally compile the installer.
if ($Installer) {
    $iss = Join-Path $PackagingDir "installer\winwhispr.iss"
    $iscc = Get-Command iscc.exe -ErrorAction SilentlyContinue
    if ($iscc) {
        $iscc = $iscc.Source
    } else {
        # Inno Setup 6 install locations: machine-wide (x86/x64) and per-user (winget).
        $candidates = @(
            "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
            "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
            "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
        )
        $iscc = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
        if (-not $iscc) {
            throw "[build] Inno Setup (ISCC.exe) not found. Install Inno Setup 6 to build the installer."
        }
    }
    # VERSION is the single source of truth; the installer takes it from there
    # rather than carrying a second copy that drifts.
    $version = (Get-Content (Join-Path $ProjectRoot "VERSION") -Raw).Trim()
    Write-Host "[build] Compiling installer with $iscc (version $version)"
    & $iscc "/DAppVersion=$version" $iss
    Write-Host "[build] Installer written to packaging\installer\Output\"
}

Write-Host "[build] Done."
