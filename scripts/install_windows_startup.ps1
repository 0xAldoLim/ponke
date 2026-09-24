# Install a per-user Startup shortcut; no administrator rights or stored password required.
$ErrorActionPreference = 'Stop'
$startScript = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'start_ponke_windows.ps1')).Path
$startupFolder = [Environment]::GetFolderPath('Startup')
if (-not $startupFolder) { throw 'Windows Startup folder was not found.' }
$linkPath = Join-Path $startupFolder 'Ponke.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($linkPath)
$shortcut.TargetPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$shortcut.Arguments = '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $startScript + '"'
$shortcut.WorkingDirectory = Split-Path -Parent $PSScriptRoot
$shortcut.Description = 'Start Ponke after signing in to Windows'
$shortcut.Save()
Write-Output "Ponke will start after sign-in: $linkPath"
