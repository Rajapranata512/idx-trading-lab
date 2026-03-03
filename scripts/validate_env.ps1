$ErrorActionPreference = "Stop"

function Get-EnvValue {
    param(
        [Parameter(Mandatory = $true)][string]$Name
    )
    $v = [Environment]::GetEnvironmentVariable($Name, "Process")
    if (-not [string]::IsNullOrWhiteSpace($v)) {
        return $v
    }
    $v = [Environment]::GetEnvironmentVariable($Name, "User")
    if (-not [string]::IsNullOrWhiteSpace($v)) {
        return $v
    }
    $v = [Environment]::GetEnvironmentVariable($Name, "Machine")
    if (-not [string]::IsNullOrWhiteSpace($v)) {
        return $v
    }
    return $null
}

function Mask-Secret {
    param([string]$Text)
    if ([string]::IsNullOrEmpty($Text)) {
        return ""
    }
    if ($Text.Length -le 8) {
        return "********"
    }
    return $Text.Substring(0, 4) + "..." + $Text.Substring($Text.Length - 4, 4)
}

$required = @(
    "EODHD_API_TOKEN",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID"
)

$missing = @()
$resolved = @{}

foreach ($name in $required) {
    $value = Get-EnvValue -Name $name
    if ([string]::IsNullOrWhiteSpace($value)) {
        $missing += $name
    }
    else {
        $resolved[$name] = $value
        [Environment]::SetEnvironmentVariable($name, $value, "Process")
    }
}

if ($missing.Count -gt 0) {
    Write-Output ("Missing environment variables: " + ($missing -join ", "))
    exit 1
}

Write-Output ("EODHD_API_TOKEN=" + (Mask-Secret $resolved["EODHD_API_TOKEN"]))
Write-Output ("TELEGRAM_BOT_TOKEN=" + (Mask-Secret $resolved["TELEGRAM_BOT_TOKEN"]))
Write-Output ("TELEGRAM_CHAT_ID=" + $resolved["TELEGRAM_CHAT_ID"])
exit 0
