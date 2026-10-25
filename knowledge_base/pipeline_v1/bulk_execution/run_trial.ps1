param(
    [Parameter(Mandatory=$true)][ValidateSet('bulk','corpus')][string]$Arm,
    [Parameter(Mandatory=$true)][string]$EndpointBase,
    [string]$OutputRoot='knowledge_base\pipeline_v1\outputs\bulk_trial30_20261013',
    [switch]$Deploy
)
$ErrorActionPreference='Stop'
Set-Location -LiteralPath (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$py='.\.venv\Scripts\python.exe'
$manifest=Join-Path $OutputRoot 'manifest.json'
$armRoot=Join-Path $OutputRoot $Arm
if ($EndpointBase -notmatch '^https://[a-z0-9-]+--coliee-qwen35-9b-bulk-server\.[a-z0-9.-]+\.modal\.direct/?$') {
    throw 'Use the separate bulk app URL; baseline/concurrency URLs are forbidden.'
}
if (-not (Test-Path -LiteralPath $manifest)) {throw 'Prepare the locked manifest first.'}
if ($Deploy -and ((Test-Path -LiteralPath (Join-Path $OutputRoot 'bulk\execution_identity.json')) -or (Test-Path -LiteralPath (Join-Path $OutputRoot 'corpus\execution_identity.json')))) {
    throw 'Do not redeploy over an active/resumable trial. Resume without -Deploy.'
}
if ($Arm -eq 'corpus') {
    $previous=Join-Path $OutputRoot 'bulk\run.json'
    if (-not (Test-Path -LiteralPath $previous)) {throw 'Run bulk first.'}
    $r=Get-Content -LiteralPath $previous -Raw | ConvertFrom-Json
    if ($r.status -ne 'complete' -or $r.stop_dispatch -or $r.protocol_verified -ne $r.expected_count) {
        throw 'Bulk must complete and pass formal validation before corpus mode.'
    }
}
& $py -m knowledge_base.pipeline_v1.bulk_execution preflight --arm $Arm --manifest $manifest --output-root $OutputRoot
if ($LASTEXITCODE -ne 0) {throw 'Local preflight failed.'}
if ($Deploy) {
    & .\.venv\Scripts\modal.exe deploy knowledge_base\pipeline_v1\deployments\modal\qwen35_9b_bulk.py --strategy recreate
    if ($LASTEXITCODE -ne 0) {throw 'Experimental deployment failed.'}
}
# Capability polling and warmup are integrated; valid checkpoints resume without re-warmup.
& $py -m knowledge_base.pipeline_v1.bulk_execution run --execute --arm $Arm --group-size 16 `
    --url ($EndpointBase.TrimEnd('/')+'/v1/chat/completions') --manifest $manifest --output-root $armRoot
if ($LASTEXITCODE -ne 0) {throw "Run incomplete/error. Preserve $armRoot and resume with the same arguments, without -Deploy."}
if ($Arm -eq 'corpus') {
    & $py -m knowledge_base.pipeline_v1.bulk_execution compare --output-root $OutputRoot
    if ($LASTEXITCODE -ne 0) {throw 'Comparison failed; receipts preserved.'}
}
Write-Host "Results: $armRoot ; protocol PASS does not establish AU semantics or speedup."
