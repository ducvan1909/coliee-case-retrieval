param(
    [switch]$Execute,
    [switch]$Mock,
    [ValidateRange(1,12)][int]$MaxNewRequests = 12,
    [string]$OutputRoot = 'knowledge_base\pipeline_v1\outputs\k0_authoring_v2_20261025',
    [string]$ControlsRoot = 'knowledge_base\pipeline_v1\outputs\kos_contract_v2_20261024_ready'
)
$ErrorActionPreference = 'Stop'
if ($Execute -and $Mock) { throw 'Execute and Mock are mutually exclusive.' }
$repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../../..')).Path
$py = Join-Path $repo '.venv\Scripts\python.exe'
$native = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python310\python.exe'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
Push-Location $repo
try {
    if (-not [IO.Path]::IsPathRooted($OutputRoot)) { $OutputRoot = Join-Path $repo $OutputRoot }
    if (-not [IO.Path]::IsPathRooted($ControlsRoot)) { $ControlsRoot = Join-Path $repo $ControlsRoot }
    $OutputRoot = [IO.Path]::GetFullPath($OutputRoot)
    $ControlsRoot = [IO.Path]::GetFullPath($ControlsRoot)
    if (-not (Test-Path -LiteralPath (Join-Path $OutputRoot 'input\workload.json'))) {
        & $py -m knowledge_base.pipeline_v1.k0_authoring_v2 prepare --output-root $OutputRoot
        if ($LASTEXITCODE -ne 0) { throw 'K0 v2 prepare failed.' }
    }
    & $py -m knowledge_base.pipeline_v1.k0_authoring_v2 preflight --output-root $OutputRoot
    if ($LASTEXITCODE -ne 0) { throw 'K0 v2 preflight failed; no endpoint call.' }
    $cpuReport = Join-Path $OutputRoot 'cpu_authoring.json'
    if (-not (Test-Path -LiteralPath $cpuReport)) {
        if (-not (Test-Path -LiteralPath $native)) { throw 'Native Python310 is required for local grammar compatibility.' }
        & $native (Join-Path $repo 'knowledge_base\pipeline_v1\experiments\k0_grammar_cpu_probe.py') `
            --bundle (Join-Path $OutputRoot 'input\cpu_authoring.json') --output $cpuReport
        if ($LASTEXITCODE -ne 0) { throw 'Native CPU grammar check failed; no endpoint call.' }
    }
    $options = @('--max-new-requests', "$MaxNewRequests", '--controls-root', $ControlsRoot)
    if ($Execute) { $options += '--execute' }
    if ($Mock) { $options += '--mock' }
    & $py -m knowledge_base.pipeline_v1.k0_authoring_v2 run --output-root $OutputRoot @options
    $runCode = $LASTEXITCODE
    if ($runCode -eq 3 -and ($Execute -or $Mock)) {
        $modeDir = if ($Mock) { 'mock' } else { 'live' }
        $runReport = Get-Content -LiteralPath (Join-Path $OutputRoot "$modeDir\run.json") -Raw | ConvertFrom-Json
        $reasons = @($runReport.pauses.PSObject.Properties | ForEach-Object { $_.Value })
        if ($reasons.Count -gt 0 -and @($reasons | Where-Object { $_ -ne 'invocation_limit' }).Count -eq 0) {
            Write-Host "Deliberate request checkpoint; resume same root: $OutputRoot"
            $global:LASTEXITCODE = 0
            return
        }
    }
    if ($runCode -ne 0) { throw "K0 v2 incomplete or blocked; preserve $OutputRoot for inspection." }
    Write-Host "K0 v2 report: $OutputRoot ; cases partial; semantic quality not assessed."
}
finally { Pop-Location }
