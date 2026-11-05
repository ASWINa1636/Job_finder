# Local AI Job Finder - PowerShell Launcher
$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $scriptDir

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "  Local AI Job Finder - Tkinter Desktop Edition" -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host ""

$pythonCmd = $null
if (Test-Path "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe") {
    $pythonCmd = "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe"
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonCmd = "py"
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonCmd = "python"
}

if ($pythonCmd) {
    & $pythonCmd "app.py"
} else {
    Write-Host "[ERROR] Python 3 not found." -ForegroundColor Red
    Write-Host "Please install Python 3.10+."
    Pause
}

