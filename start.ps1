$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Install Docker Desktop and use Linux containers with the WSL2 backend.' }
docker info *> $null
if ($LASTEXITCODE -ne 0) { throw 'Docker is not running or is not accessible. Start Docker Desktop first.' }
if ((docker info --format '{{.OSType}}') -ne 'linux') { throw 'Switch Docker Desktop to Linux containers.' }
docker compose version
if ($LASTEXITCODE -ne 0) { throw 'Docker Compose v2 is required.' }
. (Join-Path $PSScriptRoot 'scripts/migrate-identities.ps1')
Preserve-NodeIdentities
docker compose up --build -d
if ($LASTEXITCODE -ne 0) { throw 'The build/start failed. Read the Docker output above.' }
Write-Host 'Starting the lab. First launch downloads the required images...'
docker compose exec -T app python /app/wait_ready.py
if ($LASTEXITCODE -ne 0) { throw 'The lab is not ready. The startup error is shown above. Retry this launcher after resolving it.' }
$address = docker compose port app 8080
if ($LASTEXITCODE -ne 0 -or -not $address) { throw 'Could not determine the app address.' }
Write-Host ('Open http://' + $address.Trim())
Write-Host 'Stop without deleting data: docker compose down'
