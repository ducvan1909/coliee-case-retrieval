# Plan09 R4 — 099980 ninth ten missing targets

Ngày 2026-10-06. Provenance gpt-6.1-sol low; model-only, evaluation_against=model_silver. Không Terra output, human gold hoặc independent acceptance.

## Kết quả

Freeze exact 10 ID/order đầu trong 77 missing_target_ids trước khi mở raw source. Batch: 7 AU / 3 hard-negative / 0 unresolved. Reviewed 292 → 302 / 369; missing 77 → 67. Effective totals: 138 AU / 155 hard-negative / 9 unresolved.

Giữ nguyên 292 target cũ và 387 preservation hashes của proposals/sidecars/amendments/risk reviews/registry history/prior batches/reports/R3 artifacts. Eighty R4 manifest records cũ giữ nguyên, chỉ append ten records mới. Không xử lý target thứ 11, không audit, không mở Plan10.

## Exact targets / evidence

Raw case `099980`, SHA256 `49d56b1477fed32e9c45e52582884818f7632735542b22388911fccd602f2319`. Offsets half-open trên raw source, không normalize.

| # | Target ID | Full reviewed span | Decision / witness / scope |
|---|---|---|---|
| 1 | at-85da5a3bc284d68445e19c26 | [16891,17409) | AU standard_of_review/current_court, medium uncertainty: cited decisions settle review-standard question conditionally. Primary full target; evidence-error condition [16891,17020), no-genuine-jurisdiction condition [17363,17408). Không invent exact reasonableness/correctness label absent from span hoặc apply vào live jurisdiction dispute; retain 93/183–184 reservation. |
| 2 | at-85f5879a84c34e2201fc207f | [118826,119435) | Hard-negative editorial: institutional indignation/resolution criticism trong costs discussion, không freestanding duty consent-to-judgment hoặc automatic costs rule. |
| 3 | at-867e2531fb535451e4d16e4d | [21580,22316) | AU procedural_rule/current_court, medium uncertainty: amicus-like/objective respondent role without new justification. Primary full target; for-Commission condition [21595,21656), absence-other-party condition [21658,21738), greater-latitude qualification [21805,21870), no-new-justification limit [22117,22218); cross 45–46 [22866,23847). Không literal amicus appointment/unrestricted merits or fairness advocacy. |
| 4 | at-86db1baf17aae56596742d23 | [34859,35367) | Hard-negative fact_only: June 5 notice/DNR/appointment history; section69 mention không actual jurisdiction hoặc Court fraud finding. |
| 5 | at-8733e4b4d14fe59b3f2f3eec | [100412,100914) | AU holding/current_court: reject no-prejudice suggestion for this approach/applicant as refuted by record. Primary first sentence [100412,100663); approach limit [100450,100477), applicant limit [100502,100518). Không universal two-day report/interview rule hoặc heading proposition. |
| 6 | at-889ec63c9b2044652d7bc22f | [62955,63304) | Hard-negative other: reported institutional mission values pledge, không standalone enforceable court-law proposition. Separate paragraph105 legitimate-expectations rule không import vào target này. |
| 7 | at-89b21721fd80d67c69db253b | [53114,54157) | AU procedural_rule/current_court, medium uncertainty: deputy-head investigation/hearing before discipline + PSLRA/applicable agreement procedures + possible grievance adjudication. Primary middle statements [53324,53950); disciplinary-case condition [53558,53572), applicable-agreement limit [53658,53693), could-be-referred limit [53823,53858). Exclude possible-duplication opening/unanswered third-party-power question; không binding ReviewTeam recommendation or guaranteed adjudication. |
| 8 | at-8e0a98db1c36c55a5caa9a12 | [105838,106172) | AU holding/current_court, medium uncertainty: June28 corrective-action submissions too little/too late in this case. Primary full target; groundwork condition [106065,106100), date limit [105838,105854), circumstances limit [106148,106171). Không universal inability to cure by later submissions. |
| 9 | at-8edbbc3df5180b14d919415d | [16389,16883) | AU standard_of_review/cited_court: Dunsmuir two-stage framework recited in this judgment. Primary full target; second-stage condition [16739,16780). Explicit Supreme Court attribution; không party argument, final case standard hoặc assertion historic framework là current law today. |
| 10 | at-8f23d518e0197e14ac57c53f | [79062,79626) | AU holding/current_court: serious fairness/transparency/integrity breaches even assuming unchanged mandate. Primary court response [79242,79560); even-if condition [79242,79262), case limit [79547,79559). Exclude first respondent assertion/next heading; không actual finding mandate unchanged. |

Đọc full targets và neighboring raw context ±1200 chars. #1/#7 đọc 92–93 và 183–184; #3 đọc 43–46; #8 đọc 173–176. Detailed JSON lưu exact witnesses/context, qualifications, notes và trace/checksums. Không force unresolved chỉ để đủ ba outcome classes; medium uncertainty vẫn được ghi cho conditional/scoped model proposals.

## Checkpoint / verification

Frozen batch: `outputs/plan09_au_gold_v1/r4_batches/p09-r4-099980-ninth10-sol-v1.json`, có `frozen_before_raw_source_review=true`. Ten immutable single-target proposals + `.validation.json` sidecars trong `r4_model_proposals/099980`. Resume đúng batch: `python -m knowledge_base.pipeline_v1.review_plan09_r4_ninth10`; runner dùng persisted checkpoints, không relabel hoặc chọn batch tiếp.

Detailed validation: `outputs/plan09_au_gold_v1/r4_ninth10_validation.json`. Pre-checkpoint source/decision test PASS 1/1 (0.243s); focused R4 batches + R3 completion PASS 24/24 (52.265s). Manifest rebuild PASS, 90 records, `manifest_rebuild_changed=false`; preservation 387/387 hashes; source/span/trace/provenance/duplicate ownership và effective overlays valid. New primary-span exact duplicates of old AUs: 0. R3 acceptance validator vẫn PASS cho cohort cũ, không acceptance cho R4 mới.

Full relevant Plan09 PASS 60/60 (328.086s), lệnh `python -m unittest discover -s knowledge_base/pipeline_v1/tests -p "test_plan09*.py"`. Test results và bound artifact hashes được lưu trong `outputs/plan09_au_gold_v1/r4_ninth10_completion_verification.json`. Contract/test PASS không chứng minh semantic correctness, human gold hoặc retrieval quality. R4 incomplete, R5=false, Plan10 locked.
