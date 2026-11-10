# M2 Preview Revision 2 — Independent Test Report

**Final bundle:** `pipeline_v2/artifacts/m2_navigation_20261106_v3/`  
**Scope:** preview/navigation structure and raw-source provenance only. This report does not certify legal relevance, quotation ownership, or semantic sentence completeness.

## Result

The final frozen candidate passed all **56 tests** and both final whole-corpus checks. The sealed v3 bundle contains 7,708 cases, 382,343 navigation units, 454,275 previews, and 216,946 anchors.

The v3 independent audit checked each preview against raw bytes and pinned M1 structure. It found:

- 240 Unicode codepoints as the maximum preview length.
- 454,275/454,275 previews with `partial_sentence=null` and `content_window_not_sentence_verified`.
- Zero preview pairs where one window fully contains the other.
- Zero word-boundary and protected-tag clipping flags; every clipping flag matched an independent raw-character/tag-span predicate.
- All nine protected-tag clipping cases recorded in v2 are clear in v3.
- Navigation IDs, unit spans, handles, parent and neighbor mapping, anchor catalogs, source-anchor catalogs, headings, and raw/M1 fingerprints match the prior bundle.
- Token readiness remains `not_ready`; model request/retry/token counts are zero. No inference, model download, embedding/index build, or Modal deployment ran.

The 267 units without a display preview remain cataloged and navigable; they had no meaningful opening or selected display window under the current rules. Six short-opening cases were retained as heuristic diagnostics for possible manual spot-checking. Neither count measures semantic preview quality.

## Confirmed v2 defect and correction

The first sealed revision (`m2_navigation_20261106_v2`) split a 21-character `<FRAGMENT_SUPPRESSED>` tag in nine long-cue tail windows. A synthetic long-cue example reproduced the same boundary behavior for both a protected tag and an ordinary word. The boundary adjustment was rejecting a safe move because it required the new start to remain before the long cue's original focus start.

The fix allows a clipped long-cue window to advance to a safe boundary while preserving nonempty overlap with the cue. Fully fitting anchors continue to retain their full-span constraint. A raw-source regression now checks all nine v2 cases against their original M1 units and source bytes.

The v2 bundle and its audit are preserved as a checkpoint; they are not the final result. The final v3 independent audit reports zero such clips.

## Commands and verification

Final test suite:

```powershell
.venv/Scripts/python.exe -m unittest discover -s pipeline_v2/tests -v
```

Result: **56 passed**, 2.607 seconds. Includes synthetic long-cue tag/word-boundary cases, tie-breaking determinism, eight actual-source opening cases, and all nine v2 clipped-tag regressions.

Final official bundle validator:

```powershell
.venv/Scripts/python.exe -m pipeline_v2.m2 validate --repo-root . --bundle pipeline_v2/artifacts/m2_navigation_20261106_v3
```

Result: `valid=true`; 7,708 sources, 382,343 units, 454,275 previews, 216,946 anchors; 288.921 seconds.

Independent raw/M1 before-and-after audit (does not import the M2 builder or validator):

```powershell
.venv/Scripts/python.exe pipeline_v2/reviews/m2_preview_revision2_validation/independent_preview_audit.py --root . --old pipeline_v2/artifacts/m2_navigation_20261105_v1 --new pipeline_v2/artifacts/m2_navigation_20261106_v3 --output pipeline_v2/reviews/m2_preview_revision2_validation/m2_navigation_20261106_v3_full_corpus_audit.json
```

Result: `PASS`, zero errors, 58.171 seconds. The result JSON includes same-handle raw-source examples for the eight regression cases, as well as the raw checks and catalog invariants.

The v3 build completed once and was sealed write-once; build receipt is `pipeline_v2/artifacts/m2_navigation_20261106_v3.build-receipt.json` (289.514 seconds). V2 audit attempts and checker corrections are recorded in `pipeline_v2/reviews/m2_preview_revision2_validation/audit_attempt_history.json`; the v2 raw-tag cases are preserved in `pipeline_v2/reviews/m2_preview_revision2_validation/m2_navigation_20261106_v2_audit_checkpoint.json`.

## Test and audit corrections retained

The first draft of the nine-case regression looked up M2 unit IDs in the wrong M1 partition and produced nine `StopIteration` setup errors. It now reads the pinned M1 v2 source records; all nine source cases pass. This was a fixture mismatch, not a production failure.

The independent audit first failed before scanning because of an obsolete fixed M1 path. A later diagnostic mislabeled 292,722 previews ending in a word character as mid-token clips because it did not inspect the next raw character. Both are preserved with explicit invalid status in the audit attempt records. The final audit compares word flags to adjacent raw Unicode characters and tag flags to protected-tag spans. The v2 audit then exposed nine true tag splits; v3 reports zero. These checker corrections did not alter either sealed bundle.

## Limits

The six short-opening diagnostics need human review if the product requires a minimum-length opening. Sentence completeness remains intentionally unknown. Preview protocol/provenance PASS does not show that previews improve retrieval or agent decisions. Embedding and agent-tokenizer snapshots/token preflight remain unselected or unvalidated for this M2 navigation bundle, so token counts and token-validated chunks remain `not_ready`.
