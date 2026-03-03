$ErrorActionPreference = "Stop"
Set-Location "c:\TRADING\idx-trading-lab"

python -m src.cli recalibrate-volatility --force

