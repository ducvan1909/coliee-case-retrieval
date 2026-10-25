# Chỉ kiểm thử hình thức/giao thức; không chạy extraction hoặc sửa AU.
param([string]$OutputRoot = "", [switch]$LocalOnly)
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath "G:\Git\coliee-case-retrieval"
$py = ".\.venv\Scripts\python.exe"
if (-not $OutputRoot) {
    $OutputRoot = "knowledge_base\pipeline_v1\outputs\plan12_formal_$(Get-Date -Format yyyyMMdd_HHmmss)"
}
& $py -m unittest knowledge_base.pipeline_v1.tests.test_repair_decision_relations knowledge_base.pipeline_v1.tests.test_repair_relation_preflight knowledge_base.pipeline_v1.tests.test_repair_boundary_probe knowledge_base.pipeline_v1.tests.test_repair_boundary_probe_independent knowledge_base.pipeline_v1.tests.test_repair_selection knowledge_base.pipeline_v1.tests.test_repair_selection_independent knowledge_base.pipeline_v1.tests.test_repair_formal_probe knowledge_base.pipeline_v1.tests.test_repair_formal_independent knowledge_base.pipeline_v1.tests.test_repair_grammar knowledge_base.pipeline_v1.tests.test_repair_grammar_independent -q
if ($LASTEXITCODE -ne 0) { throw "Local formal tests failed." }
& $py -m knowledge_base.pipeline_v1.repair_agent formal-suite-probe --output-root "$OutputRoot\local"
if ($LASTEXITCODE -ne 0) { throw "Formal suite preparation failed: $OutputRoot" }
$prepared = Get-Content -LiteralPath "$OutputRoot\local\formal-suite-probe.json" -Raw | ConvertFrom-Json
if ($prepared.host_check_status -ne "pass" -or $prepared.selection_check_status -ne "pass") {
    throw "Full-v2 or selection local checks failed: $OutputRoot"
}
if ($LocalOnly) {
    Write-Host "Local formal checks finished; endpoint not tested. Outputs: $OutputRoot"
    return
}
$prepared = Get-Content -LiteralPath "$OutputRoot\local\formal-suite-probe.json" -Raw | ConvertFrom-Json
$ids = @($prepared.remote_cases | ForEach-Object { $_.case_id })
if ($ids.Count -eq 0) { throw "No endpoint cases prepared; refusing an empty PASS." }
& $py -m knowledge_base.pipeline_v1.au_only warmup --execute --output-root "$OutputRoot\warmup"
if ($LASTEXITCODE -ne 0) { throw "Warmup failed: $OutputRoot" }
& $py -m knowledge_base.pipeline_v1.deployments.modal.json_diagnostic --output "$OutputRoot\runtime_before.json"
if ($LASTEXITCODE -ne 0) { throw "Runtime inspection failed: $OutputRoot" }
$runtime = Get-Content -LiteralPath "$OutputRoot\runtime_before.json" -Raw | ConvertFrom-Json
$stopIds = @($runtime.runtime.active_grammar_stop_set)
if ($runtime.runtime.scheduler.available -ne $true -or $stopIds -notcontains 248044 -or $stopIds -notcontains 248046) {
    throw "XGrammar EOS is not synchronized; full suite was not dispatched."
}
$batches = @()
$reportPaths = @()
for ($start = 0; $start -lt $ids.Count; $start += 8) {
    $last = [Math]::Min($start + 7, $ids.Count - 1)
    $batchRoot = "$OutputRoot\batch_$([int]($start / 8) + 1)"
    $cliArgs = @("-m", "knowledge_base.pipeline_v1.repair_agent", "formal-suite-probe",
        "--execute", "--max-requests", "8", "--output-root", $batchRoot)
    foreach ($id in $ids[$start..$last]) { $cliArgs += @("--case-id", $id) }
    & $py @cliArgs
    $code = $LASTEXITCODE
    $reportPath = "$batchRoot\formal-suite-probe.json"
    if (-not (Test-Path -LiteralPath $reportPath)) { throw "Missing batch report: $batchRoot" }
    $report = Get-Content -LiteralPath $reportPath -Raw | ConvertFrom-Json
    $batches += [pscustomobject]@{output = $reportPath; exit_code = $code; report = $report}
    $reportPaths += $reportPath
    # Failures of formal constraints do not hide the remaining cases.
    # Stop if CLI could not construct a valid bounded batch report.
    if ($code -ne 0 -and $code -ne 3) { break }
    if (@($report.cases | Where-Object {
        $_.actual_usage_cap_violation -eq $true -or
        ($_.status -eq 'failed' -and -not $_.receipt) -or
        ($_.receipt -and $null -eq $_.receipt.output)
    }).Count -gt 0) { break }
}
$aggregateArgs = @('-m', 'knowledge_base.pipeline_v1.repair_agent', 'formal-suite-aggregate',
    '--output-root', "$OutputRoot\aggregate")
foreach ($path in $reportPaths) { $aggregateArgs += @('--report', $path) }
& $py @aggregateArgs
$aggregateExitCode = $LASTEXITCODE
$aggregate = [pscustomobject]@{
    scope = "formal_protocol_only"
    semantic_evaluation = "not_performed"
    requested_case_ids = $ids
    warmup_report_root = "$OutputRoot\warmup"
    batches = $batches
    aggregate_report = "$OutputRoot\aggregate\formal-suite-aggregate.json"
    aggregate_exit_code = $aggregateExitCode
    all_batches_completed = ($batches.Count -eq [Math]::Ceiling($ids.Count / 8.0))
    all_batches_passed = (($batches | Where-Object { $_.exit_code -ne 0 }).Count -eq 0)
    note = "Inspect each batch for unrun cases and branch coverage. Warmup cost is reported separately."
}
$aggregate | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath "$OutputRoot\formal-suite-all.json" -Encoding utf8
Write-Host "Formal suite reports: $OutputRoot ; inspect formal-suite-all.json"
if ($aggregateExitCode -ne 0 -or -not $aggregate.all_batches_completed -or -not $aggregate.all_batches_passed) {
    throw "Formal endpoint suite did not PASS. Reports preserved: $OutputRoot"
}
