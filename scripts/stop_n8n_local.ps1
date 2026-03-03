$ErrorActionPreference = "Stop"
Set-Location "c:\TRADING\idx-trading-lab"

$pidPath = "c:\TRADING\idx-trading-lab\reports\n8n.pid"
if (-not (Test-Path $pidPath)) {
    Write-Output "PID file not found: $pidPath"
    Write-Output "Trying to stop by process name..."
    $nodeProcesses = Get-CimInstance Win32_Process -Filter "Name='node.exe'" -ErrorAction SilentlyContinue
    foreach ($p in $nodeProcesses) {
        if ($p.CommandLine -and ($p.CommandLine -match "node_modules[/\\]n8n[/\\]bin[/\\]n8n" -or $p.CommandLine -match "task-runner[/\\]dist[/\\]start.js")) {
            try {
                Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
                Write-Output "Stopped node process PID=$($p.ProcessId) for n8n"
            }
            catch { }
        }
    }
    exit 0
}

$pidValue = (Get-Content $pidPath -Raw).Trim()
$pidInt = 0
if (-not [int]::TryParse($pidValue, [ref]$pidInt)) {
    Remove-Item $pidPath -Force -ErrorAction SilentlyContinue
    throw "Invalid PID file content."
}

$proc = Get-Process -Id $pidInt -ErrorAction SilentlyContinue
if ($null -eq $proc) {
    Write-Output "Process in PID file not found. Will stop n8n by scan."
}
else {
    Stop-Process -Id $proc.Id -Force
    Write-Output "Stopped process PID=$($proc.Id) from PID file."
}

# Also stop related n8n node/task-runner processes that may survive launcher termination.
$nodeProcesses = Get-CimInstance Win32_Process -Filter "Name='node.exe'" -ErrorAction SilentlyContinue
foreach ($p in $nodeProcesses) {
    if ($p.CommandLine -and ($p.CommandLine -match "node_modules[/\\]n8n[/\\]bin[/\\]n8n" -or $p.CommandLine -match "task-runner[/\\]dist[/\\]start.js")) {
        try {
            Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
            Write-Output "Stopped node process PID=$($p.ProcessId) for n8n"
        }
        catch { }
    }
}

Remove-Item $pidPath -Force -ErrorAction SilentlyContinue
Write-Output "n8n stop sequence completed."
