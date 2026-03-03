$ErrorActionPreference = "Stop"
Set-Location "c:\TRADING\idx-trading-lab"

$scriptPath = "c:\TRADING\idx-trading-lab\scripts\start_n8n_local.ps1"
if (-not (Test-Path $scriptPath)) {
    throw "Script not found: $scriptPath"
}

$before = @(Get-CimInstance Win32_Process -Filter "Name='node.exe'" -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -and $_.CommandLine -match "node_modules[/\\]n8n[/\\]bin[/\\]n8n"
    } | Select-Object -ExpandProperty ProcessId)

$proc = Start-Process -FilePath "powershell.exe" `
    -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $scriptPath `
    -WindowStyle Hidden `
    -PassThru

$nodePid = $null
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Seconds 1
    $after = @(Get-CimInstance Win32_Process -Filter "Name='node.exe'" -ErrorAction SilentlyContinue | Where-Object {
            $_.CommandLine -and $_.CommandLine -match "node_modules[/\\]n8n[/\\]bin[/\\]n8n"
        } | Select-Object -ExpandProperty ProcessId)
    $newPid = $after | Where-Object { $_ -notin $before } | Select-Object -First 1
    if ($newPid) {
        $nodePid = [int]$newPid
        break
    }
}

$stateDir = "c:\TRADING\idx-trading-lab\reports"
New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
$pidPath = Join-Path $stateDir "n8n.pid"
if ($nodePid) {
    Set-Content -Path $pidPath -Value $nodePid -Encoding ASCII
    Write-Output "n8n started in background. node PID=$nodePid (launcher PID=$($proc.Id))"
} else {
    Set-Content -Path $pidPath -Value $proc.Id -Encoding ASCII
    Write-Output "n8n launcher started in background. launcher PID=$($proc.Id)"
    Write-Output "Warning: could not detect n8n node PID automatically."
}

Write-Output "PID file: $pidPath"
