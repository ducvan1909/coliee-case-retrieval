param(
    [ValidateSet('prepare','preflight','run')][string]$Command = 'preflight',
    [ValidateSet('H','P')][string]$Arm = 'H',
    [string]$Url,
    [string]$OutputRoot = 'knowledge_base/pipeline_v1/outputs/selective_trial30_20261013',
    [string]$Manifest = 'knowledge_base/pipeline_v1/outputs/selective_trial30_20261013/manifest.json',
    [switch]$Execute
)
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '../../..')).Path
Push-Location $repoRoot
try {
    $pythonPath = Join-Path $repoRoot '.venv/Scripts/python.exe'
    $cliArgs = @('-m','knowledge_base.pipeline_v1.selective_reading',$Command,
        '--manifest',$Manifest,'--output-root',$OutputRoot,'--arm',$Arm)
    if ($Command -eq 'run') {
        if (-not $Execute -or -not $Url) { throw 'Main run requires -Execute and -Url of existing private BULK app' }
        $cliArgs += @('--execute','--url',$Url)
    } elseif ($Execute) { throw '-Execute is only valid for run' }
    & $pythonPath @cliArgs
    exit $LASTEXITCODE
} finally { Pop-Location }
