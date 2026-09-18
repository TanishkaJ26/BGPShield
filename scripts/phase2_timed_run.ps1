# Phase 2 acceptance: one day x all selected collectors, on the laptop, timed, with peak RAM.
# Plan Section 11 Phase 2 asks for the real numbers, so this measures rather than estimates.
#
# The earlier run took 60.2 minutes and missed the one-hour bar by twelve seconds. A probe on
# 2026-09-18 showed the link caps near 230-280 KB/s in AGGREGATE, so parallel collectors buy
# about 1.2x on transfer, not 6x. What they also buy is overlapping the MRT parsing of one
# collector with the download of another, which the serial run could not do.

param(
    [string]$Day = "2026-09-01",
    [int]$Jobs = 6
)

$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$sampleFile = Join-Path $repo "data\processed\phase2_mem_samples.txt"
if (Test-Path $sampleFile) { Remove-Item $sampleFile }

# Sample the whole python/hijax process tree every two seconds.
$sampler = Start-Job -ScriptBlock {
    param($out)
    while ($true) {
        $bytes = (Get-Process -Name python, hijax -ErrorAction SilentlyContinue |
                  Measure-Object -Property WorkingSet64 -Sum).Sum
        if ($bytes) { Add-Content -Path $out -Value $bytes }
        Start-Sleep -Seconds 2
    }
} -ArgumentList $sampleFile

Write-Output "timing: hijax ingest-bgp --date $Day --jobs $Jobs --force"
$started = Get-Date
& "$repo\.venv\Scripts\hijax.exe" ingest-bgp --date $Day --jobs $Jobs --force 2>&1 |
    ForEach-Object { Write-Output $_ }
$code = $LASTEXITCODE
$elapsed = (Get-Date) - $started

Stop-Job $sampler; Remove-Job $sampler

$peak = 0
if (Test-Path $sampleFile) {
    $peak = (Get-Content $sampleFile | Measure-Object -Maximum).Maximum
}

Write-Output ""
Write-Output "=== PHASE 2 ACCEPTANCE ==="
Write-Output ("exit code   : {0}" -f $code)
Write-Output ("wall clock  : {0:N1} minutes" -f $elapsed.TotalMinutes)
Write-Output ("peak RAM    : {0:N2} GB (whole python process tree, 2s sampling)" -f ($peak / 1GB))
Write-Output ("bar         : under 60 minutes and under 8 GB")
$timeOk = $elapsed.TotalMinutes -lt 60
$memOk = ($peak / 1GB) -lt 8
Write-Output ("time        : {0}" -f $(if ($timeOk) { "PASS" } else { "MISS" }))
Write-Output ("memory      : {0}" -f $(if ($memOk) { "PASS" } else { "MISS" }))
