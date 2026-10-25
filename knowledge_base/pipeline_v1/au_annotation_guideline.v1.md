# AU annotation and adjudication guideline v1

## Evidence boundary

Raw `CaseSource` text and its immutable hash are the only semantic evidence. Every annotation span is half-open `[start_char, end_char)`, includes the verbatim quote and quote SHA-256, and must reopen against the locked source. Plan 03–07 artifacts provide addresses and structural review cues only. KOS artifacts, old-pipeline output, sidecars, model output and Codex output are not human gold.

Blank tasks cover each of the 369 KOS-5 primary targets exactly once. Slices remain work-item refs under their parent target. Structural hard-case/cross-block triggers mean “review here”; they are not AU, speaker, treatment, condition or no-AU labels.

## Human AuthorityUnit

An AU requires a human-entered claim and at least one exact evidence span. Owner is the primary target/block containing the first evidence character. Additional cross-block spans are allowed and must independently reopen. Record field-level witnesses for attribution/speaker, condition, exception and limit; a citation mention or sidecar must never imply treatment or current-court voice.

Initial kinds are `holding`, `standard_of_review`, `statutory_hook`, `procedural_rule`, `fact_pattern_rule`, and `foreign_law`. Use `other` with `other_kind`, or `unresolved_kind`; never force a misleading enum.

Exact duplicate proposition spans are forbidden. Partial overlap is permitted only when both AUs are marked `distinct_supported` and the notes explain why they are distinct. Fragment/duplicate uncertainty goes to adjudication.

## Hard negatives

An explicit negative is valid only after the entire target span is reviewed. Allowed reasons are `party_argument_only`, `fact_only`, `procedural_history_only`, `citation_without_proposition`, `editorial`, `insufficient_context`, and `other`. “No AU found” cannot be inferred from processing status, budget stop, missing citation or an empty model response.

## Independent annotation and adjudication

Annotator A and B work blind: neither submission may expose the peer ID or content. A completed submission covers every packet target with either AU records or a full-target hard-negative decision. Comparison records span, kind, field-presence and negative-vs-positive disagreements.

Only a named human adjudicator who reopens exact source may issue `adjudicated` decisions. Human gold locks only after two distinct human submissions plus adjudication, except a documented named-human override. Draft, single-annotator and model records never become gold merely by changing status.

## Terra silver lane

`gpt-5.6-terra` at low reasoning may create `model_proposed` calibration/development records under prompt v1. Every proposed target must carry a review trace: task/target id, source hash, target-text checksum, P2a/P2b region id/fingerprint, and a checksum of the exact decision. A review must identify a positive AU, a reviewed hard negative, or a specific unresolved reason. Blanket abstention is forbidden: unresolved is not a hard negative, no-AU, semantic coverage, or silver readiness.

A host-validated lock is `model_adjudicated_silver`, never human gold. Any downstream score must state `evaluation_against=model_silver`; silver cannot unlock held-out quality claims.

## Held-out and few-shot

Held-out case IDs and source hashes are locked without labels. Held-out records cannot change guideline, prompt, thresholds or label mapping and cannot enter few-shot selection. Few-shot examples come only from locked human-adjudicated calibration/development gold. Until such gold exists, the manifest remains empty and blocked.
