$ErrorActionPreference = "Stop"
Set-Location "c:\TRADING\idx-trading-lab"

if (-not (Get-Command n8n -ErrorAction SilentlyContinue)) {
    throw "n8n command not found. Run scripts/install_n8n_local.ps1 first."
}

$workflowPath = "c:\TRADING\idx-trading-lab\n8n\workflows\idx_trading_daily.json"
if (-not (Test-Path $workflowPath)) {
    throw "Workflow file not found: $workflowPath"
}

$n8nUserFolder = "c:\TRADING\idx-trading-lab\.n8n_local"
New-Item -ItemType Directory -Path $n8nUserFolder -Force | Out-Null
[Environment]::SetEnvironmentVariable("N8N_USER_FOLDER", $n8nUserFolder, "Process")

n8n import:workflow --input $workflowPath
Write-Output "Workflow imported: $workflowPath"
