param(
    [switch]$Build,
    [switch]$NoCache,
    [switch]$Clean,
    [switch]$Dev,
    [string]$ProjectName = "rd"
)

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

# Compose files: base + dev overlay if -Dev flag
$composeFiles = @("-f", "docker-compose.yml")
if ($Dev) {
    $composeFiles += @("-f", "docker-compose.dev.yml")
    Write-Host "Starting in DEV mode (hot reload enabled)" -ForegroundColor Cyan
}

$composeProject = @("--project-name", $ProjectName)

if ($Clean) {
    Write-Host "Cleaning up containers and logs..." -ForegroundColor Yellow
    docker compose @composeFiles @composeProject down --remove-orphans -v
    docker container prune -f 2>$null
}

if ($Build) {
    $composeArgs = @("--progress", "plain")
    $buildArgs = @()
    if ($NoCache) {
        $buildArgs += "--no-cache"
    }
    docker compose @composeFiles @composeArgs @composeProject build @buildArgs web worker
}

docker compose @composeFiles @composeProject up redis web worker
