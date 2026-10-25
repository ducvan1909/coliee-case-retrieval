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
    $OutputRoot = "knowledge_base\pipeline_v1\outputs\au_claim_$(Get-Date -Format yyyyMMdd_HHmmss_fff)"
}
$workload = Join-Path $OutputRoot "input\workload.json"
if (-not (Test-Path -LiteralPath $workload)) {
    if (Test-Path -LiteralPath $OutputRoot) { throw "Existing root has no workload; inspect it before retrying." }
    & $py -m knowledge_base.pipeline_v1.au_claim prepare --output-root "$OutputRoot\input"
    if ($LASTEXITCODE -ne 0) { throw "Prepare failed: $OutputRoot" }
}
$checkRoot = Join-Path $OutputRoot "preflight_$(Get-Date -Format yyyyMMdd_HHmmss_fff)"
& $py -m knowledge_base.pipeline_v1.au_claim preflight --workload $workload --output-root $checkRoot
if ($LASTEXITCODE -ne 0) { throw "Preflight failed; no extraction dispatched: $checkRoot" }
$mode = if ($Execute) { "live" } else { "mock" }
$runRoot = Join-Path $OutputRoot $mode
if ($Execute) {
    & $py -m knowledge_base.pipeline_v1.au_claim run --execute `
        --workload $workload --concurrency $Concurrency --output-root $runRoot
} else {
    & $py -m knowledge_base.pipeline_v1.au_claim run --mock `
        --workload $workload --concurrency $Concurrency --output-root $runRoot
}
$runExit = $LASTEXITCODE
if (Test-Path -LiteralPath "$runRoot\run.json") {
    $comparison = Join-Path $OutputRoot "comparison_${mode}_$(Get-Date -Format yyyyMMdd_HHmmss_fff)"
    & $py -m knowledge_base.pipeline_v1.au_claim compare `
        --workload $workload --run "$runRoot\run.json" --output-root $comparison
    if ($LASTEXITCODE -ne 0) { throw "Comparison failed: $comparison" }
    Write-Host "Comparison: $comparison ; semantic review remains pending."
}
if ($runExit -ne 0) { throw "Run incomplete; preserve $OutputRoot for inspection/resume." }
Write-Host "Results: $OutputRoot ; mode=$mode. Protocol success does not establish AU quality."
