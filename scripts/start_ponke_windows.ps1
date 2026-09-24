# Runs at Windows sign-in. Docker's named PostgreSQL volume is deliberately left untouched.
# Docker writes progress to stderr even on success; rely on native exit codes below.
$ErrorActionPreference = 'Continue'
$projectDir = Split-Path -Parent $PSScriptRoot
$dockerExe = Join-Path ${env:ProgramFiles} 'Docker\Docker\resources\bin\docker.exe'
$desktopExe = Join-Path ${env:ProgramFiles} 'Docker\Docker\Docker Desktop.exe'
$logDir = Join-Path $env:LOCALAPPDATA 'Ponke'
$logFile = Join-Path $logDir 'startup.log'

New-Item -ItemType Directory -Path $logDir -Force | Out-Null

function Write-StartupLog([string]$message) {
    Add-Content -LiteralPath $logFile -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $message"
}

try {
    if (-not (Test-Path -LiteralPath $dockerExe)) { throw 'Docker CLI is not installed.' }
    if (-not (Test-Path -LiteralPath $desktopExe)) { throw 'Docker Desktop is not installed.' }
    if (-not (Test-Path -LiteralPath (Join-Path $projectDir '.env'))) {
        throw 'Ponke .env is missing from the project directory.'
    }

    Write-StartupLog 'Waiting for Docker Desktop.'
    if (-not (Get-Process -Name 'Docker Desktop' -ErrorAction SilentlyContinue)) {
        Start-Process -FilePath $desktopExe -WindowStyle Hidden
    }
    $deadline = (Get-Date).AddMinutes(6)
    do {
        & $dockerExe info --format '{{.ServerVersion}}' 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { break }
        Start-Sleep -Seconds 5
    } while ((Get-Date) -lt $deadline)
    if ($LASTEXITCODE -ne 0) { throw 'Docker did not become ready within six minutes.' }

    Push-Location $projectDir
    try {
        & $dockerExe compose up -d --no-build *> $null
        if ($LASTEXITCODE -ne 0) { throw 'docker compose up failed.' }
        $deadline = (Get-Date).AddMinutes(3)
        do {
            $state = & $dockerExe compose ps --format '{{.Service}} {{.Health}}' 2>$null
            if ($state -contains 'app healthy') {
                Write-StartupLog 'Ponke is healthy.'
                exit 0
            }
            Start-Sleep -Seconds 5
        } while ((Get-Date) -lt $deadline)
        throw 'Ponke did not become healthy within three minutes.'
    } finally {
        Pop-Location
    }
} catch {
    Write-StartupLog "Startup failed: $($_.Exception.Message)"
    exit 1
}
