$ErrorActionPreference = "Stop"
$taskName = "IDX_N8N_Local_Startup"
$startupCmdPath = Join-Path ([Environment]::GetFolderPath("Startup")) "IDX_N8N_Local_Startup.cmd"
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
if (Test-Path $startupCmdPath) {
    Remove-Item $startupCmdPath -Force -ErrorAction SilentlyContinue
    Write-Output "Startup fallback removed: $startupCmdPath"
}
Write-Output "Scheduled task removed (if existed): $taskName"
