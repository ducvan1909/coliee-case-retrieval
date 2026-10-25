# Plan 10 — independent final local/mock retest (2026-10-07)

## Verdict

**PASS — local/mock runtime and experiment contract, within the stated character-based prompt-token estimator.** The previous P0 reservation defect is fixed: input reservations now cover the exact serialized OpenAI-compatible JSON payload constructed by the runtime, rather than only the rendered AnalysisRegion.

This is not a provider, billing, semantic-AU, human-gold, ContextHint-effectiveness, or retrieval-quality result. No Modal endpoint was contacted; fake openers and temporary cache directories were used. No real `.env` was read or logged.

## Evidence

- `python -m unittest knowledge_base.pipeline_v1.tests.test_plan10 -v`: **10/10 PASS**.
- The original schema-invalid reproductions are rejected before host checks and become unresolved through the remote runtime path. Exact target coverage, quote/span and context references, candidate cap, model/spec equality, redacted unexpected errors, cache revalidation, atomic writes, P2a/P2b pairing, and merged source/context repeat accounting remain covered by code and focused tests.
- The CLI requires `--execute` and a positive `--max-requests` before loading configuration. `probe --max-requests 1` without that flag stopped at the gate; no provider/configuration path ran.
- The input request now contains both `rendered_input_tokens` and `estimated_prompt_input_tokens`; `input_tokens` is the latter. `estimate_prompt_input_tokens` serializes the same `modal_payload` that `call_modal` sends, including frozen model, prompt, full schema, region, response format, and output cap (`au_baseline/core.py:62-66,119-122`). Its value participates in cache identity and both preflight/per-request input and USD reservation (`core.py:24,151-152`; `au_baseline/__main__.py:15-17`).

## Independent regression reproduction

For the first locked P2a request, the local retest observed:

| Field | Value |
| --- | ---: |
| Rendered-only estimate | 913 tokens |
| Exact serialized JSON-body size | 10,227 characters |
| Prompt-body estimate | 2,557 tokens |
| Configured input cap | 913 tokens |
| Fake-provider dispatches | 0 |
| Runtime result | `budget_stopped` / `budget_reservation_exceeded` |

The recomputed ceiling of `json_body_chars / 4` exactly equals `estimated_prompt_input_tokens`. Thus the old rendered-only cap cannot dispatch this request.

## Scope and remaining evidence gap

The cap is an explicit deterministic **character-based estimate**, inherited from the locked region token estimator; it is not proof of a provider tokenizer's measured token count or of actual billing. A real provider run, if separately authorized, must still be budgeted conservatively and report the provider receipt's actual usage. That future run must continue to label results `evaluation_against=model_silver`, with `semantic_gold=false` and `retrieval_quality_claim=false` until the separate human-gold and evaluation gates are met.
