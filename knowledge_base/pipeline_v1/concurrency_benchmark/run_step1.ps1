param(
    [Parameter(Mandatory=$true)][ValidateSet(1,2,4)][int]$Concurrency,
    [Parameter(Mandatory=$true)][string]$EndpointBase,
    [string]$OutputRoot = "knowledge_base\pipeline_v1\outputs\concurrency_step1_20261012",
    [switch]$SkipDeploy
)
$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
Set-Location -LiteralPath $repoRoot
$py = ".\.venv\Scripts\python.exe"
$manifest = Join-Path $OutputRoot "manifest.json"
$armRoot = Join-Path $OutputRoot "c$Concurrency"
if (-not (Test-Path -LiteralPath $manifest)) { throw "Prepare locked manifest first." }
if ($EndpointBase -notmatch '^https://[a-z0-9-]+--coliee-qwen35-9b-concurrency-server\.[a-z0-9.-]+\.modal\.direct/?$') {
    throw "Use the experimental endpoint URL returned by deploy; never the baseline URL."
}
if (-not $SkipDeploy -and (Test-Path -LiteralPath (Join-Path $armRoot 'identity.json'))) {
    throw "Arm already started: use -SkipDeploy to resume without interrupting server jobs."
}
if ($Concurrency -gt 1) {
    $previous = if ($Concurrency -eq 2) { 1 } else { 2 }
    $previousPath = Join-Path $OutputRoot "c$previous\run.json"
    if (-not (Test-Path -LiteralPath $previousPath)) { throw "Run C$previous first." }
    $report = Get-Content -LiteralPath $previousPath -Raw | ConvertFrom-Json
    if ($report.status -ne 'complete' -or -not $report.performance_eligible -or $report.stop_dispatch) {
        throw "Previous arm incomplete/resumed/unknown; inspect it before advancing."
    }
    if ($Concurrency -eq 4) {
        $base = Get-Content -LiteralPath (Join-Path $OutputRoot 'c1\run.json') -Raw | ConvertFrom-Json
        if ($report.protocol_verified -lt $base.protocol_verified -or $report.needs_split -gt $base.needs_split) {
            throw "C2 worsened formal/coverage counts; do not automatically advance to C4."
        }
    }
}
& $py -m knowledge_base.pipeline_v1.concurrency_benchmark preflight --manifest $manifest --output-root $OutputRoot
if ($LASTEXITCODE -ne 0) { throw "Local preflight failed." }
if (-not $SkipDeploy) {
    $previousSetting = [Environment]::GetEnvironmentVariable('PLX_BENCH_CONCURRENCY', 'Process')
    try {
        $env:PLX_BENCH_CONCURRENCY = "$Concurrency"
        & .\.venv\Scripts\modal.exe deploy knowledge_base\pipeline_v1\deployments\modal\qwen35_9b_concurrency.py --strategy recreate
        if ($LASTEXITCODE -ne 0) { throw "Experimental deploy failed." }
    } finally {
        [Environment]::SetEnvironmentVariable('PLX_BENCH_CONCURRENCY', $previousSetting, 'Process')
    }
}
& $py -m knowledge_base.pipeline_v1.concurrency_benchmark run --execute --concurrency $Concurrency `
    --url ($EndpointBase.TrimEnd('/') + '/v1/chat/completions') --manifest $manifest --output-root $armRoot
if ($LASTEXITCODE -ne 0) { throw "C$Concurrency incomplete/error; inspect $armRoot before advancing." }
Write-Host "C$Concurrency saved: $armRoot ; review formal/semantic differences before next step."
