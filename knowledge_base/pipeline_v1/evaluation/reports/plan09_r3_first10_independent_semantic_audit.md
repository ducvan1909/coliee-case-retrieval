# Plan 09 R3 first-10 independent semantic audit

Date: 2026-10-05  
Audit lane: independent model-only review; all conclusions remain model-silver.

## Decision

**Reject the batch as a single coordinator acceptance unit.** Seven records are acceptable as written, two require semantic correction, and one is structurally invalid against the raw source.

- Accept: items 01, 03, 04, 05, 07, 08, 09.
- Revise: item 02 and item 10.
- Rebuild exact spans, then revalidate: item 06.
- P09-S01 is not one of these ten records. This audit does not close or alter that finding.

The audit read case `011904` through `open_source` and compared each target plus neighboring context with the original AU and any linked amendment. No proposal, amendment, queue, registry, or risk-review record was changed.

## Item findings

| # | Target | Audit | Severity | Source-grounded assessment |
|---|---|---|---|---|
| 01 | `at-166e883b4b22f4c136190986` | agree | none | Paragraph 10 applies reasonableness and expressly uses the justification/transparency/intelligibility and defensible-outcomes formulation. `standard_of_review/current_court` is supported. Evidence: raw source `[5400,6085)`. |
| 02 | `at-2f7477cfb9547856d31ae73a` | **disagree** | moderate | Current-court voice is clear, but `keep` preserves an over-broad claim with no qualification witnesses. Paragraph 16 is expressly about claimants from developed democratic states and characterizes danger as an exceptional circumstance. The record should route an amendment that captures at least the developed-democracy condition and danger/exception qualification. Evidence: `[8358,9331)`, especially “While the burden placed on claimants from developed democratic states...” and “would constitute an exceptional circumstance”. |
| 03 | `at-056fd4ca0454c65c2b585cea` | agree | none | “I am of the view that the Board erred” is an explicit current-court holding, followed by allowing judicial review. Evidence: `[20340,20493)` and paragraph 35. |
| 04 | `at-0802db7ceff18ea43d1a3387` | agree | none | The amendment correctly changes `holding` to `procedural_rule`, retains current-court voice, and records the no-deference limitation while preserving the duty to address contradictory evidence. Evidence: `[18316,19533)`. Amendment validator PASS. |
| 05 | `at-b6e11fcb6b0d65c364d63d7b` | agree | none | Paragraph 33 is the reviewing court's critique: the Board omitted the Human Rights Commission complaint and paradoxically relied on an avenue its own cited report described as ineffective. Paragraphs 34–35 connect this critique to the disposition. Evidence: `[19541,20332)`. |
| 06 | `at-c6800dac79406967a0f487af` | agree semantically, **invalid record** | high/blocking integrity | The claimed Board omission is supported by paragraph 29, and the reported statistics remain evidence rather than court findings. However, `target_span` and `context_spans` do not match raw source: the record stores `México`, while `open_source` contains the replacement character in `M�xico`. Both quotes are one code point longer than their indexed raw spans. `validate_risk_review` raises `quote_mismatch`. Evidence offsets: target `[15576,16864)`, context `[15076,17364)`. |
| 07 | `at-e6d8b4b85d3ed8642bf952df` | agree | none | The amendment correctly treats paragraph 28 as a general procedural reasons-giving rule and records the contradictory-evidence condition. “This Court has consistently held” supports current-court adoption. Evidence: `[15211,15568)`. Amendment validator PASS. |
| 08 | `at-d2edd223db1b214b6af3212a` | agree | none | The appellate quotation supplies authority, while the separate sentence beginning “Thus” is the current court's adopted proposition. `procedural_rule/current_court` is supported. Evidence: `[7282,7771)`. |
| 09 | `at-fa73738e43e28d91717f8a07` | agree | none | Paragraph 15 reports Court of Appeal doctrine and contains no separate current-court adoption sentence. The amendment correctly uses `cited_court` and records both the developed-democracy condition and exceptional-circumstances exception. Evidence: `[7779,8350)`. Amendment validator PASS. |
| 10 | `at-8269eb428258043e32dca5a8` | **disagree** | moderate | The move to `unresolved` is too conservative. Paragraph 27 is the current reviewing court's case-specific finding that the Board faced abundant evidence showing ineffectiveness; paragraphs 28–34 use that finding to establish reviewable error. “Not clearly reusable” is not enough to erase a supported case-specific holding. Prefer retaining a scoped `holding/current_court`, optionally with cross-block support to paragraph 34, rather than hard-negative or unresolved. Evidence: `[14834,15203)` with paragraphs 28 and 34. |

## Structural verification

- All four linked amendments (04, 07, 09, 10) pass `validate_amendment` in the audited snapshot.
- Nine of ten risk-review records pass `validate_risk_review`.
- Item 06 fails deterministically with `quote_mismatch`; therefore the persisted first-10 validation claim is no longer true for the bytes audited here.
- Read-only unit tests `test_plan09_risk_reviews` and `test_plan09_remediation` report 9/9 PASS, but this does not override the direct item-06 validator failure. The discrepancy indicates the checked-in test path did not reliably expose this exact malformed record during the concurrent update window.

## Coordinator action

Do not accept the first-10 batch wholesale. The coordinator may accept items 01, 03, 04, 05, 07, 08, and 09 individually. Before batch acceptance:

1. replace item 02 `keep` with an amendment that preserves its explicit condition/exception witnesses;
2. rebuild item 06 target/context spans exclusively from `open_source` and rerun `validate_risk_review`;
3. reconsider item 10 as a scoped `holding/current_court`; if disagreement persists, retain unresolved but record the independent disagreement rather than treating it as accepted;
4. regenerate derived validation/progress reports only after those immutable corrections are checkpointed by the coordinator.

This audit neither creates human gold nor establishes semantic precision/recall.
