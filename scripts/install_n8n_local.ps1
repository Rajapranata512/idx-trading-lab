$ErrorActionPreference = "Stop"

function Command-Exists {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

Write-Output "== IDX n8n local installer =="

if (-not (Command-Exists "node")) {
    Write-Output "Node.js not found. Installing Node.js LTS via winget..."
    if (-not (Command-Exists "winget")) {
        throw "winget is not available. Install Node.js LTS manually from https://nodejs.org/ first."
    }
    winget install OpenJS.NodeJS.LTS --silent --accept-package-agreements --accept-source-agreements
}

if (-not (Command-Exists "npm")) {
    throw "npm is not available after Node.js install. Re-open terminal and run this script again."
}

Write-Output "Installing/upgrading n8n globally..."
npm install -g n8n

Write-Output "n8n version:"
n8n --version

Write-Output "Installer completed."
