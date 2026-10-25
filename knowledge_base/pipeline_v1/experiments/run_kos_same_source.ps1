param(
    [switch]$Execute,
    [string]$OutputRoot = "",
    [ValidateRange(1,4)][int]$Concurrency = 2
)
$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).ProviderPath
Set-Location $repo
$py = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $py)) { throw "Missing .venv Python." }
$env:PYTHONIOENCODING = "utf-8"
if (-not $OutputRoot) {
    $OutputRoot = "knowledge_base\pipeline_v1\outputs\kos_same_source_$(Get-Date -Format yyyyMMdd_HHmmss_fff)"
}
$workload = Join-Path $OutputRoot "input\workload.json"
$checklist = Join-Path $OutputRoot "input\reference_checklist.json"
if (-not (Test-Path -LiteralPath $workload)) {
    if (Test-Path -LiteralPath $OutputRoot) { throw "Existing root has no workload; inspect it before retrying." }
    & $py -m knowledge_base.pipeline_v1.au_target_context.kos_aligned prepare `
        --output-root "$OutputRoot\input"
    if ($LASTEXITCODE -ne 0) { throw "Prepare failed: $OutputRoot" }
}
# A new report directory permits repeat validation without overwriting the lock.
$preflight = Join-Path $OutputRoot "preflight_$(Get-Date -Format yyyyMMdd_HHmmss_fff)"
& $py -m knowledge_base.pipeline_v1.au_target_context.kos_aligned preflight `
    --workload $workload --output-root $preflight
if ($LASTEXITCODE -ne 0) { throw "Preflight failed; no extraction dispatched: $preflight" }
$mode = if ($Execute) { "live" } else { "mock" }
$runRoot = Join-Path $OutputRoot $mode
if ($Execute) {
    & $py -m knowledge_base.pipeline_v1.au_target_context.kos_aligned run `
        --execute --workload $workload --concurrency $Concurrency --output-root $runRoot
} else {
    & $py -m knowledge_base.pipeline_v1.au_target_context.kos_aligned run `
        --mock --workload $workload --concurrency $Concurrency --output-root $runRoot
}
$runExit = $LASTEXITCODE
if (Test-Path -LiteralPath "$runRoot\run.json") {
    $comparisonRoot = Join-Path $OutputRoot "comparison_${mode}_$(Get-Date -Format yyyyMMdd_HHmmss_fff)"
    & $py -m knowledge_base.pipeline_v1.au_target_context.kos_aligned compare `
        --workload $workload --reference-checklist $checklist `
        --run "$runRoot\run.json" --output-root $comparisonRoot
    if ($LASTEXITCODE -ne 0) { throw "Comparison failed: $comparisonRoot" }
    Write-Host "Comparison: $comparisonRoot ; semantic review remains pending."
}
if ($runExit -ne 0) { throw "Run incomplete; preserve $OutputRoot and resume with the same -OutputRoot." }
Write-Host "Results: $OutputRoot ; mode=$mode. Mock does not assess AU quality."
