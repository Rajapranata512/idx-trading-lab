param(
    [string]$SettingsPath = "config/settings.json",
    [string]$FillsPath = "",
    [int]$LookbackDays = 0
)

$ErrorActionPreference = "Stop"
Set-Location "c:\TRADING\idx-trading-lab"

if (-not (Test-Path $SettingsPath)) {
    throw "Settings file not found: $SettingsPath"
}

$args = @("-m", "src.cli", "--settings", $SettingsPath, "reconcile-live")
if (-not [string]::IsNullOrWhiteSpace($FillsPath)) {
    $args += @("--fills-path", $FillsPath)
}
if ($LookbackDays -gt 0) {
    $args += @("--lookback-days", "$LookbackDays")
}

& python @args
