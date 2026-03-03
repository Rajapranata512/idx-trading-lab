$ErrorActionPreference = "Stop"
Set-Location "c:\TRADING\idx-trading-lab"

$taskName = "IDX_N8N_Local_Startup"
$scriptPath = "c:\TRADING\idx-trading-lab\scripts\start_n8n_background.ps1"
$startupCmdPath = Join-Path ([Environment]::GetFolderPath("Startup")) "IDX_N8N_Local_Startup.cmd"

if (-not (Test-Path $scriptPath)) {
    throw "Script not found: $scriptPath"
}

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`""
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$userId = "$env:USERDOMAIN\$env:USERNAME"
if ([string]::IsNullOrWhiteSpace($env:USERDOMAIN)) {
    $userId = $env:USERNAME
}

# Try highest privileges first. If denied, gracefully fallback to per-user limited run level.
try {
    $principalHighest = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Highest
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principalHighest -Force | Out-Null
    Write-Output "Scheduled task created/updated with RunLevel=Highest: $taskName"
    if (Test-Path $startupCmdPath) {
        Remove-Item $startupCmdPath -Force -ErrorAction SilentlyContinue
    }
}
catch {
    $msg = $_.Exception.Message
    if ($msg -match "Access is denied|0x80070005") {
        try {
            $principalLimited = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited
            Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principalLimited -Force | Out-Null
            Write-Output "Scheduled task created/updated with RunLevel=Limited (no admin): $taskName"
            if (Test-Path $startupCmdPath) {
                Remove-Item $startupCmdPath -Force -ErrorAction SilentlyContinue
            }
        }
        catch {
            $cmd = @(
                "@echo off",
                "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`""
            )
            Set-Content -Path $startupCmdPath -Value $cmd -Encoding ASCII
            Write-Output "ScheduledTask denied for this user. Fallback created in Startup folder:"
            Write-Output $startupCmdPath
        }
    }
    else {
        throw
    }
}
