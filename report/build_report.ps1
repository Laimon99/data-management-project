$ErrorActionPreference = "Stop"

$reportDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $reportDir
$servicesPath = Join-Path $repoRoot "services"
$previousPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = if ($previousPythonPath) {
    "$servicesPath;$previousPythonPath"
}
else {
    $servicesPath
}

Push-Location $repoRoot
try {
    python -m quality_assessment profile `
        --google-path data/raw/google_places/restaurants_seed.jsonl `
        --tripadvisor-path data/raw/tripadvisor/tripadvisor_scraper_results.json `
        --thefork-path data/raw/thefork/thefork_milan_restaurants_normalized.json `
        --output-dir data/quality `
        --markdown-report docs/data-quality-assessment.md `
        --latex-tables-dir report/tables
    if ($LASTEXITCODE -ne 0) {
        throw "quality_assessment profile failed with exit code $LASTEXITCODE"
    }

    Push-Location $reportDir
    try {
        pdflatex -interaction=nonstopmode -halt-on-error main.tex
        if ($LASTEXITCODE -ne 0) {
            throw "pdflatex failed on first pass with exit code $LASTEXITCODE"
        }
        pdflatex -interaction=nonstopmode -halt-on-error main.tex
        if ($LASTEXITCODE -ne 0) {
            throw "pdflatex failed on second pass with exit code $LASTEXITCODE"
        }
    }
    finally {
        Pop-Location
    }
}
finally {
    $env:PYTHONPATH = $previousPythonPath
    Pop-Location
}
