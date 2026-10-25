# Plan 09 R3 re-audit: first-10 items 02, 06, and 10

Date: 2026-10-05  
Scope: read-only re-audit of exactly three revised effective heads. All results remain model-only/model-silver.

## Decision

**Accept all three revisions: items 02, 06, and 10.**

No canonical proposal, amendment, review, queue, registry, or progress artifact was modified by this audit. P09-S01 remains outside scope and unchanged; this decision does not unlock Plan 10.

## Locked inputs

- Raw source: `source_store_v1/cases/011904/versions/c2bc.../source.txt`
  - SHA-256: `c2bc7c0944a5ee103368055f7d2f0e3c260d4bb8336d406c3d01733304c96b12`
- Effective review heads:
  - item 02: `p09-r3-first10-audit-02-gpt61sol-v2`, SHA-256 `9541e45435009fddda3c32d242f8f7780f0ea3ff2d13bb48a1f5953742c990d5`
  - item 06: `p09-r3-first10-audit-06-gpt61sol-v2`, SHA-256 `41ce7a307cc3b032d212d51a9a9ab73d2608a51dea6ee237e3c6f39548810dec`
  - item 10: `p09-r3-first10-audit-10-gpt61sol-v2`, SHA-256 `679c61f68994c53a6bdf5c3642f321e423fe847189aca0c3a4fdb59ff831e6ea`
- Effective amendment heads:
  - item 02: `p09-r3-first10-audit-02-gpt61sol-v2`, SHA-256 `e6bcc2742c6039b71c92d4ff65eadd7200e7490dd8abdeae3bc4b4f1bf5f0663`
  - item 10: `p09-r3-first10-audit-10-gpt61sol-v2`, SHA-256 `33db855e7e081e9a1327a5fd92dc1f937e56ff01fbb3f1c1c42c34732776f058`

## Item 02 — accept

The effective AU now correctly preserves all material qualifications from paragraph 16:

- condition: `claimants from developed democratic states`;
- limit: that high burden does not require placing themselves in danger to exhaust protection avenues;
- exception: requiring such danger constitutes an exceptional circumstance;
- speaker: `current_court`, supported by “I remain of the view” and “in my opinion”;
- kind: `procedural_rule`.

The condition, exception, and limit witnesses are exact spans within raw source `[8358,9331)`. The claim no longer generalizes beyond the developed-democracy context. Review and amendment validators PASS.

## Item 06 — accept and retract prior finding

The previous audit's `quote_mismatch` finding is **retracted**.

Direct byte/code-point verification shows:

- raw bytes at `México`: `4d c3 a9 78 69 63 6f`;
- decoded code points: `U+004D U+00E9 U+0078 U+0069 U+0063 U+006F`;
- raw source contains `U+00E9`, not `U+FFFD`;
- both v1 and v2 review quotes contain the same `U+00E9` and exactly match source offsets `[15576,16864)` and context `[15076,17364)`.

Root cause of the false finding: the earlier ad-hoc audit command loaded UTF-8 JSON through Python `open()` using the Windows preferred encoding `cp1252`. UTF-8 bytes `C3 A9` were therefore interpreted as two characters `U+00C3 U+00A9`, increasing the in-memory quote length by one and producing a false mismatch. The visible replacement glyph in terminal output was a console-rendering artifact; it was not `U+FFFD` in the source string.

Using repository `load_json`/UTF-8 decoding, `validate_risk_review` PASSes. The semantic `keep` decision is supported: paragraph 29 states the Board omitted contrary documentary evidence; reported statistics illustrate that evidence and are not promoted into independent court findings.

## Item 10 — accept

The revised amendment restores a narrowly scoped positive AU:

- claim: in review of this principal applicant, the court found the Board faced abundant evidence indicating the protective measures were ineffective;
- kind: `holding`;
- speaker: `current_court`;
- exact proposition evidence: raw source `[15089,15203)`;
- neighboring support: paragraph 28 gives the contradictory-evidence rule and paragraph 34 expressly finds Board error.

This avoids the earlier over-conservative `unresolved` outcome without turning the proposition into a general claim that all Mexican protection is ineffective. Review and amendment validators PASS.

## Lineage and validation

- Each v2 risk review points to the exact SHA-256 of its v1 predecessor.
- Item 10 amendment v2 points to amendment v1 SHA-256 `1e6dca92da20681fbbb4b9465707a3a57ae68a073f71ddcdf761db0bdd4dac18`.
- Item 02 starts an amendment lineage because its v1 decision was `keep`; this is not a fork.
- `risk_review_heads` returns one head per audited identity; `amendment_heads` returns one head per amended target.
- No predecessor file was overwritten, and no fork or cycle was detected.
- Read-only revision-history and risk-review tests: **7/7 PASS** in 53.277 s.

## Boundary

The coordinator may accept these three revised heads. This conclusion says nothing about the other 20 records, does not close P09-S01, does not establish human gold, and does not open Plan 10.

