# Small endpoint test for the formerly truncated JSON; not the full formal suite.
param([string]$OutputRoot = "")
$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..\..")).Path
Set-Location -LiteralPath $repo
$py = Join-Path $repo ".venv\Scripts\python.exe"
if (-not $OutputRoot) {
    $OutputRoot = "knowledge_base\pipeline_v1\outputs\eos_sync_test_$(Get-Date -Format yyyyMMdd_HHmmss)"
}
if (Test-Path -LiteralPath $OutputRoot) { throw "Choose a fresh output directory." }

& $py -m unittest knowledge_base.pipeline_v1.tests.test_eos_sync knowledge_base.pipeline_v1.tests.test_eos_sync_independent -q
if ($LASTEXITCODE -ne 0) { throw "Local EOS sync tests failed; no endpoint request sent." }

& $py -m knowledge_base.pipeline_v1.au_only warmup --execute --output-root "$OutputRoot\warmup"
if ($LASTEXITCODE -ne 0) { throw "Warmup failed; no formal test sent." }

& $py -m knowledge_base.pipeline_v1.deployments.modal.json_diagnostic --output "$OutputRoot\runtime_before.json"
if ($LASTEXITCODE -ne 0) { throw "Runtime inspection failed; no formal test sent." }
$runtime = Get-Content -LiteralPath "$OutputRoot\runtime_before.json" -Raw | ConvertFrom-Json
$stopIds = @($runtime.runtime.active_grammar_stop_set)
if ($runtime.runtime.scheduler.available -ne $true -or $stopIds -notcontains 248044 -or $stopIds -notcontains 248046) {
    throw "Runtime XGrammar stop IDs are not synchronized; inspect runtime_before.json."
}

& $py -m knowledge_base.pipeline_v1.repair_agent formal-suite-probe --execute --max-requests 1 --case-id invalid_reason_int --output-root "$OutputRoot\probe"
if ($LASTEXITCODE -ne 0) { throw "Formerly failing JSON case did not pass; inspect probe artifacts." }
$probe = Get-Content -LiteralPath "$OutputRoot\probe\formal-suite-probe.json" -Raw | ConvertFrom-Json
if ($probe.selected_batch_status -ne "complete" -or $probe.remote_validation_status -ne "pass") {
    throw "Selected case incomplete; this is not an endpoint PASS."
}
Write-Host "EOS SYNC SMALL TEST PASS - $OutputRoot ; full suite and semantics not evaluated."
