$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
Set-Location $root

# 1) 构建应用（干净重建 dist）
& (Join-Path $root 'build_app.ps1')
if ($LASTEXITCODE -ne 0) { throw 'App build failed.' }

# 2) 定位 Inno Setup 编译器
$candidates = @(
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
)
$iscc = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) {
    throw 'Inno Setup 6 (ISCC.exe) not found. Install with: winget install JRSoftware.InnoSetup'
}

# 3) 编译安装包
& $iscc (Join-Path $root 'installer\installer.iss')
if ($LASTEXITCODE -ne 0) { throw 'Installer compilation failed.' }

$setup = Get-ChildItem (Join-Path $root 'installer') -Filter '*-setup.exe' |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $setup) { throw 'Setup output not found.' }
Write-Host "Installer: $($setup.FullName)"
