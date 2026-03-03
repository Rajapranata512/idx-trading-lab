$ErrorActionPreference = "Stop"
Set-Location "c:\TRADING\idx-trading-lab"

python -m src.cli update-event-risk --force
