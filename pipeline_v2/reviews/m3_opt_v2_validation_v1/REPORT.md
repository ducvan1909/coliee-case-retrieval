# Independent Local Validation — M3 Optimization V2

Date: 2026-11-08  
Scope: frozen production implementation fingerprint `e2e554dd44bbd99ab93b61ca893094fe9dd47e0cd8604e5898e8b169bf931cf3`.

## Result

**18/18 local synthetic tests passed.** The tests cover lexical ranking, immutable session behavior, compatibility receipt gates, fair benchmark sampling and OOM handling, and local CLI isolation. All provider/runtime interactions are mocked. No Modal CLI/SDK, model inference, Docker, credentials, `.env`, labels, or gold data were read or used.

Exact command:

```powershell
.venv/Scripts/python.exe -m unittest `
  pipeline_v2.tests.test_m3_opt_v2_index `
  pipeline_v2.tests.test_m3_opt_v2_session `
  pipeline_v2.tests.test_m3_opt_v2_runtime `
  pipeline_v2.tests.test_m3_opt_v2_benchmark `
  pipeline_v2.tests.test_m3_opt_v2_cli -v
```

Final frozen-tree result: `Ran 18 tests in 0.487s — OK`.

## Coverage

- BM25 is checked against a separately written formula oracle for Unicode, digits/citations, negation terms, exclusion before cap, and deterministic ties. A one-shot iterator is consumed once. SQLite metadata contains no raw `text`, retains paragraph references, resolves relative and absolute paths, and top-hit metadata is fetched with a bounded number of SQL queries.
- Session open does not iterate all passage metadata or call vector norm validation. Evidence open detects changed raw bytes. Explicit revalidation detects source drift and invalidates the session; a canonical query case outside the pilot is allowed as a no-op exclusion, while malformed IDs fail before store access.
- Compatibility-gate tests bind receipts to the index/profile/code and require eight document and three query checks. A simulated receipt cannot enable a real search. New preflight with a missing runtime directory and a failed retry over a prior `PASS` pointer are exercised without remote calls.
- Benchmark tests verify the deterministic four-window sample has 64 unique passages per stratum, all candidate batch sizes use the same selected IDs and token denominator, crossover orders are balanced, and a mocked OOM at stress-128 leaves candidate sizes 16/32/64 independently eligible. A mocked OOM keeps unknown usage as `null`.
- CLI `build`, `verify`, `open`, and `--help` are tested with a missing env file while env parsing/building and any `import modal` are forced to fail. All commands still complete through mocked local functions.

The one-shot iterator test alone does not prove bounded memory use. The implementation was also inspected: `PersistentBM25.create()` processes one document `Counter` at a time and inserts postings in batches capped at 512 rows. This is code inspection, not a large-memory benchmark.

## Limits

These tests are protocol and local behavior tests, not proof of legal relevance or COLIEE semantic quality. They do not exercise actual Qdrant state, the real sealed pilot index, a real Modal L4 response, query/document vector parity on the deployed model, throughput, memory, end-to-end CLI latency, or full-corpus readiness. A successful synthetic preflight receipt is not treated as evidence that the deployed model passes parity. Before claiming remote performance, run the user-owned Modal preflight and benchmark commands and review their request/token/latency ledger. Full corpus and COLIEE scoring remain outside this test result.

## Test files

- `pipeline_v2/tests/test_m3_opt_v2_index.py`
- `pipeline_v2/tests/test_m3_opt_v2_session.py`
- `pipeline_v2/tests/test_m3_opt_v2_runtime.py`
- `pipeline_v2/tests/test_m3_opt_v2_benchmark.py`
- `pipeline_v2/tests/test_m3_opt_v2_cli.py`
