$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
Set-Location $root

python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller dependency installation failed.' }

Remove-Item -Recurse -Force -ErrorAction SilentlyContinue build, dist
python -m PyInstaller --clean --noconfirm 'NCMConverter.spec'
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }

$app = Get-ChildItem (Join-Path $root 'dist') -Directory | Select-Object -First 1
if (-not $app) { throw 'PyInstaller output directory not found.' }
$internalBin = Join-Path $app.FullName '_internal\bin'
foreach ($tool in 'ncmdump.exe', 'ffmpeg.exe', 'ffprobe.exe') {
    if (-not (Test-Path (Join-Path $internalBin $tool))) {
        throw "Missing bundled tool: $tool"
    }
}
$exe = Get-ChildItem $app.FullName -Filter '*.exe' | Select-Object -First 1
Write-Host "Built: $($exe.FullName)"
