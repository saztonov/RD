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
    if ($Dev) {
        docker compose @composeFiles @composeArgs @composeProject build @buildArgs web worker
    } else {
        docker compose @composeFiles @composeArgs @composeProject build @buildArgs web worker worker-meta worker-text worker-image worker-stamp
    }
}

if ($Dev) {
    # Dev: universal worker обрабатывает все очереди
    docker compose @composeFiles @composeProject up redis web worker
} else {
    # Production: все specialized workers
    docker compose @composeFiles @composeProject up redis web worker worker-meta worker-text worker-image worker-stamp
}
