# Plan 09 R4 fourth10 corrections — independent re-audit

Report revision: **1**. Audit date: 2026-10-06. Scope is exactly the two audit-bound correction overlays; the other 367 effective reviews were checked for hash preservation, not semantically re-audited.

## Verdict

**PASS — BOTH CORRECTIONS ACCEPTED.** The two moderate findings from the original fourth10 audit are closed. No additional finding was identified within this correction scope.

The effective model-silver totals are now **188 AUs, 186 hard negatives and 8 unresolved**, with **369/369 reviewed, 0 missing and 0 duplicate targets**. This does not set R5 PASS: `semantic_gold=false`, `R5=false`, and Plan 10 remains locked until the separate R5 final audit.

## Correction findings

| Target | Result | Independent assessment |
|---|---|---|
| `at-36d2799e80bf0e3f5421c6cf` | accepted; finding closed | The AU correctly records only the current court's characterization of the issue as jurisdictional, if not a vital legal question requiring correct PSEA interpretation. It does not decide that the Commission lacked jurisdiction or settle the agency review standard. Paragraphs 93 and 183-184 correctly preserve the final-ruling reservation. |
| `at-3bf2d5382a3dbb34d161b87b` | accepted; finding closed | `hard_negative: party_argument_only` is correct because paragraph 62 expressly says the applicant argues. Paragraph 63 postpones assessment; the overlay does not invent a universal personal-gain requirement for fraud. |

## Integrity and coverage verification

- Both amendments pass the dedicated R4 amendment validator.
- Both persisted sidecars exactly equal independently recomputed validation results.
- Effective review hashes changed for exactly the two intended case-target keys; all other 367 are unchanged.
- All 615 frozen preservation hashes match, including the original fourth10 batch, proposals, sidecars and initial independent audit.
- Original proposal hashes remain `8dbdeac9…` and `2561bca4…`; corrections are overlays, not rewrites.
- Coverage revision confirms 369 expected/reviewed, 0 missing, 0 canonical duplicates and exact case-target-set verification.
- Count delta is exactly `+1 AU`, `+1 hard negative`, `-2 unresolved`.

## Locked artifacts

| Artifact | SHA256 |
|---|---|
| Original fourth10 independent audit | `d70fcedd0c66dfe73af05dfb0df1c710c96969e8dfd1e7a9b5f3c99340d6319a` |
| Correction frozen inventory | `ca7e38eb307efe011593f9dd3d5ba7562a0301df0078441e698d5378865db717` |
| Correction validation | `36c055ce31f0e337de682a8632eb328a365e7c4b836fbdfd685e93525b97ede4` |
| Corrected coverage revision | `4cdef57ec3235fad7ec4b970133e4479e94422154f229d1792aeb5c429e82718` |
| Completion verification | `ed69df81a43597f0a0c02b9fff20e469ebbdbfe67c666fa7f0260a1cd991dbd4` |
| Correction 01 / sidecar | `422d148137758f13f3c4d97f4e5c1ae0515db26e399206874352cbae2a1ca758` / `891421645f49ca802611b722bd132a5350f39d33355e60307197f539c9119e7c` |
| Correction 02 / sidecar | `77b517a849d5b1c03d08f1dc0f3290b81962494af065000281fba0d4bac36c8e` / `87a160e62ebb7ee10b9efb3345f4de4ec123869fa2d2e7f5ce6b80328ef3cec2` |

## Gate boundary

This re-audit closes only the two fourth10 correction findings. It does not independently re-audit the remaining corpus, turn model-silver into human gold, set R5 PASS, or unlock Plan 10.
