param(
    [switch]$Execute,
    [string]$OutputRoot = "",
    [int]$Concurrency = 2
)
$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
Set-Location $repo
$py = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $py)) { throw "Thiếu Python trong .venv." }
if ($Concurrency -lt 1 -or $Concurrency -gt 4) { throw "Concurrency phải từ 1 đến 4." }
if (-not $OutputRoot) {
    $OutputRoot = "knowledge_base\pipeline_v1\outputs\evidence_first_$(Get-Date -Format yyyyMMdd_HHmmss_fff)"
}
if (Test-Path -LiteralPath $OutputRoot) { throw "Dùng output root mới; resume bằng CLI run với workload cũ." }
$env:PYTHONIOENCODING = "utf-8"
$summaries = @()
foreach ($profile in @("baseline_v2", "evidence_first_v1")) {
    $root = Join-Path $OutputRoot $profile
    & $py -m knowledge_base.pipeline_v1.au_target_context prepare `
        --prompt-profile $profile --output-root "$root\input"
    if ($LASTEXITCODE -ne 0) { throw "$profile prepare chưa đạt: $root" }
    $workload = "$root\input\workload.json"
    & $py -m knowledge_base.pipeline_v1.au_target_context preflight `
        --workload $workload --output-root "$root\preflight"
    if ($LASTEXITCODE -ne 0) { throw "$profile preflight chưa đạt: $root" }
    if ($Execute) {
        # Chỉ hai TARGET smoke, không tự mở full32 hoặc toàn corpus.
        $mode = "smoke"
        & $py -m knowledge_base.pipeline_v1.au_target_context run `
            --execute --workload $workload --concurrency $Concurrency `
            --target-id act-fa670aae74f627868ebb33f6 `
            --target-id act-4cdccae84ddffa61cb7bb573 `
            --output-root "$root\$mode"
    } else {
        $mode = "mock"
        & $py -m knowledge_base.pipeline_v1.au_target_context run `
            --mock --workload $workload --concurrency $Concurrency --output-root "$root\$mode"
    }
    if ($LASTEXITCODE -ne 0) {
        $failedReport = "$root\$mode\run.json"
        if (Test-Path -LiteralPath $failedReport) {
            $failedRun = Get-Content -LiteralPath $failedReport -Raw -Encoding UTF8 | ConvertFrom-Json
            Write-Host "invalid=$($failedRun.protocol_invalid) failed=$($failedRun.failed) pending=$($failedRun.pending) ; report: $failedReport"
            $receipts = "$root\$mode\receipts"
            if (Test-Path -LiteralPath $receipts) {
                Get-ChildItem -LiteralPath $receipts -Filter '*.json' | ForEach-Object {
                    $receipt = Get-Content -LiteralPath $_.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
                    if ($receipt.status -ne 'verified') {
                        Write-Host "receipt: $($_.FullName) ; error=$($receipt.error) code=$($receipt.error_code)"
                    }
                }
            }
        }
        throw "$profile chưa complete; giữ $root để kiểm tra/resume, không tạo root khác để retry mù."
    }
    $report = Get-Content -LiteralPath "$root\$mode\run.json" -Raw -Encoding UTF8 | ConvertFrom-Json
    $summaries += [ordered]@{
        profile = $profile; report = "$root\$mode\run.json"; status = $report.status
        selected_target_count = $report.selected_target_count
        stage1_requests = $report.stage1_requests; stage2_requests = $report.stage2_requests
        provider_POST_attempts = $report.provider_POST_attempts
        total_provider_usage = $report.total_provider_usage
        elapsed_wall_ms = $report.elapsed_wall_ms
        semantic_quality = "not_assessed"
    }
}
[ordered]@{
    mode = $(if ($Execute) { "live_smoke" } else { "local_mock" })
    semantic_quality = "not_assessed"
    note = "Protocol/mock PASS không chứng minh AU đúng hoặc tiết kiệm. Cần kiểm toàn TARGET kể cả negative/unresolved."
    arms = $summaries
} | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath "$OutputRoot\comparison.json" -Encoding UTF8
Write-Host "Kết quả: $OutputRoot ; semantic review chưa thực hiện."
