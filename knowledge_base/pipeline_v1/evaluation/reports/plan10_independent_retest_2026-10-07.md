# Plan 10 — independent remediation retest (2026-10-07)

## Verdict

**FAIL — do not run the remote Plan 10 baseline yet.** The prior schema, fault-handling, paired-control, and most cache/accounting remediation is materially present and focused local/mock tests pass **9/9**. However, the dedicated input-token/USD preflight under-reserves the actual request payload, so it can dispatch a request that exceeds its configured budget.

No Modal endpoint was called. All adapter tests used a fake opener and temporary cache directories. Neither `knowledge_base/.env` nor any real credential was read or printed.

This report is strictly protocol/runtime evidence. It says nothing about AU semantic accuracy, human gold, ContextHint value, or retrieval quality.

## Rechecked passes

- `python -m unittest knowledge_base.pipeline_v1.tests.test_plan10 -v`: **9/9 PASS**.
- The earlier invalid outputs (missing required `reason_detail`, wrong enum, malformed warning, extra property, invalid positive reasons) are now rejected by `Draft202012Validator` before host checks (`au_baseline/core.py:65-66`). A fake provider returning such output becomes `unresolved` in the runtime path.
- Missing/foreign target, exact span/quote, per-target context references, global local-AU ID uniqueness, and AU candidate caps remain host-checked after schema validation (`core.py:71-86`).
- Combined bearer-token precedence and split `key:secret` construction remain correct; blank model names are rejected (`core.py:90-96`). `probe` without `--execute` errors before calling configuration/network.
- Runtime exceptions are converted to a redacted unresolved row and later requests continue (`core.py:155-157`); the focused test asserts the injected secret-like exception text is absent from the serialized receipt.
- P2a/P2b paired manifest creation, probe hash checks, and remote ledgers/comparison are now present in `au_baseline/__main__.py:33-45`. Repeated source and context spans use merged interval accounting (`core.py:34-49`) and mock totals include both (`core.py:165-174`).
- Cache writes remain atomic (`core.py:30-32`); remote cache reuse revalidates the cached response (`core.py:139-145`).

## P0 — input-token/USD preflight underestimates the actual transmitted payload

`build_locked_requests` records `input_tokens` from `len(rendered)` only (`core.py:48`), but `call_modal` sends `prompt_for(...)`, which prefixes instructions, request metadata, and the full versioned JSON Schema (`core.py:60,111`). The same incomplete value is used for both preflight and per-request budget reservation (`__main__.py:15`; `core.py:149-151`).

### Local fake-provider reproduction

For the first P2a request:

- rendered region: 3,650 characters;
- recorded/reserved input: **913** tokens (4 chars/token);
- actual `prompt_for` payload: 9,234 characters, approximately **2,309** tokens using the same estimator.

With `max_input_tokens=913`, a fake provider reporting `prompt_tokens=2309` was still called and returned `status="protocol_verified"`; the receipt records `input_tokens=2309`. Therefore the configured cap did not prevent an over-budget dispatch.

The same underestimate carries into USD reservation whenever input pricing is configured. Recording actual provider usage after dispatch cannot restore the violated no-over-budget guarantee.

### Required remediation

Build and freeze the exact prompt before budgeting, then store an `estimated_prompt_input_tokens` (or equivalent) based on the entire payload, including prompt wrapper/schema/request identifiers and rendered region. Use that value consistently for:

1. paired preflight;
2. per-request reservation;
3. input USD reservation; and
4. persisted accounting, alongside actual provider usage.

Add a local test whose input cap equals the old rendered-only count and assert the opener is **not** called. Retest both arms and ensure the same prompt-accounting method is applied without changing model/prompt/schema/examples/caps between P2a and P2b.

## Final gate

After the P0 fix and the new non-dispatch regression test pass, the local/mock **runtime contract** can be reconsidered. That would still not validate semantic AU extraction, human adjudication/gold, ContextHint effectiveness, or retrieval quality.
