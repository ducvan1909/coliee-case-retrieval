param(
    [switch]$Execute,
    [switch]$ReportOnly,
    [string]$OutputRoot = 'knowledge_base\pipeline_v1\outputs\kos_contract_v2_20261024_ready'
)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '../../..')).Path
$py = Join-Path $repo '.venv\Scripts\python.exe'
$native = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python310\python.exe'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
Push-Location $repo
try {
    if (-not [IO.Path]::IsPathRooted($OutputRoot)) { $OutputRoot = Join-Path $repo $OutputRoot }
    if (-not (Test-Path -LiteralPath (Join-Path $OutputRoot 'input\manifest.json'))) {
        & $py -m knowledge_base.pipeline_v1.kos_authoring_controls_v2 prepare --output-root $OutputRoot
        if ($LASTEXITCODE -ne 0) { throw "Prepare failed; preserve $OutputRoot" }
    }
    & $py -m knowledge_base.pipeline_v1.kos_authoring_controls_v2 preflight --output-root $OutputRoot
    if ($LASTEXITCODE -ne 0) { throw "Preflight failed; no endpoint call. Inspect $OutputRoot" }

    if ($ReportOnly -or ($Execute -and (Test-Path -LiteralPath (Join-Path $OutputRoot 'live\binding.json')))) {
        & $py -m knowledge_base.pipeline_v1.experiments.recover_kos_contract_v2_report --output-root $OutputRoot
        $recoveryCode = $LASTEXITCODE
        if ($recoveryCode -eq 0) {
            Write-Host "Report recovered offline: $OutputRoot\recovered_report\report.json ; no new model request."
            return
        }
        if ($ReportOnly -or $recoveryCode -ne 4) {
            throw "Offline report is incomplete, invalid, or controls failed. Inspect $OutputRoot\recovered_report."
        }
        # Exit 4 means a valid but incomplete checkpoint; explicit Execute may resume.
    }

    $cpuReport = Join-Path $OutputRoot 'cpu_balanced.json'
    if (-not (Test-Path -LiteralPath $cpuReport)) {
        if (-not (Test-Path -LiteralPath $native)) { throw 'Existing native Python310 runtime is required for the CPU grammar check.' }
        & $native knowledge_base\pipeline_v1\experiments\k0_grammar_cpu_probe.py `
            --bundle (Join-Path $OutputRoot 'input\cpu_balanced.json') --output $cpuReport
        if ($LASTEXITCODE -ne 0) { throw "Native grammar check failed; no endpoint call. Inspect $OutputRoot" }
    }
    $options = @()
    if ($Execute) { $options += '--execute' }
    & $py -m knowledge_base.pipeline_v1.kos_authoring_controls_v2 run --output-root $OutputRoot @options
    if ($Execute) {
        # The frozen v2 evaluator can re-normalize numeric config and change its
        # hash. Read persisted binding/receipts directly; never rewrite that binding.
        & $py -m knowledge_base.pipeline_v1.experiments.recover_kos_contract_v2_report --output-root $OutputRoot
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Controls incomplete or failed. Keep this root for inspection/resume: $OutputRoot"
    }
    Write-Host "Report: $OutputRoot ; protocol controls do not establish AU quality. No corpus dispatch."
}
finally { Pop-Location }
