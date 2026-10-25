# Tám ca giao thức về identity/duplicate; không đánh giá ngữ nghĩa AU.
param([string]$OutputRoot = "", [switch]$LocalOnly)
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath "G:\Git\coliee-case-retrieval"
$py = ".\.venv\Scripts\python.exe"
if (-not $OutputRoot) {
    $OutputRoot = "knowledge_base\pipeline_v1\outputs\plan12_relations_$(Get-Date -Format yyyyMMdd_HHmmss)"
}
& $py -m unittest knowledge_base.pipeline_v1.tests.test_repair_decision_relations knowledge_base.pipeline_v1.tests.test_repair_relation_preflight -q
if ($LASTEXITCODE -ne 0) { throw "Local decision relationship tests failed." }
& $py -m knowledge_base.pipeline_v1.repair_agent formal-suite-probe --output-root "$OutputRoot\local"
if ($LASTEXITCODE -ne 0) { throw "Local formal preparation failed." }
if ($LocalOnly) { return }
& $py -m knowledge_base.pipeline_v1.au_only warmup --execute --output-root "$OutputRoot\warmup"
if ($LASTEXITCODE -ne 0) { throw "Warmup failed." }
& $py -m knowledge_base.pipeline_v1.deployments.modal.json_diagnostic --output "$OutputRoot\runtime_before.json"
if ($LASTEXITCODE -ne 0) { throw "Runtime inspection failed." }
$runtime = Get-Content -LiteralPath "$OutputRoot\runtime_before.json" -Raw | ConvertFrom-Json
$stopIds = @($runtime.runtime.active_grammar_stop_set)
if ($runtime.runtime.scheduler.available -ne $true -or $stopIds -notcontains 248044 -or $stopIds -notcontains 248046) {
    throw "EOS synchronization unverified; no relation probes dispatched."
}
$ids = @('proposal_exact_once', 'duplicate_1_anchor', 'duplicate_2_anchor',
    'duplicate_missing_retained', 'duplicate_replace', 'duplicate_uncertain_anchor',
    'duplicate_cycle', 'nonduplicate_retained')
$cliArgs = @('-m', 'knowledge_base.pipeline_v1.repair_agent', 'formal-suite-probe',
    '--execute', '--max-requests', '8', '--output-root', "$OutputRoot\probe")
foreach ($id in $ids) { $cliArgs += @('--case-id', $id) }
& $py @cliArgs
if ($LASTEXITCODE -ne 0) { throw "Relationship endpoint probe failed; inspect $OutputRoot\probe\formal-suite-probe.json" }
Write-Host "PLAN12 RELATION PROBE PASS - $OutputRoot ; eight formal cases only, AU semantics not evaluated."
