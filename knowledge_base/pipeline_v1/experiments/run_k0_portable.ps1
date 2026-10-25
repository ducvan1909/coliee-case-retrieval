param(
    [ValidateSet('export','inspect','prepare','preflight','run')][string]$Command = 'run',
    [string]$RepoRoot = '',
    [string]$Bundle = 'knowledge_base/pipeline_v1/research_snapshots/k0_portable_20261025',
    [string]$OutputRoot = 'research_bundle/k0_portable_runs/current',
    [string]$Python = $env:K0_PYTHON,
    [string]$NativePython = $env:K0_NATIVE_PYTHON,
    [switch]$Execute,
    [switch]$Mock,
    [switch]$CheckRuntime,
    [ValidateRange(1,12)][int]$MaxNewRequests = 12
)
$ErrorActionPreference = 'Stop'
if ($Execute -and $Mock) { throw 'Execute and Mock are mutually exclusive.' }
if ($Command -ne 'run' -and ($Execute -or $Mock)) { throw 'Execution flags require run.' }
if (-not $RepoRoot) { $RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../..')) }
if (-not $Python) {
    $Python = Join-Path $RepoRoot '.venv/Scripts/python.exe'
    if (-not (Test-Path -LiteralPath $Python)) { $Python = Join-Path $RepoRoot '.venv/bin/python' }
}
$env:PYTHONUTF8 = '1'
Push-Location $RepoRoot
try {
    $common = @('--repo-root', $RepoRoot, '--bundle', $Bundle, '--output-root', $OutputRoot)
    if ($Command -eq 'run') {
        if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot "$OutputRoot/input/workload.json"))) {
            & $Python -m knowledge_base.pipeline_v1.k0_portable prepare @common
            if ($LASTEXITCODE -ne 0) { throw 'Portable prepare failed.' }
        }
        & $Python -m knowledge_base.pipeline_v1.k0_portable preflight @common
        if ($LASTEXITCODE -ne 0) { throw 'Portable preflight failed.' }
        if ($Execute -and -not (Test-Path -LiteralPath (Join-Path $RepoRoot "$OutputRoot/cpu_authoring.json"))) {
            if (-not $NativePython) { throw 'Supply -NativePython or K0_NATIVE_PYTHON for local XGrammar CPU probe.' }
            & $NativePython -m knowledge_base.pipeline_v1.k0_portable.cpu --repo-root $RepoRoot `
                --bundle "$OutputRoot/input/cpu_authoring.json" --output "$OutputRoot/cpu_authoring.json"
            if ($LASTEXITCODE -ne 0) { throw 'Portable CPU gate failed.' }
        }
        $options = @('--max-new-requests', "$MaxNewRequests")
        if ($Execute) { $options += '--execute' }
        if ($Mock) { $options += '--mock' }
        & $Python -m knowledge_base.pipeline_v1.k0_portable run @common @options
    } else {
        $options = @()
        if ($CheckRuntime) { $options += '--check-runtime' }
        & $Python -m knowledge_base.pipeline_v1.k0_portable $Command @common @options
    }
    $code = $LASTEXITCODE
} finally { Pop-Location }
exit $code
