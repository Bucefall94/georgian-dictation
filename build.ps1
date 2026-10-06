[CmdletBinding()]
param(
    [switch]$Clean
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    python -m venv (Join-Path $ProjectRoot '.venv')
}

& $Python -m pip install --disable-pip-version-check -r (Join-Path $ProjectRoot 'requirements-dev.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }

if ($Clean) {
    $BuildDir = [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot 'build'))
    $DistDir = [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot 'dist'))
    if ($BuildDir.StartsWith($ProjectRoot, [System.StringComparison]::OrdinalIgnoreCase) -and (Test-Path -LiteralPath $BuildDir)) {
        Remove-Item -LiteralPath $BuildDir -Recurse -Force
    }
    if ($DistDir.StartsWith($ProjectRoot, [System.StringComparison]::OrdinalIgnoreCase) -and (Test-Path -LiteralPath $DistDir)) {
        Remove-Item -LiteralPath $DistDir -Recurse -Force
    }
}

Push-Location $ProjectRoot
try {
    & $Python -m pytest
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed.' }

    & $Python -m PyInstaller `
        --noconfirm `
        --clean `
        --windowed `
        --onedir `
        --name GeorgianDictation `
        --collect-data georgian_dictation `
        --hidden-import sounddevice `
        run_app.pyw
    if ($LASTEXITCODE -ne 0) { throw 'Executable build failed.' }

    # PyInstaller may collect the Python runtime's older MSVC DLLs at the
    # application root. PySide6 6.11 requires the newer redistributable shipped
    # in its wheel; keep one compatible set in the DLL search root.
    $QtRuntimeDir = Join-Path $ProjectRoot '.venv\Lib\site-packages\PySide6'
    $BundleRuntimeDir = Join-Path $ProjectRoot 'dist\GeorgianDictation\_internal'
    Get-ChildItem -LiteralPath $QtRuntimeDir -File | Where-Object {
        $_.Name -like 'msvcp140*.dll' -or
        $_.Name -like 'vcruntime140*.dll' -or
        $_.Name -eq 'concrt140.dll' -or
        $_.Name -eq 'vcomp140.dll'
    } | Copy-Item -Destination $BundleRuntimeDir -Force

    # The Codex development PATH can expose a version-suffixed ICU build from
    # unrelated tooling. PyInstaller may collect it as icuuc.dll, while Qt on
    # Windows intentionally links to the OS ICU ABI. Do not ship that foreign
    # DLL; Windows 11 supplies the matching system ICU used by the source app.
    $IcuCandidates = @(
        (Join-Path $BundleRuntimeDir 'icuuc.dll')
    ) + @(Get-ChildItem -LiteralPath $BundleRuntimeDir -Filter 'icudt*.dll' -File -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName })
    foreach ($IcuFile in $IcuCandidates) {
        if ($IcuFile -and (Test-Path -LiteralPath $IcuFile -PathType Leaf)) {
            $ResolvedIcu = [System.IO.Path]::GetFullPath($IcuFile)
            if (-not $ResolvedIcu.StartsWith($BundleRuntimeDir, [System.StringComparison]::OrdinalIgnoreCase)) {
                throw "Refusing to remove ICU outside bundle: $ResolvedIcu"
            }
            Remove-Item -LiteralPath $ResolvedIcu -Force
        }
    }
}
finally {
    Pop-Location
}

$Exe = Join-Path $ProjectRoot 'dist\GeorgianDictation\GeorgianDictation.exe'
if (-not (Test-Path -LiteralPath $Exe -PathType Leaf)) {
    throw "Build completed without expected executable: $Exe"
}
Write-Host "Ready: $Exe"
