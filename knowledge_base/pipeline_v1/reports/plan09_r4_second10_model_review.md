# Plan09 R4 — 099980 second ten missing targets

Ngày 2026-10-05. Reviewer/provenance gpt-6.1-sol low; model-only/model-silver. Không independent audit, không R5 acceptance. Canonical artifact là `ModelAUProposal`, không phải Terra output.

## Kết quả

Đúng 10 target đầu trong missing_target_ids hiện tại sau batch first10, theo thứ tự ổn định. Batch: 2 AU / 7 hard-negative / 1 unresolved. Coverage tăng 222 → 232 / 369; missing giảm đúng 147 → 137. Effective counts: 104 AU / 126 hard negatives / 2 unresolved.

218 artifact hashes của cohort đã có/first10/R3 được giữ nguyên, gồm proposal, sidecar, amendment, risk reviews, registry history, accepted R3, first10 frozen batch và reports. Các first10 manifest records giữ nguyên, chỉ append ten records mới vào R4 manifest. Không review/sửa lại 222 target cũ; không chọn target thứ 11 trong turn này. R3 vẫn PASS ở cohort accepted cũ; R4 vẫn incomplete, R5 chưa PASS, Plan10 false.

## Exact targets và decisions

Raw case `099980`, source SHA256 `49d56b1477fed32e9c45e52582884818f7632735542b22388911fccd602f2319`; half-open raw offsets, exact quotes/hash không normalize.

| # | Target ID | Full reviewed target | Decision / evidence |
|---|---|---|---|
| 1 | at-0c041e93ec332ab4eaa1354a | [55466,56158) | `unresolved`: applicant interpretation + court “inclined to agree”; paragraph 93 explicitly withholds definitive jurisdiction/reasonableness opinion. Không ép thành final holding hoặc party-only negative. |
| 2 | at-10bb35c0b238a53d984dfdf8 | [113906,114442) | Hard-negative `party_argument_only`: respondent costs concession/proposal, không court adoption. |
| 3 | at-143c4e018a2c0568cdf11a72 | [7072,8267) | Hard-negative `fact_only`: facts/supervisor role rồi investigator presumption/finding; không nâng thành court-created duty to correct references. |
| 4 | at-14a2c80dde4ce6c302eded10 | [95037,95530) | Hard-negative `fact_only`: testimony/purpose-of-investigation appraisal; không nhập legal expectation ở paragraph 161 khác owner. |
| 5 | at-14ff8ed5bd6fc2b9d2b9cff5 | [41635,42527) | Hard-negative `party_argument_only`: respondent reliance on Seck 1 và asserted plenary powers. |
| 6 | at-169450a12e07bd505d8d2dab | [118259,118817) | Hard-negative `editorial`: court disclaims finding innocence; case-specific criticism/Rule-of-Law rhetoric không thành innocence holding hay new legal test. |
| 7 | at-174a2f0bbfd0b2d0d0ee2608 | [57495,58236) | Hard-negative `party_argument_only`: respondent admission rồi defence rằng procedure sufficient/fair; không court endorsement. |
| 8 | at-188b314c4f3fc2293a2a3f9e | [27428,28033) | AU `fact_pattern_rule`, current_court: intent essential, material act alone insufficient in Commission fraud analysis. Primary [27428,27599), chỉ first two court sentences; không quoted section-66 agency analogy. Paragraph 53 support [26766,27422); good-faith/error exception [27204,27269). |
| 9 | at-19699b1ac79c9676fcc00a6d | [32814,33600) | AU `procedural_rule`, current_court, medium uncertainty: highly relevant to examine own false-reference jurisprudence when assessing this decision reasonableness. Primary [32814,33125); jurisdiction assumption [33161,33222); no-definitive-opinion limitation/cross-support paragraph 93 [56166,56481). Không universal binding-precedent duty hay final jurisdiction ruling. |
| 10 | at-1f0c7e3838ca599ebd75ae72 | [54165,54809) | Hard-negative `procedural_history_only`: Commission three corrective actions, không court endorsement of general permission/revocation/RCMP powers. |

Đọc full target + neighboring raw context ±1000 chars. #8 mở tới paragraph 53; #9 đọc thêm full paragraphs 92–93 để giữ remote reservation. Detailed JSON chứa claim text, full quote/source spans, reviewer notes, field-level witnesses, explicit unresolved reason và per-target trace/checksums.

## Checkpoint / resume boundary

Dùng `au_gold/r4.py` đã có: immutable target proposal, exact validation sidecar, atomic append manifest và global progress. Frozen second10 batch giữ selected IDs, prior progress, prior R4 manifest và preservation hashes. Resume dùng file checkpoint hợp lệ đã tồn tại; không relabel và không chọn ten targets kế tiếp. Duplicate ownership và differing immutable proposal đều bị reject.

First10 reports là immutable historical snapshots (222/369, 147 missing), không cập nhật thành số liệu second10. Test first10 đã tách batch-local records khỏi tổng R4 manifest chứa nhiều batches.

## Artifacts

- `outputs/plan09_au_gold_v1/r4_second10_validation.json`: exact decisions/evidence/context và preservation checks.
- `outputs/plan09_au_gold_v1/r4_batches/p09-r4-099980-second10-sol-v1.json`: frozen ten targets và before snapshots.
- `outputs/plan09_au_gold_v1/r4_model_proposals/099980/p09-r4-099980-second10-{01..10}-gpt61sol-v1.json` cùng `.validation.json` sidecars.
- `outputs/plan09_au_gold_v1/model_proposal_manifest.json`: append ten records; cumulative twenty R4 proposals.
- `reports/plan09_model_silver_progress.latest.json`: current progress/gates.
- Resume: `python -m knowledge_base.pipeline_v1.review_plan09_r4_second10`; chỉ batch frozen này, không batch tiếp.

## Tests / acceptance boundary

Pre-checkpoint decision/source test: 1/1 PASS. Focused R4 first10 + second10 + R3 completion: 10/10 PASS (13.570 giây). Full relevant Plan09: 46/46 PASS (277.725 giây), lệnh `python -m unittest discover -s knowledge_base/pipeline_v1/tests -p "test_plan09*.py"`. R4 manifest rebuild PASS, cumulative twenty proposals, `manifest_rebuild_changed=false`; rebuilt progress exact 232/369, 137 missing. Preservation recheck: 218/218 hashes unchanged; R3 acceptance validator PASS.

Persisted test/hash summary: `outputs/plan09_au_gold_v1/r4_second10_completion_verification.json`. Contract/test PASS không thay independent semantic review; hai AU và một unresolved vẫn model proposals. Không claim human gold, R5 pass hoặc Plan10 readiness.
