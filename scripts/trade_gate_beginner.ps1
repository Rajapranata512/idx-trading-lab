param(
    [switch]$SkipRun,
    [switch]$DebugReasons,
    [string]$SettingsPath = "config/settings.beginner.json"
)

$ErrorActionPreference = "Stop"
Set-Location "c:\TRADING\idx-trading-lab"

& "c:\TRADING\idx-trading-lab\scripts\trade_gate_swing.ps1" `
    -SkipRun:$SkipRun `
    -DebugReasons:$DebugReasons `
    -SettingsPath $SettingsPath `
    -BeginnerSafe
