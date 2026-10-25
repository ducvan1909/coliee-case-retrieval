# Offline region priority rule pilot

Run from repository root with the existing venv:

```powershell
.\.venv\Scripts\python.exe -m knowledge_base.pipeline_v1.region_priority_offline run --output-root knowledge_base/pipeline_v1/outputs/region_priority_offline_20261013
```

The API exports `extract_features(text)`, `build_inventory(**input_paths)`,
`schedule(inventory, arm, budget=None, bytes_per_token=4)` and
`run(output_root=..., kos_root=..., **input_paths)`. `build_inventory` accepts
`kos_manifest`, `source_store`, `block_manifest`, `atom_manifest`, `block_policy`,
and `atom_policy`; defaults bind exact5 and the existing validated policies.
Arms are `multi_queue`, `source_order`, `cue_control`; aliases `round_robin` and
`old_cue` are accepted. Budgets use per-packet ceil UTF-8 bytes/divisor, including
JSON IDs, exact source text and the shared offline scaffold. This is an estimate,
not a Qwen tokenizer or the full production extraction prompt.

All blocks, including metadata, remain in inventory and exhaustive schedules.
Source feature anchors address immutable atoms. Repeated occurrences saturate;
previews and KOS fields are never feature inputs. Negation is retained as an
explicit cue without semantic interpretation. Context spans are unioned within
each packet and kept separate from TARGET. Raw adjacent/reference context is a
hint only, capped at 6,000 characters and 12 merged intervals; omitted context
obligations remain unknown. Ambiguous/external paragraph references do not attach
local paragraphs. Long targets are not truncated or marked negative.

`inventory.json` holds full spans, features, exact serialized packets, costs and
bindings. `report.json` contains frozen exhaustive schedules, all budget schedules,
per-AU alignment/exposure/context packets, source coverage, transformation audit,
implementation fingerprints and limitations. `summary.json` and `summary.md`
provide concise counts and curves. Report files must be fresh; the authorized
Main snapshot and tester directory may already exist and are preserved.

KOS is loaded/hash-verified only after schedules are frozen. Only unique exact or
whitespace-only aligned evidence enters the diagnostic denominator; ambiguous,
empty and no-match records remain in the audit. Full TARGET exposure is measured
by cumulative union, separately from CONTEXT. No exposure metric establishes
semantic assessment, qualified evidence, gold recall or semantic stopping.
Learned semantics, NER and embeddings are absent. No network, inference, install,
deploy or production integration exists in this module.
