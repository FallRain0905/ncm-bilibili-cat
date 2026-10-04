[CmdletBinding()]
param(
    [ValidateSet('flac', 'mp3')]
    [string]$Format = 'flac',
    [string]$SourceDir = 'D:\CloudMusic\VipSongsDownload',
    [string]$OutputDir = '',
    [string]$NcmdumpPath = '',
    [string]$FfmpegPath = ''
)

$ErrorActionPreference = 'Stop'
$workspace = $PSScriptRoot

if (-not $NcmdumpPath) {
    $NcmdumpPath = Join-Path $workspace 'ncmdump\tools\ncmdump-1.5.1\ncmdump.exe'
}
if (-not $OutputDir) {
    $OutputDir = Join-Path $workspace "output\$Format"
}
if (-not (Test-Path -LiteralPath $SourceDir -PathType Container)) {
    throw "Source directory does not exist: $SourceDir"
}
if (-not (Test-Path -LiteralPath $NcmdumpPath -PathType Leaf)) {
    throw "ncmdump executable not found: $NcmdumpPath"
}

if ($Format -eq 'mp3' -and -not $FfmpegPath) {
    $bundledFfmpeg = Get-ChildItem -LiteralPath (Join-Path $workspace 'tools') -Filter 'ffmpeg.exe' -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($bundledFfmpeg) {
        $FfmpegPath = $bundledFfmpeg.FullName
    }
}
if ($Format -eq 'mp3' -and -not $FfmpegPath) {
    $ffmpegCommand = Get-Command ffmpeg.exe -ErrorAction SilentlyContinue
    if (-not $ffmpegCommand) {
        $ffmpegCommand = Get-Command ffmpeg -ErrorAction SilentlyContinue
    }
    if ($ffmpegCommand) {
        $FfmpegPath = $ffmpegCommand.Source
    }
}
if ($Format -eq 'mp3' -and (-not $FfmpegPath -or -not (Test-Path -LiteralPath $FfmpegPath -PathType Leaf))) {
    throw 'FFmpeg not found. Install FFmpeg or pass -FfmpegPath.'
}

$sourceRoot = (Resolve-Path -LiteralPath $SourceDir).Path.TrimEnd('\')
$outputRoot = [System.IO.Path]::GetFullPath($OutputDir).TrimEnd('\')
if ($outputRoot.Equals($sourceRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'OutputDir must be different from SourceDir to avoid mixing converted files with downloads.'
}
New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null

$files = @(Get-ChildItem -LiteralPath $sourceRoot -Filter '*.ncm' -File -Recurse)
if ($files.Count -eq 0) {
    Write-Host "No NCM files found in: $sourceRoot"
    exit 0
}

$success = 0
$skipped = 0
$failed = [System.Collections.Generic.List[string]]::new()

foreach ($file in $files) {
    $relativePath = $file.FullName.Substring($sourceRoot.Length).TrimStart('\')
    $relativeDirectory = Split-Path -Parent $relativePath
    $targetDirectory = if ($relativeDirectory) { Join-Path $outputRoot $relativeDirectory } else { $outputRoot }
    New-Item -ItemType Directory -Path $targetDirectory -Force | Out-Null

    $baseName = [System.IO.Path]::GetFileNameWithoutExtension($file.Name)
    $decodedPath = Join-Path $targetDirectory "$baseName.flac"
    $targetPath = if ($Format -eq 'mp3') { Join-Path $targetDirectory "$baseName.mp3" } else { $decodedPath }

    if (Test-Path -LiteralPath $targetPath -PathType Leaf) {
        Write-Host "SKIP  $relativePath (output exists)"
        $skipped++
        continue
    }

    try {
        $ncmdumpArgs = @($file.FullName, '-o', $targetDirectory)
        & $NcmdumpPath @ncmdumpArgs
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $decodedPath -PathType Leaf)) {
            throw "ncmdump failed with exit code $LASTEXITCODE"
        }

        if ($Format -eq 'mp3') {
            & $FfmpegPath '-hide_banner' '-loglevel' 'error' '-n' '-i' $decodedPath '-map_metadata' '0' '-codec:a' 'libmp3lame' '-q:a' '2' $targetPath
            if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $targetPath -PathType Leaf)) {
                throw "FFmpeg failed with exit code $LASTEXITCODE"
            }
            Remove-Item -LiteralPath $decodedPath -Force
        }

        $displayTarget = $targetPath.Substring($outputRoot.Length).TrimStart('\')
        Write-Host "DONE  $relativePath -> $displayTarget"
        $success++
    }
    catch {
        $failed.Add($relativePath)
        Write-Error "FAIL  $relativePath : $($_.Exception.Message)"
    }
}

Write-Host "`nSummary: $success converted, $skipped skipped, $($failed.Count) failed."
if ($failed.Count -gt 0) {
    exit 1
}
