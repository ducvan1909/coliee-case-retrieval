# Plan09 R4 — 099980 fourth ten missing targets

Ngày 2026-10-05. Provenance gpt-6.1-sol low, model-only/model-silver. Không Terra output, không independent audit hoặc R5 acceptance.

## Kết quả

Đúng 10 ID đầu trong 127 missing_target_ids trước batch, giữ thứ tự ổn định. Batch 3 AU / 5 hard-negative / 2 unresolved. Coverage 242 → 252 / 369; missing 127 → 117. Effective totals: 111 AU / 136 hard negatives / 5 unresolved.

267 preservation hashes của existing proposal/sidecar/amendment/risk-review/registry history, prior batches/reports và accepted R3 giữ nguyên. Thirty R4 manifest records cũ giữ nguyên, chỉ append ten records mới. Không sửa/review lại 242 target cũ, không xử lý target thứ 11. R3 vẫn PASS cho cohort accepted cũ; R4 incomplete, R5 chưa PASS, Plan10 false.

## Exact targets / evidence

Raw case `099980`, source SHA256 `49d56b1477fed32e9c45e52582884818f7632735542b22388911fccd602f2319`; half-open raw offsets, không normalize quotes/hash.

| # | Target ID | Full reviewed span | Decision / evidence / qualifiers |
|---|---|---|---|
| 1 | at-2c1bd134149633afd4376e74 | [17996,18387) | Hard-negative `procedural_history_only`: forward result/analytical roadmap, không separate reasoned authority proposition hoặc imported later grounds. |
| 2 | at-2ee52523f9ffaed8ef6d78a9 | [10808,11130) | Hard-negative `procedural_history_only`: Commission letters notify judicial-review rights; không gán reported agency notification thành current-court statutory interpretation. |
| 3 | at-30fcb7387e01828cdc463add | [61507,61609) | AU `procedural_rule`, current_court: choice-of-procedure criterion not determinative under Baker context. Primary [61507,61609); limit [61564,61581). Không nói factor irrelevant hoặc Commission tùy ý miễn fairness. |
| 4 | at-31fb5ee31ba428e383f369cf | [4263,4689) | Hard-negative `fact_only`: DNR/email investigation/transmittal events; không adoption of interception legality. |
| 5 | at-322488d8d16a073136576e8a | [70054,70397) | Hard-negative `fact_only`: potential disciplinary impacts, không rule prescribing discipline. |
| 6 | at-34095952cc8f4531057b05a3 | [98868,99493) | AU `procedural_rule`, current_court: absent direct provision of new evidence, at least send another revised factual report. Primary [99233,99465); non-disclosure condition [99252,99311); Cousineau/17-May information limit [99403,99464). Direct disclosure remains an alternative, không absolute report duty. |
| 7 | at-36d2799e80bf0e3f5421c6cf | [17417,17988) | `unresolved`: mixed applicant jurisdiction request/court non-final characterization; paragraph 93 reserves definitive ruling. Không settled correctness standard hoặc forced party-only negative. |
| 8 | at-397a79d4d287d795fed0e818 | [80358,80994) | Hard-negative `fact_only`: interested-employer participation facts, không universal entitlement to reports/remedies. |
| 9 | at-3b322354b56dc150db0ef7af | [26105,26357) | AU `procedural_rule`, current_court: in this case absent statutory fraud definition, court states reliance on Commission interpretation. Primary [26105,26357); definition-gap condition [26119,26168); case limit [26105,26117). Không suy ra universal deference/non-reviewability/final jurisdiction standard. |
| 10 | at-3bf2d5382a3dbb34d161b87b | [33608,34429) | `unresolved`: applicant-argues frame rồi unclear-intent/factual contrasts chưa tách speaker/adoption đủ chắc; no final reasonableness ruling. Không invent rule personal gain luôn là yếu tố bắt buộc của fraud. |

Đọc mỗi full target và raw neighboring context ±1200 chars. #7/#10 đọc thêm full paragraphs 92–93 để giữ reservation. Detailed JSON lưu claims, exact witnesses/context, notes, qualifications, explicit unresolved reasons và trace/checksums. Ba AU là model proposals, không tự coi là semantic gold.

## Checkpoint / artifacts

Dùng R4 single-target immutable checkpoint + sidecar và frozen-batch runner đã có. Duplicate guard, exact source/owner/span/trace/provenance validation và atomic append manifest/progress; resume dùng checkpoint hợp lệ, không relabel hoặc chọn batch kế tiếp.

- `outputs/plan09_au_gold_v1/r4_fourth10_validation.json`: detailed targets/decisions/evidence và preservation checks.
- `outputs/plan09_au_gold_v1/r4_batches/p09-r4-099980-fourth10-sol-v1.json`: frozen ten IDs, before progress/manifest và preservation hashes.
- `outputs/plan09_au_gold_v1/r4_model_proposals/099980/p09-r4-099980-fourth10-{01..10}-gpt61sol-v1.json` cùng `.validation.json` sidecars.
- `outputs/plan09_au_gold_v1/model_proposal_manifest.json`: forty R4 proposal records.
- `reports/plan09_model_silver_progress.latest.json`: current progress/gates.
- Resume đúng batch: `python -m knowledge_base.pipeline_v1.review_plan09_r4_fourth10`.

## Verification boundary

Pre-checkpoint source/decision test: 1/1 PASS. Focused R4 batches + R3 completion: 14/14 PASS (21.925 giây). Full relevant Plan09: 50/50 PASS (294.072 giây), lệnh `python -m unittest discover -s knowledge_base/pipeline_v1/tests -p "test_plan09*.py"`. Manifest rebuild: PASS, forty records, `manifest_rebuild_changed=false`. Progress exact 252/369, 117 missing. Preservation 267/267 hashes và R3 acceptance validator PASS.

Test/hash summary: `outputs/plan09_au_gold_v1/r4_fourth10_completion_verification.json`. Proposal và effective overlays valid; contract/test PASS không thay independent semantic acceptance, human gold hay retrieval-quality proof. Plan10 vẫn khóa.
