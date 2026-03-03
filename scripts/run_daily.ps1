$ErrorActionPreference = "Stop"
Set-Location "c:\TRADING\idx-trading-lab"
powershell -ExecutionPolicy Bypass -File "scripts/run_daily_retry.ps1"
