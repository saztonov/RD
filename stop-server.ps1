param(
    [string]$ProjectName = "rd"
)

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

Write-Host "Stopping server..." -ForegroundColor Yellow

# Stop all containers for the project
docker compose --project-name $ProjectName down --remove-orphans

# Clean up stopped containers and their logs
Write-Host "Cleaning up logs..." -ForegroundColor Yellow
docker container prune -f 2>$null

Write-Host "Server stopped and logs cleaned" -ForegroundColor Green
