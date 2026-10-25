# Plan 03 — SourceBlock contract

## Scope

Plan 03 is a local deterministic structural pre-pass over the immutable KOS-5
`CaseSource` records. A `SourceBlock` records an observed source range. It is not
a `SentenceAtom`, `AnalysisRegion`, `LegalUnit`, `AuthorityUnit`, or semantic
heading.

The raw source store is authoritative. KOS artifacts remain audit-only and are
not labels or gold data.

## Exact partition

- All offsets are half-open Unicode-codepoint offsets after `utf-8-sig` decode.
- Ordered leaf block spans partition the complete source with no overlap or gap.
- Concatenating exact spans in `order` must reproduce the source exactly.
- Separator whitespace is attached to the preceding block. Leading or
  all-source whitespace is represented by a `whitespace` block.
- A numbered paragraph keeps embedded quote/list material in the same leaf.
  Such observations are nested sidecar spans and never overlapping child blocks.

`marker_span` identifies only a paragraph marker. `content_span` excludes that
marker and surrounding separator whitespace. Both remain subordinate to the
canonical full `span`.

## Conservative interpretation

`heading_candidate=true` means only that a line matched a formal structural
signal. It always produces a review event and does not assert heading semantics.
No tree is required. No relations are materialized in v1; adjacency is derived
from block order.

Bracketed years from 1800 through 2099 are protected from paragraph-marker
classification. Citation, quote, and list matches are observational candidates.

## Identity, cache, and invalidation

The cache key is SHA-256 over UTF-8 canonical JSON (sorted keys, compact
separators) of this named-field payload:

```json
{"case_id":"...","source_hash":"...","parser_version":"...","policy_sha256":"..."}
```

A block ID is `sb-` plus the first 24 hexadecimal characters of SHA-256 over
the same canonical encoding of:

```json
{
  "identity_contract": "sourceblock-id-v1",
  "case_id": "...",
  "source_hash": "...",
  "parser_version": "...",
  "policy_sha256": "...",
  "order": 0,
  "span": {"start_char": 0, "end_char": 10},
  "block_type": "numbered_paragraph"
}
```

The validator recomputes both identities. It also requires every block,
SpanRef, nested span, and parser event to match map-level case/source/parser and
policy provenance. When an artifact path is supplied, its suffix must be
`cases/<case_id>/<source_hash>/<parser_version>-<policy-prefix>/block_map.json`.

Parser events use `sourceblock-event-v2`. Each event is bound to a canonical
`event_type -> severity + message_code + message` specification and to its
related `block_id`/`block_order`. Its ID hash covers all of those fields plus
case/source/parser/policy provenance and exact span. Changing a review event to
`info`, rewriting its message, or moving it to another block is therefore a
contract violation rather than a cosmetically valid audit record.

Artifacts live below that dependency-addressed directory and are never
overwritten with different bytes. Any source hash, parser version, or policy
change creates a different cache identity and block identity.

## Gate meaning

PASS proves schema validity, exact coverage, zero gap/overlap, exact round-trip,
stable IDs/order, KOS-5 dependency hashes, and absence of parser error events.
It does not prove semantic segmentation quality or generalization beyond KOS-5.

Run:

```powershell
python -m knowledge_base.pipeline_v1.structural_prepass
```

The terminal prints one status line. Detailed results are written to
`reports/plan03_structural_validation.latest.json`; the human audit view is
`reports/plan03_block_audit.html`.
