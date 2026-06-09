param(
    [ValidateSet("dry-run", "mock", "openai")]
    [string]$Mode = "dry-run",

    [ValidateSet("tripadvisor", "thefork", "all")]
    [string]$Source = "all",

    [Nullable[int]]$Limit = 10,

    [switch]$NoLimit,
    [switch]$Apply,
    [switch]$Force,
    [string]$OutputJsonl,

    [switch]$SkipPrepareData,
    [switch]$SkipLoad,
    [switch]$SkipClean,
    [switch]$SkipEntityResolve,
    [switch]$SkipTripadvisorGeocode,
    [switch]$NoStartDockerDesktop,

    [int]$DockerTimeoutSeconds = 240,
    [int]$MongoTimeoutSeconds = 90
)

$ErrorActionPreference = "Stop"

function Invoke-Checked {
    param(
        [string]$Label,
        [scriptblock]$Command
    )

    Write-Host ""
    Write-Host "==> $Label"
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE"
    }
}

function Test-DockerReady {
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        docker info *> $null
        return $LASTEXITCODE -eq 0
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
}

function Test-MongoReady {
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        @'
from pymongo import MongoClient

client = MongoClient("mongodb://localhost:27017", serverSelectionTimeoutMS=1000)
client.admin.command("ping")
client.close()
print("mongo-ready")
'@ | uv run python - *> $null
        return $LASTEXITCODE -eq 0
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
}

function Wait-Until {
    param(
        [string]$Label,
        [int]$TimeoutSeconds,
        [scriptblock]$Condition
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (& $Condition) {
            return
        }
        Start-Sleep -Seconds 5
    }
    throw "Timed out waiting for $Label after $TimeoutSeconds seconds"
}

if ($Mode -eq "dry-run" -and $Apply) {
    throw "-Apply is not valid with -Mode dry-run."
}

if ($Mode -eq "openai" -and [string]::IsNullOrWhiteSpace($env:DATAMAN_OPENAI_API_KEY)) {
    throw "DATAMAN_OPENAI_API_KEY is required for -Mode openai."
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir
$dockerDesktopPath = "C:\Program Files\Docker\Docker\Docker Desktop.exe"

Push-Location $repoRoot
try {
    if (-not (Test-DockerReady)) {
        if ($NoStartDockerDesktop) {
            throw "Docker Desktop is not running. Start it manually, then rerun this script."
        }
        if (-not (Test-Path $dockerDesktopPath)) {
            throw "Docker Desktop executable not found at $dockerDesktopPath"
        }

        Write-Host "Starting Docker Desktop..."
        Start-Process -FilePath $dockerDesktopPath -WindowStyle Hidden
        Wait-Until -Label "Docker Desktop" -TimeoutSeconds $DockerTimeoutSeconds -Condition {
            Test-DockerReady
        }
    }

    $existingMongo = docker ps -a --filter "name=^/dataman-mongo$" --format "{{.Names}}"
    if ($existingMongo -eq "dataman-mongo") {
        Invoke-Checked "Start existing MongoDB container" {
            docker start dataman-mongo | Out-Host
        }
    }
    else {
        Invoke-Checked "Start MongoDB with Docker Compose" {
            docker compose up -d mongo
        }
    }

    Wait-Until -Label "MongoDB localhost:27017" -TimeoutSeconds $MongoTimeoutSeconds -Condition {
        Test-MongoReady
    }

    if (-not $SkipPrepareData) {
        if (-not $SkipLoad) {
            Invoke-Checked "Load raw data into MongoDB" {
                uv run dataman-load all
            }
        }

        if (-not $SkipClean) {
            Invoke-Checked "Clean Google data" {
                uv run google-clean
            }

            if ($SkipTripadvisorGeocode) {
                Invoke-Checked "Clean Tripadvisor data without geocoding" {
                    uv run tripadvisor-clean --skip-geocode
                }
            }
            else {
                Invoke-Checked "Clean Tripadvisor data" {
                    uv run tripadvisor-clean
                }
            }

            Invoke-Checked "Clean TheFork data" {
                uv run thefork-clean
            }
        }

        if (-not $SkipEntityResolve) {
            Invoke-Checked "Build deterministic entity-resolution candidates" {
                uv run dataman-entity-resolve --replace-destination
            }
        }
    }

    $pipelineArgs = @(
        "run",
        "dataman-llm-pipeline",
        "--mode",
        $Mode,
        "--source",
        $Source
    )

    if ($Apply) {
        $pipelineArgs += "--apply"
    }
    if ($Force) {
        $pipelineArgs += "--force"
    }
    if (-not $NoLimit -and $null -ne $Limit) {
        $pipelineArgs += @("--limit", [string]$Limit)
    }
    if (-not [string]::IsNullOrWhiteSpace($OutputJsonl)) {
        $pipelineArgs += @("--output-jsonl", $OutputJsonl)
    }

    Invoke-Checked "Run LLM matching pipeline" {
        uv @pipelineArgs
    }
}
finally {
    Pop-Location
}
