# Plan 04 — SentenceAtom, protected spans, and derived slices

SentenceAtom is only an exact address inside one validated SourceBlock. It is
not a legal proposition, semantic sentence, LegalUnit, AU, or retrieval
candidate. The canonical artifact stores only IDs, provenance, and SpanRefs;
source text remains in the immutable source store.

## Coverage

The segmented scope is the complete SourceBlock span, including an inherited
paragraph marker and attached whitespace. Ordered atoms cover each parent block
exactly once with no gap or overlap. This makes every source character
addressable and preserves exact per-block and case round-trip.

`parent_block_refs` copies only Plan 03 identity and span metadata—block ID,
order, full span, content span, marker span, parser version, and policy hash—so
marker/content lineage is explicit without duplicating source text.

## Protection modes

`boundary_forbidden` is a hard segmentation constraint. Atom boundaries may not
fall inside or immediately after the terminal punctuation of abbreviation,
initial, reporter citation, case name, decimal/section reference, citation year,
paragraph marker, or list marker spans.

`context_only` is an annotation, not a boundary lock. Balanced/unbalanced
quotation and newline/layout spans may contain valid sentence boundaries.
Unbalanced quotation is routed to review rather than silently treated as a
closed protected region.

## Identity and invalidation

Cache identity includes `case_id`, `source_hash`, the validated SourceBlock map
cache key, segmenter version, and sentence policy hash. Atom, protected-span,
slice-plan, and event IDs use canonical named-field JSON payloads. Validation
re-runs the deterministic producer and compares the complete artifact, in
addition to schema, provenance, containment, coverage, and path checks.

## Derived slice plans

The configurable `max_chars` cap is model-independent. Only blocks exceeding
the cap receive a `DerivedSlicePlan`; slice boundaries are SentenceAtom
boundaries. An atom larger than the cap is retained intact and routed to review.
Plans keep `parent_block_id` and exact spans, contain no text, and create no new
SourceBlock, LegalUnit, AnalysisRegion, or candidate.

Run:

```powershell
python -m knowledge_base.pipeline_v1.sentence_atoms
```

The terminal prints one status line. Detailed results and the audit view are
written to `reports/plan04_sentence_atom_validation.latest.json` and
`reports/plan04_sentence_atom_audit.html`.
