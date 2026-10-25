param(
    [switch]$Execute,
    [switch]$Mock,
    [ValidateRange(0, 12)][int]$MaxNewRequests = 0,
    [string]$OutputRoot,
    [string]$ParentRoot = 'knowledge_base\pipeline_v1\outputs\au_claim_a_local_ready_20261020'
)
$ErrorActionPreference = 'Stop'
if ($Execute -and $Mock) { throw 'Choose Execute or Mock, not both.' }
$repo = (Resolve-Path (Join-Path $PSScriptRoot '../../..')).Path
$py = Join-Path $repo '.venv\Scripts\python.exe'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
Push-Location $repo
try {
    if (-not $OutputRoot) {
        $OutputRoot = 'knowledge_base\pipeline_v1\outputs\k0_' + (Get-Date -Format 'yyyyMMdd_HHmmss_fff')
    }
    if (-not [IO.Path]::IsPathRooted($OutputRoot)) { $OutputRoot = Join-Path $repo $OutputRoot }
    if (-not [IO.Path]::IsPathRooted($ParentRoot)) { $ParentRoot = Join-Path $repo $ParentRoot }
    if (-not (Test-Path -LiteralPath (Join-Path $OutputRoot 'input\workload.json'))) {
        & $py -m knowledge_base.pipeline_v1.k0_authoring prepare --parent-root $ParentRoot --output-root $OutputRoot
        if ($LASTEXITCODE -ne 0) { throw "K0 prepare failed; inspect $OutputRoot" }
    }
    & $py -m knowledge_base.pipeline_v1.k0_authoring preflight --output-root $OutputRoot
    if ($LASTEXITCODE -ne 0) { throw "K0 preflight failed; inspect $OutputRoot" }
    $options = @()
    if ($Execute) { $options += '--execute' }
    if ($Mock) { $options += '--mock' }
    if ($MaxNewRequests -gt 0) { $options += @('--max-new-requests', $MaxNewRequests) }
    & $py -m knowledge_base.pipeline_v1.k0_authoring run --output-root $OutputRoot @options
    $resultCode = $LASTEXITCODE
    $mode = 'dryrun'
    if ($Execute) { $mode = 'live' }
    if ($Mock) { $mode = 'mock' }
    $reportPath = Join-Path $OutputRoot "$mode\run.json"
    if ($resultCode -ne 0) {
        if (($MaxNewRequests -gt 0) -and (Test-Path -LiteralPath $reportPath)) {
            $report = Get-Content -LiteralPath $reportPath -Raw | ConvertFrom-Json
            $reasons = @($report.pauses.PSObject.Properties | ForEach-Object { $_.Value })
            if (($reasons.Count -gt 0) -and (@($reasons | Where-Object { $_ -ne 'invocation_limit' }).Count -eq 0)) {
                Write-Host "K0 smoke checkpoint saved. Resume same OutputRoot without MaxNewRequests: $OutputRoot"
                $global:LASTEXITCODE = 0
                return
            }
        }
        throw "K0 incomplete/blocked; preserve same OutputRoot for inspection: $OutputRoot"
    }
    Write-Host "K0 report: $reportPath ; work scope only, cases remain partial; semantic review pending."
}
finally { Pop-Location }
