# Plan09 R4 — 099980 third ten missing targets

Ngày 2026-10-05. Provenance gpt-6.1-sol low, model-only/model-silver; không Terra outputs, không independent audit/R5 acceptance.

## Kết quả

Đúng 10 ID đầu trong 137 missing_target_ids trước batch, giữ thứ tự ổn định. Batch 4 AU / 5 hard-negative / 1 unresolved. Coverage 232 → 242 / 369; missing 137 → 127. Effective totals: 108 AU / 131 hard negatives / 3 unresolved.

243 hashes của existing proposals/sidecars/amendments/risk reviews/registry history, previous frozen batches/reports và accepted R3 giữ nguyên. Hai mươi R4 manifest records cũ giữ nguyên, chỉ append ten records mới. Không sửa/review lại 232 targets đã có, không xử lý target thứ 11. R3 vẫn PASS ở cohort cũ, R4 incomplete, R5 chưa PASS và Plan10 false.

## Exact target decisions

Raw case `099980`, source SHA256 `49d56b1477fed32e9c45e52582884818f7632735542b22388911fccd602f2319`. Half-open raw offsets, quotes/hash không normalize.

| # | Target ID | Full reviewed span | Decision / primary evidence và qualifiers |
|---|---|---|---|
| 1 | at-1f8713f545365df1f151daa4 | [120764,121441) | Hard-negative `editorial`: closing thanks/request Commission reflection, không systemic reform order. Formal judgment có owner khác. |
| 2 | at-23e0d9d111911c28fba85628 | [104762,105374) | AU `procedural_rule`, current_court, medium uncertainty. Draft final investigation report cần được gửi/comment trước approval cho người directly affected. Primary court question [105153,105374); final-report condition [104958,105001); before-approval limit [105319,105373); paragraph 174 confirmation [105383,105436). |
| 3 | at-246ff349485b66f67fe5c39d | [110179,110567) | Hard-negative `editorial`: remedy reflection/repair metaphor, không operative remedy hay standalone test. |
| 4 | at-25a47b63b5767f7bc735f6be | [89120,89941) | AU `holding`, current_court. Notice 31/03/2010 insufficient vì không nói applicant bị nghi fraud. Primary chỉ first two court sentences [89120,89305); dated-notice limit [89124,89161); non-disclosure condition [89217,89304). Không nâng quoted boilerplate thành court rule. |
| 5 | at-27935875158c3bd52e6220aa | [83824,84462) | Hard-negative `fact_only`: quoted investigator purpose/allegations, không adopted court legal conclusion. |
| 6 | at-27d52ebdf0fe44b1ec832078 | [28976,29425) | `unresolved`: nested cited-court confirmation + expressly quoted investigator argument. Chưa đủ chứng cứ cho adoption/speaker của reusable rule; không gán current_court hoặc cited_court, không ép AU/negative. |
| 7 | at-2830ad7af31dc36e2dfd45a2 | [50128,52340) | AU `statutory_hook`, current_court paraphrase: PSEA/PSLRA review legislation/admin/application sau 5 năm. Primary chỉ first sentence [50128,50300); temporal limit [50262,50299). Loại Review Team recommendation khỏi binding-rule witnesses. |
| 8 | at-298921465b894cd1e165f1c2 | [36855,37259) | Hard-negative `fact_only`: this jurisdiction-report timing/Policy omission appraisal, không final jurisdiction ruling. |
| 9 | at-2ad9077730065065ecf5523f | [37785,38476) | Hard-negative `procedural_history_only`: expressly quoted investigator jurisdiction-objection response, không current-court adoption. |
| 10 | at-2be613d920e6ea831c8e3022 | [115307,115798) | AU case-specific `holding`, current_court, medium uncertainty. Court states lack of retroactive-setting-aside authority for this decision. Primary narrow clause [115497,115583); this-decision limit [115562,115583). Không biến thành universal bar on retroactive judicial relief hoặc rule hợp pháp hóa permission condition. |

Mỗi target được đọc toàn raw span và neighboring context ±1100 chars. JSON lưu full reviewed quote/hash, actual context spans, per-target decisions/notes, primary attribution witnesses, qualifications và trace/checksums. Medium uncertainty ở #2/#10 được ghi rõ cho independent review sau này.

## Atomic/resumable workflow

Tái dùng `au_gold/r4.py`: single-target immutable proposal + exact validation sidecar, duplicate guard và atomic manifest/progress publishing. `au_gold/r4_batch.py` chỉ gom freeze/run/verify cho một batch ten-target, không có vòng lặp chọn batch kế tiếp. Frozen manifest lưu target IDs, prior progress, prior R4 manifest và preservation hashes. Khi resume, dùng checkpoint hợp lệ có sẵn, không relabel.

## Artifacts

- `outputs/plan09_au_gold_v1/r4_third10_validation.json`: detailed decisions/evidence/context và preservation validation.
- `outputs/plan09_au_gold_v1/r4_batches/p09-r4-099980-third10-sol-v1.json`: frozen selected ten và prior snapshots.
- `outputs/plan09_au_gold_v1/r4_model_proposals/099980/p09-r4-099980-third10-{01..10}-gpt61sol-v1.json` cùng `.validation.json` sidecars.
- `outputs/plan09_au_gold_v1/model_proposal_manifest.json`: cumulative thirty R4 proposals.
- `reports/plan09_model_silver_progress.latest.json`: rebuilt current progress/gates.
- Resume đúng batch: `python -m knowledge_base.pipeline_v1.review_plan09_r4_third10`.

## Verification boundary

Pre-checkpoint source/decision test: 1/1 PASS. Focused R4 first10/second10/third10 + R3 completion: 12/12 PASS (17.606 giây). Full relevant Plan09: 48/48 PASS (288.952 giây), lệnh `python -m unittest discover -s knowledge_base/pipeline_v1/tests -p "test_plan09*.py"`. R4 manifest rebuild: PASS, thirty records, `manifest_rebuild_changed=false`; global progress exact 242/369, 127 missing. Recheck 243/243 preservation hashes và R3 acceptance validator: PASS.

Persisted test/hash summary: `outputs/plan09_au_gold_v1/r4_third10_completion_verification.json`. Tất cả proposal/effective overlays validated; điều đó không thay semantic acceptance, human gold hoặc retrieval-quality evidence. R5/Plan10 chưa được mở.
