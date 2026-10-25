# AU-only pilot: manifest & preflight audit (2026-10-08)

## Scope and method

Read-only audit of the materialized pilot. No provider/Modal call and no production-code edit.

Inputs checked:

- `manifests/au_only_pilot_r5_model_silver.v1.json`
- `outputs/au_only_pilot_r5_preflight/preflight.json`
- `outputs/plan09_au_gold_v1/r5_acceptance.v1.json`
- frozen Plan07 v1.4 workload maps and `outputs/source_store_v1`
- safe (non-secret) `AU_ONLY_*` values from `knowledge_base/.env`

## Result: PASS for the materialized artifact and offline preflight

| Check | Evidence | Result |
|---|---|---|
| Exact pilot population | 10 distinct `(case_id,target_id)` pairs; all keys are present in Plan09 R5 `effective_review_hashes`. | PASS |
| Selected IDs | `011904:{at-056fd4ca0454c65c2b585cea, at-ade4a3797b31d7deb9bf7baf}`; `013009:{at-d1a9498ecd408d28317aa793, at-f4a073144323210976dace57}`; `013948:{at-3afd82f9ffea744294fd4624, at-726483a83077ee92addf3aff}`; `045155:{at-923a3aae96b77d61178e6d57, at-52c4e1747233e8e73f3510f5}`; `099980:{at-c346a3add188a66127ed9fb5, at-422fbd7f49cb2cff502c7399}`. | PASS |
| Frozen identity/provenance | Re-running `au_only.build_pilot.build()` from the current frozen v1.4 maps produced a manifest exactly equal to the saved JSON. Builder glob is explicitly `p2-offline-scheduler-v1.4-*`; no v1.5/v1.6 map is used. | PASS |
| Source integrity | Offline `preflight()` re-opened the locked source store, checked source hashes and all offsets, and produced an object exactly equal to the saved receipt. | PASS |
| Single-target/no paired arm | Every request has exactly one `expected_target_ids` entry and `arm == "AU-only"`. | PASS |
| No runtime P2/hint payload | All ten `hint_payload`s are exactly `{version: context-hint-payload-v1, hint_ids: []}`; validation rejects a P2 arm or any non-empty hint payload. The v1.4/P2a reference is construction-time provenance only, not a runtime arm or hint. | PASS |
| Locked model/thinking | Every request specifies `Qwen/Qwen3.5-9B` and `enable_thinking=false`, matching non-secret `AU_ONLY_MODEL` and `AU_ONLY_ENABLE_THINKING` values in `knowledge_base/.env`. | PASS (artifact-to-file) |
| Caps/totals | Manifest reserves 26,206 input and 16,000 output tokens, below env caps 120,000 and 32,000; request and provider-attempt counts are 10, below caps 20 and 20. | PASS |
| Saved receipt | Saved receipt is `status: pass`, `request_count: 10`, `failures: []`; direct recomputation returned an exactly equal receipt. | PASS |

## Important boundary

This is a model-silver development pilot, not human/semantic gold. A valid manifest and protocol preflight do not establish AU extraction quality or retrieval impact.

There is one execution-provenance caveat: `au_only.__main__` reads `os.environ` and does not call a dotenv loader. The saved manifest matches the values in `knowledge_base/.env`, but this audit cannot prove the shell that created the receipt had loaded that file. Before a live call, explicitly export the reviewed `AU_ONLY_*` values (or introduce an auditable dotenv-loading policy), re-run preflight, and persist the resulting receipt/config fingerprint. No secret value was read or reported in this audit.

## Independent assessment

The assertion “v1.4 provenance and a PASS receipt make the pilot ready to claim a result” would be too strong. The evidence supports deterministic construction and bounded protocol readiness only. It does not prove that the ten IDs were selected by a human outside the hard-coded builder set, that the provider will be reachable, or that returned AUs are semantically correct. Those require a recorded execution plus the stated model-silver review/evaluation gate.
