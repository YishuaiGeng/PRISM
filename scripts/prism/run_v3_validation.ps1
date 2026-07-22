# Step-5 online validation for the v3 paradigm libraries (PowerShell 5.1).
# Four sequential runs (baseline vs PRISM full, at 3x and 5x scales).
# Sequential on purpose: parallel runs risk API-gateway 524 timeouts.
# Each run is logged to results/prism/logs/ and a failure does not stop the rest.

$ErrorActionPreference = "Continue"
Set-Location (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
New-Item -ItemType Directory -Force results\logs | Out-Null

$MODEL = "GPT-4o-mini"
$DATA_3X = "data/hf/zebralogic/generated_3x_eval_domain_explicit_150.jsonl"
$DATA_5X = "data/hf/zebralogic/generated_5x5_6x5_eval_domain_explicit_100.jsonl"

function Invoke-Run {
    param([string]$Name, [string[]]$PyArgs)
    Write-Host "=== [$Name] start: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===" -ForegroundColor Cyan
    python @PyArgs 2>&1 | Tee-Object -FilePath "results\logs\$Name.log"
    if ($LASTEXITCODE -eq 0) {
        Write-Host "=== [$Name] OK: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===" -ForegroundColor Green
    } else {
        Write-Host "=== [$Name] FAILED (exit $LASTEXITCODE): see results\logs\$Name.log ===" -ForegroundColor Red
    }
}

Invoke-Run "v3_3x_baseline" @(
    "scripts/run_online.py",
    "--data-dir", $DATA_3X, "--data-source", "local", "--model", $MODEL,
    "--no-paradigm", "--no-memory", "--max-repair", "3", "--sizes", "3x3,3x4",
    "--schema-hint-mode", "puzzle",
    "--output", "results/prism/v3_3x_baseline_150.csv"
)

Invoke-Run "v3_3x_full" @(
    "scripts/run_online.py",
    "--data-dir", $DATA_3X, "--data-source", "local", "--model", $MODEL,
    "--library", "paradigm_store/prism_3x_v3.db",
    "--error-library", "paradigm_store/error_3x_v3.db",
    "--max-repair", "3", "--sizes", "3x3,3x4",
    "--schema-hint-mode", "puzzle",
    "--output", "results/prism/v3_3x_full_150.csv"
)

Invoke-Run "v3_5x_baseline" @(
    "scripts/run_online.py",
    "--data-dir", $DATA_5X, "--data-source", "local", "--model", $MODEL,
    "--no-paradigm", "--no-memory", "--max-repair", "3", "--sizes", "5x5,6x5",
    "--schema-hint-mode", "puzzle", "--translation-normalize", "initial",
    "--output", "results/prism/v3_5x_baseline_100.csv"
)

Invoke-Run "v3_5x_full" @(
    "scripts/run_online.py",
    "--data-dir", $DATA_5X, "--data-source", "local", "--model", $MODEL,
    "--library", "paradigm_store/prism_5x6x_v3.db",
    "--error-library", "paradigm_store/error_5x6x_v3.db",
    "--max-repair", "3", "--sizes", "5x5,6x5",
    "--schema-hint-mode", "puzzle", "--translation-normalize", "initial",
    "--output", "results/prism/v3_5x_full_100.csv"
)

Write-Host ""
Write-Host "=== All runs finished: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ==="
Write-Host "--- Quick summary (solved counts) ---"
python -c @'
import csv, glob
for f in sorted(glob.glob("results/prism/v3_*_1?0.csv")):
    with open(f, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        print(f + ": empty"); continue
    solved = sum(1 for r in rows if str(r.get("solved")).lower() == "true")
    pos = sum(1 for r in rows if str(r.get("positive_guidance_triggered")).lower() == "true")
    err = sum(1 for r in rows if str(r.get("error_guidance_triggered")).lower() == "true")
    print(f"{f}: {solved}/{len(rows)} solved | positive_triggered={pos} | error_triggered={err}")
'@
