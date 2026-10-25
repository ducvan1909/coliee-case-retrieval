param(
    [string]$OutputRoot = "",
    [switch]$Execute,
    [switch]$Full,
    [switch]$EndpointVerified,
    [string]$Workload = "knowledge_base\pipeline_v1\outputs\au_context_paired\implementation_20261014\locked01\workload.json",
    [string]$ReferenceChecklist = "knowledge_base\pipeline_v1\outputs\au_context_paired\implementation_20261014\reference_checklist_locked.v2.json"
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
Set-Location -LiteralPath $repo
$py = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $py)) { throw "Missing repo .venv Python." }
if ($Full -and -not $Execute) { throw "-Full requires -Execute." }
if ($Execute -and -not $EndpointVerified) {
    throw "Plan22 requires actual endpoint model/revision verification. Check Qwen/Qwen3.5-9B revision c202236235762e1c871ad0ccb60c8ee5ba337b9a, then pass -EndpointVerified. No request sent."
}
if (-not $OutputRoot) {
    $stamp = Get-Date -Format yyyyMMdd_HHmmss
    $OutputRoot = "knowledge_base\pipeline_v1\outputs\au_context_paired\pilot_$stamp"
}
$manifest = $Workload
$reference = $ReferenceChecklist
$caps = @("--max-requests", "34", "--max-provider-attempts", "100", "--max-total-input-tokens", "500000", "--max-total-output-tokens", "40000")
$stamp = Get-Date -Format yyyyMMdd_HHmmss_fff
& $py -m knowledge_base.pipeline_v1.au_context_paired preflight --workload $manifest --output-root "$OutputRoot\preflight_$stamp" @caps
if ($LASTEXITCODE -ne 0) { throw "Preflight failed. No inference dispatched." }
if (-not $Execute) {
    & $py -m knowledge_base.pipeline_v1.au_context_paired run --workload $manifest --output-root "$OutputRoot\dry_run" @caps
    if ($LASTEXITCODE -ne 0) { throw "Local dry-run failed." }
    Write-Host "Local check complete. Inference=0. Output: $OutputRoot"
    return
}
& $py -m knowledge_base.pipeline_v1.au_context_paired run --execute --smoke --workload $manifest --reference-checklist $reference --output-root "$OutputRoot\live" @caps
if ($LASTEXITCODE -ne 0) { throw "Smoke incomplete/failed; preserve receipts and inspect $OutputRoot. Do not run full." }
if ($Full) {
    & $py -m knowledge_base.pipeline_v1.au_context_paired run --execute --workload $manifest --reference-checklist $reference --output-root "$OutputRoot\live" @caps
    if ($LASTEXITCODE -ne 0) { throw "Pilot incomplete; preserve same output root for resume: $OutputRoot" }
}
Write-Host "Run saved: $OutputRoot\live\run.json. Semantic review remains pending."
