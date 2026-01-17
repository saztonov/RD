param(
    [switch]$Build,
    [switch]$NoCache,
    [switch]$Clean,
    [string]$ProjectName = "rd"
)

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

$composeProject = @("--project-name", $ProjectName)

if ($Clean) {
    docker compose @composeProject down --remove-orphans
}

if ($Build) {
    $composeArgs = @("--progress", "plain")
    $buildArgs = @()
    if ($NoCache) {
        $buildArgs += "--no-cache"
    }
    docker compose @composeArgs @composeProject build @buildArgs web worker
}

docker compose @composeProject up redis web worker
