# Plan 09 R4 fifth10 — independent semantic audit

Report revision: **1** (initial; supersedes none). Audit date: 2026-10-06. Independent reviewer: `gpt-5.6-sol` low. Producer: `gpt-6.1-sol` low.

## Verdict

**PASS WITH QUALIFICATIONS** for exactly frozen batch `p09-r4-099980-fifth10-sol-v1`: **10 agree, 0 disagree, 0 insufficient**; 3 AUs, 6 hard negatives and 1 unresolved. Items 1, 7 and 10 have low-severity qualifications. **No severe findings** and no canonical correction are required.

These records remain model-silver, not human gold. This audit does not complete R5 and does not unlock Plan 10. No target outside fifth10 was audited and no canonical artifact was modified.

## Item findings

| # | Target | Verdict | Independent assessment |
|---:|---|---|---|
| 1 | `at-3c30af827186591d2bf66be2` | agree / **low** | Paragraph 45 is current-court procedural guidance and supports the claim. Qualification: it is case-specific; paragraphs 43/46 show the respondent's special representative role and that the Court nevertheless considered the arguments because the applicant did not object. The paragraph-46 witness is present. |
| 2 | `at-3e39044f97b84404b520022e` | agree / none | Paragraph 94 is explicitly applicant allegations. Later agreement does not change this target's speaker. |
| 3 | `at-3e97359dc0a6d7669025040b` | agree / none | Paragraph 172 reports the agency report and agency guilt determination. It is not a current-court conviction or legal test. |
| 4 | `at-41ba0116a63ebb7c839e9149` | agree / none | Paragraph 91 is the applicant's conjunction/ancillary-power argument. The court never finally adopts it. |
| 5 | `at-422fbd7f49cb2cff502c7399` | agree / none | Paragraph 152 expressly rejects the respondent's legitimate-expectations position. Current-court attribution and investigation-specific scope are correct. |
| 6 | `at-4751d840ca72860653e65cd8` | agree / none | Paragraph 131 is factual evidence appraisal; it does not create a universal duty to interview managers. |
| 7 | `at-47a655a27ed5534b3a17e956` | agree / **low** | Only the final sentence is court voice; earlier sentences are respondent advocacy. The primary sentence is referential, so the full target and paragraph-152 cross-reference are indispensable. Both are preserved, and the claim avoids a universal no-cure rule. |
| 8 | `at-49def3d233262fffd76bbd5a` | agree / none | Paragraph 4 reports the challenged Commission decision. The fraud finding is agency history, not a court guilt finding. |
| 9 | `at-49ed1261d578f869e56746d2` | agree / none | Paragraph 88 is case history plus a rhetorical referral criticism; it does not transform Review Team recommendation 3.1 into binding law. |
| 10 | `at-4b1f384513ca1b440639bff3` | agree / **low** | Paragraph 76 is current-court analytical doubt, but paragraph 93 expressly reserves a final ruling. The recorded remote reservation is mandatory; `unresolved` is more faithful than a settled standard-of-review AU or hard negative. |

## Technical checks and snapshot

- Frozen batch SHA256: `37c17bb8e21fc9bee70fd334d38a7cce3d839352e66abd56cf9afbab0d194f55`.
- Raw source computed/declared SHA256: `49d56b1477fed32e9c45e52582884818f7632735542b22388911fccd602f2319`.
- All ten proposals pass `validate_model_proposal`; exact source identity, half-open spans/quotes, region identity and review-trace checksums revalidated.
- All ten sidecars exactly equal freshly recomputed validation results.
- All producers are exactly `model:gpt-6.1-sol` / `gpt-6.1-sol` / `low`, prompt `r4-au-annotation-prompt-v1`.
- Current registry read found one owner per target. Checkpoint and rebuild paths reject duplicate ownership with `checkpoint_duplicate_target`.

| # | Proposal SHA256 | Sidecar SHA256 |
|---:|---|---|
| 1 | `81f47afe1507599628f188bb7bd6ab3b7f9ff63bbad8de953ed2630911c2b8af` | `a8d651f4b76b1bf246e53c75c2eb3bb78688d350cf9be25d25801dbd24a731ac` |
| 2 | `ba43dce9893a17dd3f349ad5d6569922de53762446a5d04d40862266a01dbd9d` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 3 | `b403a0ed3cb96ba5ae75c3aed9813356f59f8d02fca044872883d6687a17d7e2` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 4 | `2faf8f03ab6ebed59e9ccdfa1fa77ae3bc16c6f639163acf0fba513b0414d9f0` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 5 | `387b49adcb75adf8ebcc0700cac71125ce4e87bcf0edd02c63e369f337c2f2e3` | `a8d651f4b76b1bf246e53c75c2eb3bb78688d350cf9be25d25801dbd24a731ac` |
| 6 | `4eca229f5aaae1d53e65376ccfb363882124a2acf5f4f35d7662ca25cd108099` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 7 | `9b0f44eb41440c112de5a5460f47bee84b3211f2942430e1933aa340f099e853` | `a8d651f4b76b1bf246e53c75c2eb3bb78688d350cf9be25d25801dbd24a731ac` |
| 8 | `c1eb6a8f62773d4cf54091f96a2df2fc34fb96c4ffd150eee3cc2a68aa6455be` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 9 | `36c96ee61adbdbfb53d760611f1137e66fa25260bbe37b851f09eff1d0301bd6` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 10 | `fb5f7c42686f99bd1b92da2eb129f03c28eaa99fa80f72e3578c4e0f313fbb0c` | `708dcb8b0f0fd734f24940fea1aca2e6195190bfd8573af26510491352c012bc` |

## Concurrency boundary

Mutable global progress and the global R4/model-proposal manifest were not hash-locked. The registry was read only to check ownership. Later appends elsewhere do not alter this frozen batch/checkpoint/sidecar/source snapshot.
