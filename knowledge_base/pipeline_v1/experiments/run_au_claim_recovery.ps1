param(
    [switch]$Execute,
    [switch]$Mock,
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
        $OutputRoot = 'knowledge_base\pipeline_v1\outputs\au_claim_recovery_' + (Get-Date -Format 'yyyyMMdd_HHmmss_fff')
    }
    if (-not [IO.Path]::IsPathRooted($OutputRoot)) { $OutputRoot = Join-Path $repo $OutputRoot }
    if (-not [IO.Path]::IsPathRooted($ParentRoot)) { $ParentRoot = Join-Path $repo $ParentRoot }
    Write-Host 'Length is now a warning only. Offline revalidation; no model request, including with Execute.'
    & $py -m knowledge_base.pipeline_v1.au_claim_soft import `
        --parent-root $ParentRoot --output-root $OutputRoot
    if ($LASTEXITCODE -ne 0) { throw "Offline validation failed; use a fresh output root: $OutputRoot" }
    Write-Host "Offline validation output: $OutputRoot ; semantic review not performed."
}
finally { Pop-Location }
