# AU-only runner

This runner accepts one pre-locked `AUOnlyLockedManifest` of 10–20 independent regions. Every request must name an immutable `case_id`, `source_hash`, target IDs and source-offset references; `source_refs[*].target_ids` must cover each expected target exactly once globally. Preflight opens the locked source, checks the hash through the source store, and rejects empty, out-of-range, unordered, or zero-length references before any provider setup. It rejects P2 arms and non-empty ContextHint payloads. It does not create hints, pair arms, or alter the historical `au_baseline` runner.

Offline preflight only:

```powershell
python -m knowledge_base.pipeline_v1.au_only preflight --manifest .\au_only_locked.json --source-store knowledge_base\pipeline_v1\outputs\source_store_v1
```

Remote execution is explicit (do not run until the manifest, caps, credentials, and source hashes are reviewed):

```powershell
python -m knowledge_base.pipeline_v1.au_only run --execute --manifest .\au_only_locked.json --source-store knowledge_base\pipeline_v1\outputs\source_store_v1
```

Source-free endpoint checks (each requires `--execute` and sends no corpus text):

```powershell
python -m knowledge_base.pipeline_v1.au_only warmup --execute --output-root .\outputs\au_only
python -m knowledge_base.pipeline_v1.au_only schema-probe --execute --output-root .\outputs\au_only
python -m knowledge_base.pipeline_v1.au_only full-schema-probe --execute --output-root .\outputs\au_only
```

`schema-probe` requests strict `json_schema` output with only `holding` or `procedural_rule`, then writes `schema_probe.json`; it records config identity and request fingerprint but never tokens, secrets, or source text. `full-schema-probe` sends the exact response schema used by an AU request and validates the source-free response locally. A real run performs this full probe after warmup and before reading or dispatching any source region; a failed probe stops the run.

The locked `spec` must include the exact `model` and `enable_thinking` values, and runtime rejects a different modal configuration. The run cache is keyed by manifest identity and the full locked request. Cached protocol-verified rows are revalidated against the source. A write-ahead cumulative ledger survives resume and reserves/records request, provider-attempt, input, and output-token caps; HTTP/transport usage is represented as unavailable, never zero. A `length`/`content_filter` result is unresolved with its provider usage retained. Protocol validation checks all AU `evidence_spans`, attribution `evidence_span`, and condition/exception/limit spans against exact source offsets and quotes. `complete` means protocol completion only: the runner always writes `semantic_gold=false` and makes no semantic-quality claim.

`run` additionally requires the shared `AU_URL`, `AU_TOKEN`, `AU_MODEL`, `AU_MAX_TOTAL_INPUT_TOKENS`, and `AU_MAX_TOTAL_OUTPUT_TOKENS`. The shared block and all supported caps/warmup keys are in `knowledge_base/.env.example`; copy values only into the ignored `knowledge_base/.env`. Canonical `AU_*` values take precedence field-by-field. `AU_ONLY_*` remains a deprecated compatibility fallback, so it may keep an existing local configuration working but must not be used for new configuration.

AU-only intentionally makes no USD cost claim or enforcement. `AU_MAX_USD_MICROS`/legacy `AU_ONLY_MAX_USD_MICROS` and provider price-rate variables are ignored; request, provider-attempt, and input/output token caps remain mandatory.
