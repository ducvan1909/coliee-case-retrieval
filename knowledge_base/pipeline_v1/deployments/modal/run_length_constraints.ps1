param(
    [string]$OutputRoot = "",
    [switch]$InspectLive,
    [switch]$Cpu,
    [ValidateSet("inherited", "candidate", "both")][string]$Arm = "inherited",
    [ValidateSet("all", "host_validated", "bounded", "max_chars", "json_schema")][string]$Variant = "all"
)
$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..\..")).ProviderPath
Set-Location -LiteralPath $repo
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$py = Join-Path $repo ".venv\Scripts\python.exe"
if (-not $OutputRoot) {
    $OutputRoot = "knowledge_base\pipeline_v1\outputs\length_constraints_$(Get-Date -Format yyyyMMdd_HHmmss_fff)"
}
if (Test-Path -LiteralPath $OutputRoot) { throw "Choose a fresh output root; reports are not overwritten." }

& $py -m unittest tests.test_au_length_probe -q
if ($LASTEXITCODE -ne 0) { throw "Local tests failed; no remote operation started." }
& $py -m knowledge_base.pipeline_v1.au_length_probe prepare --output-root "$OutputRoot\prepared"
if ($LASTEXITCODE -ne 0) { throw "Prepare failed." }

if ($InspectLive) {
    & $py -m knowledge_base.pipeline_v1.au_length_probe runtime --output-root "$OutputRoot\runtime"
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Live runtime unavailable; versions remain unknown. No automatic warmup or inference sent."
    }
}
if ($Cpu) {
    $modal = Join-Path $repo ".venv\Scripts\modal.exe"
    & $modal run knowledge_base\pipeline_v1\deployments\modal\length_constraints_cpu.py `
        --arm $Arm --variant $Variant --repeats 2 --output-root "$OutputRoot\cpu"
    if ($LASTEXITCODE -ne 0) { throw "CPU benchmark did not finish; preserve reports at $OutputRoot." }
    $arms = if ($Arm -eq "both") { @("inherited", "candidate") } else { @($Arm) }
    foreach ($name in $arms) {
        $report = Get-Content -LiteralPath "$OutputRoot\cpu\$name.json" -Raw | ConvertFrom-Json
        if ($report.report.status -ne "PASS") {
            throw "CPU $name did not PASS; inspect $OutputRoot. No endpoint acceptance established."
        }
    }
}
Write-Host "Saved: $OutputRoot ; CPU replay is not endpoint inference or AU semantic validation."
