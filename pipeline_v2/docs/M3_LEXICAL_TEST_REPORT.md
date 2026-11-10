# M3 lexical reader: independent test report

## Result

The independent behavioral suite passed **14/14 tests**. The same run combined
with the existing M3 Optimization V2 regression suite passed **32/32 tests**
(14 new lexical tests + 18 V2 regressions).

Commands, run from the repository root:

```powershell
.venv/Scripts/python.exe -m unittest pipeline_v2.tests.test_m3_lexical_reader -v
.venv/Scripts/python.exe -m unittest pipeline_v2.tests.test_m3_lexical_reader pipeline_v2.tests.test_m3_opt_v2_index pipeline_v2.tests.test_m3_opt_v2_session pipeline_v2.tests.test_m3_opt_v2_runtime pipeline_v2.tests.test_m3_opt_v2_benchmark pipeline_v2.tests.test_m3_opt_v2_cli -v
```

Final outcomes: first command `OK`, 14 tests in 0.835s; combined command
`OK`, 32 tests in 1.554s. Both ran after the reader implementation was frozen
for the full-corpus benchmark.

## What the new tests cover

- Independent BM25 oracle, using a separate Python `Counter`/float64 formula;
  exact ranking IDs and scores within `1e-12` for both `case` and `passage`.
- Unicode case-folding, citation digits/punctuation, negation terms, repeated
  query terms, empty and OOV queries, and fresh score accumulation per request.
- Query-case exclusion before the result cap, deterministic score ties, large
  limits, and unique-case selection before its cap.
- More than one fetch block: 4,097 postings result in requested fetch blocks
  `[4096, 4096, 4096]` returning `[4096, 1, 0]` rows.
- Rejection of invalid channel, limit, query-case ID, and mode; SQLite opens
  read-only and does not mutate the fixture database.
- Sticky invalidation for lexical profile/code drift and full-runner
  profile/implementation drift (guard dependencies mocked; no sealed run
  changed).
- CLI `--help` and module import with Modal/Qdrant environment variables
  removed; no Modal import, Qdrant reader, or vector load path in the lexical
  module.

Fixtures use temporary SQLite files in temporary directories. The tests do not
access the sealed full-corpus lexical DB, Qdrant, Modal, credentials, labels,
gold data, or vector artifacts. The existing 18 V2 tests remain unchanged and
pass in the combined run.

## Limits of this validation

This establishes local reader behavior and arithmetic parity on controlled
fixtures. It does not establish ranking parity on all full-corpus queries,
latency or memory improvement, search quality against COLIEE labels, or
end-to-end `LexicalSession` behavior against the sealed production snapshot.
The actual eight-query full-data parity and timing run is a separate Main-owned
benchmark; no semantic relevance or COLIEE quality claim follows from these
protocol tests.
