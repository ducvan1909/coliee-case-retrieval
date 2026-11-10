# Independent tests for M3 Sparse BM25

## Result

The fixture-based sparse tests pass on the current implementation. The suite
compares ranking and float64 scores with a scalar BM25 oracle computed from
fixture text, and checks storage and failure behavior. It does not use the
sealed full-corpus database or alter production artifacts.

## Commands and outcomes

Command:

```powershell
& .venv/Scripts/python.exe -m unittest pipeline_v2.tests.test_m3_sparse_index pipeline_v2.tests.test_m3_lexical_reader pipeline_v2.tests.test_m3_hybrid_dense pipeline_v2.tests.test_m3_hybrid_fusion -v
```

Outcome: **37/37 PASS** in about 2.3 seconds: 11 new sparse tests and 26
existing lexical-reader and hybrid regressions.

The sparse tests cover:

- Unicode/casefolding, punctuation and numeric terms, negation tokens, repeated
  query terms, empty and OOV queries;
- exact scalar-oracle ranking and scores for case and passage channels;
- deterministic ties, raw passage results, unique-case cap and query-case
  exclusion;
- request score reset, sorted unique term/document catalogs, per-term strictly
  increasing document indices, required dtypes, readonly mmap arrays;
- read-only source database, bounded `fetchmany` posting ingestion, rejected
  invalid TF/DF and out-of-universe document IDs;
- missing completion seal, source/index hash drift and semantic array damage.
  Semantic corruption is resealed with recomputed hashes in the test to ensure
  the loader checks array invariants in addition to file hashes.

## Scope limits

These tests validate behavior on generated temporary SQLite fixtures. They do
not establish that the full 415,693-passage sidecar builds, matches all eight
locked full-corpus queries, improves end-to-end hybrid latency, or stays within
the measured memory target. Those require the separately approved real build
and benchmark against the sealed source. No Modal inference, network service,
Qdrant, labels, or full-corpus writes were used by this test suite.

## Remaining qualification

Protocol and numeric parity on synthetic data do not establish retrieval
quality against COLIEE labels. Keep any full-corpus semantic result separate
from this local unit-test status.
