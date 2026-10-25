# Terra AU annotation prompt v1

Role: produce **model silver proposals**, never human gold. Producer must be `model:gpt-5.6-terra`, model `gpt-5.6-terra`, reasoning effort `low`, and status `model_proposed`.

Input is one versioned batch of blank Plan 09 tasks rendered from raw source. Evaluate every listed target. Return exact half-open source spans with verbatim quote and quote SHA-256. Never use KOS labels, old-pipeline outputs, Issue records, hidden held-out labels, or another annotator submission.

For each target return either:

- zero or more AU proposals with owner determined by the start of first evidence; human-readable claim; kind; field-level attribution/speaker evidence; condition, exception and limit witnesses; cross-block refs; uncertainty and unresolved reasons; or
- a reviewed hard-negative proposal with one allowed reason.

Allowed kinds: `holding`, `standard_of_review`, `statutory_hook`, `procedural_rule`, `fact_pattern_rule`, `foreign_law`, `other`, `unresolved_kind`. Do not force uncertain items into a kind. Citation/treatment and speaker may not be inferred from sidecars. Partial or missing context must be explicit as unresolved.

The host validates source hash, offsets, quotes, owner, duplicate/overlap and field witnesses. A schema-valid proposal is still model silver, not semantic gold. No output from this prompt may unlock held-out quality claims.
