param(
    [Parameter(Mandatory=$true)][string]$EndpointBase,
    [string]$OutputRoot='knowledge_base\pipeline_v1\outputs\prefix_cache_probe_20261013',
    [switch]$SkipDeploy
)
$ErrorActionPreference='Stop'
Set-Location -LiteralPath (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$py='.\.venv\Scripts\python.exe'
$manifest=Join-Path $OutputRoot 'manifest.json'
if ($EndpointBase -notmatch '^https://[a-z0-9-]+--coliee-qwen35-9b-concurrency-server\.[a-z0-9.-]+\.modal\.direct/?$') {
    throw 'Use the experimental Modal endpoint, never baseline.'
}
if (-not (Test-Path -LiteralPath $manifest)) { throw 'Prepare probe manifest first.' }
if (-not $SkipDeploy -and (Test-Path -LiteralPath (Join-Path $OutputRoot 'probe_identity.json'))) {
    throw 'Probe already started. Use -SkipDeploy to resume; do not recreate running jobs.'
}
& $py -m knowledge_base.pipeline_v1.prefix_cache_probe preflight --manifest $manifest --output-root $OutputRoot
if ($LASTEXITCODE -ne 0) { throw 'Local preflight failed.' }
if (-not $SkipDeploy) {
    $oldSetting=[Environment]::GetEnvironmentVariable('PLX_BENCH_CONCURRENCY','Process')
    try {
        $env:PLX_BENCH_CONCURRENCY='4'
        & .\.venv\Scripts\modal.exe deploy knowledge_base\pipeline_v1\deployments\modal\qwen35_9b_concurrency.py --strategy recreate
        if ($LASTEXITCODE -ne 0) { throw 'Experimental deploy failed.' }
    } finally { [Environment]::SetEnvironmentVariable('PLX_BENCH_CONCURRENCY',$oldSetting,'Process') }
}
& $py -m knowledge_base.pipeline_v1.prefix_cache_probe run --execute --manifest $manifest `
    --url ($EndpointBase.TrimEnd('/')+'/v1/chat/completions') --output-root $OutputRoot
if ($LASTEXITCODE -ne 0) { throw "Probe incomplete/unavailable/error. Inspect $OutputRoot before retrying." }
Write-Host "Cache report ready: $OutputRoot\run.json ; no causal speedup or semantic quality claim."
