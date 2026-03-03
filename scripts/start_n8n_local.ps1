$ErrorActionPreference = "Stop"
Set-Location "c:\TRADING\idx-trading-lab"

function Get-EnvValue {
    param([Parameter(Mandatory = $true)][string]$Name)
    $v = [Environment]::GetEnvironmentVariable($Name, "Process")
    if (-not [string]::IsNullOrWhiteSpace($v)) { return $v }
    $v = [Environment]::GetEnvironmentVariable($Name, "User")
    if (-not [string]::IsNullOrWhiteSpace($v)) { return $v }
    $v = [Environment]::GetEnvironmentVariable($Name, "Machine")
    if (-not [string]::IsNullOrWhiteSpace($v)) { return $v }
    return $null
}

function Ensure-Env {
    $required = @("EODHD_API_TOKEN", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
    $missing = @()
    foreach ($name in $required) {
        $value = Get-EnvValue -Name $name
        if ([string]::IsNullOrWhiteSpace($value)) {
            $missing += $name
        }
        else {
            [Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
    }
    if ($missing.Count -gt 0) {
        throw ("Missing environment variables: " + ($missing -join ", "))
    }
}

if (-not (Get-Command n8n -ErrorAction SilentlyContinue)) {
    throw "n8n command not found. Run scripts/install_n8n_local.ps1 first."
}

Ensure-Env

$repoRoot = "c:\TRADING\idx-trading-lab"
$n8nUserFolder = Join-Path $repoRoot ".n8n_local"
New-Item -ItemType Directory -Path $n8nUserFolder -Force | Out-Null

[Environment]::SetEnvironmentVariable("N8N_HOST", "127.0.0.1", "Process")
[Environment]::SetEnvironmentVariable("N8N_PORT", "5678", "Process")
[Environment]::SetEnvironmentVariable("N8N_PROTOCOL", "http", "Process")
[Environment]::SetEnvironmentVariable("N8N_USER_FOLDER", $n8nUserFolder, "Process")
[Environment]::SetEnvironmentVariable("N8N_DIAGNOSTICS_ENABLED", "false", "Process")
[Environment]::SetEnvironmentVariable("N8N_ENFORCE_SETTINGS_FILE_PERMISSIONS", "true", "Process")
[Environment]::SetEnvironmentVariable("N8N_LOG_LEVEL", "info", "Process")
[Environment]::SetEnvironmentVariable("GENERIC_TIMEZONE", "Asia/Jakarta", "Process")
[Environment]::SetEnvironmentVariable("TZ", "Asia/Jakarta", "Process")
[Environment]::SetEnvironmentVariable("NODES_EXCLUDE", "[]", "Process")

Write-Output "Starting n8n local on http://127.0.0.1:5678"
Write-Output "NODES_EXCLUDE=$([Environment]::GetEnvironmentVariable('NODES_EXCLUDE','Process'))"
n8n
