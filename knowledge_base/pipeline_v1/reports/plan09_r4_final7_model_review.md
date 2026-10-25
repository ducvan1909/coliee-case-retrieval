# Plan09 R4 final7 model review and coverage completion

Date2026-10-06. Producer `model:gpt-6.1-sol`, reasoning `low`, model_silver only. Not Terra output or independently accepted human gold. Exactly all7 remaining099980 IDs in frozen progress order, no outside target. Raw source SHA256 `49d56b1477fed32e9c45e52582884818f7632735542b22388911fccd602f2319`.

## Raw-source decisions

| # | Target | Full raw target [start,end) | Decision and scope |
|---|---|---|---|
| 1 | at-ee2e12aeef17269d91410e7e | [60473,60937) | AU procedural_rule, para100 cited_court former PSEA6(2)/(3) greater procedural protection. Current comparison with differently worded66/67 is context, no universal fraud hearing entitlement. |
| 2 | at-f71923e1a0ac847eaf65fdcc | [119444,120085) | Hard-negative editorial, para198 counsel praise/institution criticism; no immunity or counsel-liability test. |
| 3 | at-f84bcbf2e61c72f291935ac4 | [8927,9432) | Hard-negative procedural_history_only, para18 other agency order/report not personally affecting applicant; no Court sanction-power endorsement. |
| 4 | at-f9b94a5e5fb3e05554f4c167 | [14821,15478) | Hard-negative party_argument_only, para30 applicant fairness/jurisdiction arguments including conditional If-Court-accepts; no adopted holding inside target. |
| 5 | at-f9be712086516d8fe612b889 | [101654,103488) | AU statutory_hook, para170 commission_correspondence Regulations19 disclosure discretion, public-interest/privacy balance and conditional consultation. Not actual publication or court fraud finding. |
| 6 | at-fefd2e4233313a501663cb35 | [83305,83815) | Hard-negative procedural_history_only, para140 report transmittal and reserved mother-interview question; no universal duty/no-duty ruling. |
| 7 | at-ffb5c4acb13eda43b742abd3 | [46324,47112) | Three statutory_hook AUs, para82 PSDPA Minister environment duty, Treasury Board sector-wide code duty, chief-executive portion/code-consistency duty. Rhetorical continuum excluded. |

Read all full targets and neighboring raw context ±1200 chars. Three positive targets contain5AUs due three disjoint statutory duties in #7;4N/0U. Exact attribution/conditions/limits/source/contexts/trace witnesses persist in detailed JSON. No labels inferred from heading or KOS.

Exact primary witnesses: #1 [60473,60691), former-scheme scope [60559,60597); #5 [102608,103209), public-interest/privacy condition [102979,103048), contemplated-disclosure condition [103050,103150), discretion qualifier [102816,102855), investigation-information scope [102889,102931); #7 Minister [46599,46782), Treasury Board [46783,46887), sector-wide scope [46848,46886), chief-executives [46888,47112), responsible-portion scope [46943,47020), code-consistency witness [47022,47111).

## Checkpoints and final coverage

Frozen before raw source review: `outputs/plan09_au_gold_v1/r4_batches/p09-r4-099980-final7-sol-v1.json`,555 prior artifact hashes. Seven immutable individual proposal/sidecar pairs. Resume `python -m knowledge_base.pipeline_v1.review_plan09_r4_final7`; existing checkpoints reused without relabeling.

The ten-target runner now accepts optional `target_count=7` for exactly the final362→369 batch; default10 behavior preserved. Live-state tests derive R4-complete from missing count; old historical batch artifacts and R3 acceptance are not rewritten. Progress blocker distinguishes coverage complete from pending independent R5 audit.

Coverage binds every original proposal and all existing sidecars. Historical Terra layout differs from R4: some use `.json.validation.json`, and17 originals have no persisted sidecar. Coverage artifact records fresh validation checks and explicit absence for those17 without creating/replacing old sidecars. All157 R4 checkpoints retain their canonical sidecars. The initial coverage-binding path assumption was corrected after exact read-only inventory; final7 checkpoints were not rewritten.

Pre-checkpoint decision test PASS1/1 (0.179s). Detailed validation `outputs/plan09_au_gold_v1/r4_final7_validation.json`; exact case-target-set coverage artifact `outputs/plan09_au_gold_v1/r4_coverage_completion.json`; completion verification `outputs/plan09_au_gold_v1/r4_final7_completion_verification.json`. Coverage362→369/369, missing7→0; effective187AU/185N/10U. Exact expected369 case-target pairs equal effective reviewed pairs, duplicate0, all5 cases complete. Rebuild157records PASS, `manifest_rebuild_changed=false`; preservation555/555; exact primary duplicates of old AU spans0. Focused R4 batches + R3 completion PASS38/38 (156.362s); full Plan09 PASS74/74 (530.415s), command: `python -m unittest discover -s knowledge_base/pipeline_v1/tests -p "test_plan09*.py"`.

R4 coverage completeness counts unresolved model reviews as reviewed; it does not imply semantic acceptance, human gold, retrieval quality or R5 PASS. Independent final audit remains mandatory; R5=false and Plan10 locked.
