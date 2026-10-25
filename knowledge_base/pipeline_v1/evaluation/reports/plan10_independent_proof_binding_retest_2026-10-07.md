# Plan 10 probe-proof binding retest — 2026-10-07

## Verdict: original regression fixed; paired authorization still incomplete

`python -m unittest knowledge_base.pipeline_v1.tests.test_plan10 -v` passes **23/23**. The exact prior regression is fixed: a warmup-probe ledger whose verified attempt has `request_id="WRONG"`, `request_sha256="WRONG"`, or `cache_key="WRONG"` is rejected.

However, `_has_probe_proof` still treats a ledger as proof without resolving or validating the referenced source-probe cache row. Do not authorize paired-run on a warmup-probe ledger alone yet.

No Modal call or real `.env` read occurred.

## Evidence

- `_has_probe_proof` now requires the successful attempt's request ID, request hash and cache key to equal the current first locked P2a request (`au_baseline/__main__.py:39`).
- The focused regression test covers the wrong-ID/hash/key case (`tests/test_plan10.py:78-82`).
- A local temporary ledger with all current top-level manifest/spec/model/thinking identifiers and an attempt containing the *correct* request ID/hash/cache key—but with no `source_probe_cache/.../response.json` at all—still returns `True` from `_has_probe_proof`.

## Remaining required gate

Resolve the expected cache path from the bound cache key, require it to exist, then validate that the row:

1. has matching cache key and request object/hash;
2. has `status="protocol_verified"`;
3. has a valid response against the locked source/schema/host checks; and
4. has receipt model/thinking/finish metadata consistent with the ledger.

Persist or derive a cache-row digest in the combined ledger and reject missing, corrupt, mismatched, or stale cache rows. Add the missing-cache regression test. This remains protocol/provenance work only; it does not establish semantic AU or retrieval quality.
