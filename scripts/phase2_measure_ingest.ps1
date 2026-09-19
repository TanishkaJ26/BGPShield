# Phase 2 acceptance measurement (plan Section 11, Phase 2):
# "one day x all selected collectors ingests on a laptop in < 1 h with < 8 GB RAM
#  (report the real numbers)".
#
# Ingestion can run collectors in separate processes, so memory is sampled across the whole
# process tree, not just the launcher.
param(
    [string]$Date = "2026-09-01",
    [string]$Collectors = "",
    [int]$Jobs = 1
)
$exe = Join-Path $PSScriptRoot "..\.venv\Scripts\bgpshield.exe"
$argList = @("ingest-bgp", "--date", $Date, "--jobs", "$Jobs")
if ($Collectors -ne "") { $argList += @("--collectors", $Collectors) }

$start = Get-Date
$proc = Start-Process -FilePath $exe -ArgumentList $argList -NoNewWindow -PassThru
$rootId = $proc.Id
$peakBytes = 0

function Get-TreeIds([int]$root) {
    $all = Get-CimInstance Win32_Process -Property ProcessId, ParentProcessId
    $ids = New-Object System.Collections.Generic.HashSet[int]
    [void]$ids.Add($root)
    $changed = $true
    while ($changed) {
        $changed = $false
        foreach ($p in $all) {
            if ($ids.Contains([int]$p.ParentProcessId) -and -not $ids.Contains([int]$p.ProcessId)) {
                [void]$ids.Add([int]$p.ProcessId); $changed = $true
            }
        }
    }
    return $ids
}

while (-not $proc.HasExited) {
    $sum = 0
    foreach ($id in (Get-TreeIds $rootId)) {
        try { $sum += (Get-Process -Id $id -ErrorAction Stop).WorkingSet64 } catch {}
    }
    if ($sum -gt $peakBytes) { $peakBytes = $sum }
    Start-Sleep -Seconds 2
}
$elapsed = (Get-Date) - $start
Write-Output ""
Write-Output ("wall clock       : {0:n1} minutes" -f $elapsed.TotalMinutes)
Write-Output ("peak memory tree : {0:n2} GB" -f ($peakBytes / 1GB))
Write-Output ("exit code        : {0}" -f $proc.ExitCode)
