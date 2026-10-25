# Plan 09 R4 tenth10 — independent semantic audit

Report revision: **1** (initial; supersedes none). Audit date: 2026-10-06. Independent reviewer: `gpt-6.1-sol` low. Producer: `gpt-6.1-sol` low; independence here means a separate review against frozen inputs and raw source, not a different model family.

## Verdict

**PASS WITH QUALIFICATIONS** for exactly frozen batch `p09-r4-099980-tenth10-sol-v1`: **10 agree, 0 disagree, 0 insufficient**; 8 AUs, 4 hard negatives and 0 unresolved. Items 1, 3, 5 and 10 have low-severity scope qualifications. **No severe findings** and no canonical correction are required.

These records remain model-silver, not human gold. R5=false and Plan 10 remains locked. No target outside tenth10 was audited and no canonical/global artifact was modified.

## Item findings

| # | Target | Verdict | Independent assessment |
|---:|---|---|---|
| 1 | `at-8f8857880ffb9989ff95d485` | agree / **low** | FCA 18.1(3) remedy discretion and Rule 400(3) costs constraints are supported. “Broad” is not unfettered, and no amount is awarded here. |
| 2 | `at-9169a7cb049cf248e5c2ce1a` | agree / none | Comparative allegation/evidence assessment is factual, not a proof standard or innocence holding. |
| 3 | `at-9225bf8f48de08423b2764aa` | agree / **low** | Correctly attributed to the cited Supreme Court and confined to the CHRA filtering scheme; it does not transfer to the PSEA Commission. |
| 4 | `at-950ed802967a5dd1e6352b4e` | agree / none | The three alternative PSEA grounds, statutory sections and Commission-satisfaction condition are exact. |
| 5 | `at-95364ee9fae807cd82176477` | agree / **low** | Greater procedural protection is supported in the section 69 fraud/individual-impact context, but does not prescribe one universal procedure. |
| 6 | `at-98814cc80cdfb175986f0de4` | agree / none | Three disjoint AUs correctly separate relief/fairness, costs and finality. Relief is applicant-limited; $650 is conditional on non-payment; finality waits for expiry of appeal rights. |
| 7 | `at-9a77548a0ed859334746f9be` | agree / none | Investigator fraud/credibility findings and job facts are not current-court adjudication or a general fraud test. |
| 8 | `at-9b01d3f90b10e934c376245e` | agree / none | A dictionary definition reported from the investigator's report is not a standalone court legal definition in this target. |
| 9 | `at-9c36ec4f176e3085aed6e9c8` | agree / none | Reference-checking and e-mail history are facts, not a legal rule or fraud holding. |
| 10 | `at-9d5ed1c1ad745b3679a3f919` | agree / **low** | Sections 66-68 remedies are supported. The claim cannot be extended to the expressly unresolved section 69 third-party corrective-power question. |

## Formal judgment check

The target at position 6 contains three AUs with pairwise non-overlapping evidence spans: points 1-4 `[121494,122024)`, point 5 `[122026,122262)`, and point 6 `[122264,122343)`. The gaps exclude separators, and the final span excludes `Application allowed` and editor credit. Each claim preserves the operative condition in its own source segment.

## Technical checks and snapshot

- Frozen batch SHA256: `a785569cd9e3a792937e1bcddd8e71f5545499d046276c9cefab323265bc5da4`.
- Raw source computed/declared SHA256: `49d56b1477fed32e9c45e52582884818f7632735542b22388911fccd602f2319`.
- All ten proposals pass `validate_model_proposal`; exact source, spans/quotes, region identity and trace checksums revalidated.
- All ten sidecars exactly equal recomputed validation results.
- All producers are exactly `model:gpt-6.1-sol` / `gpt-6.1-sol` / `low`, prompt `r4-au-annotation-prompt-v1`.
- Current registry read found one owner per target; duplicate guards remain active.

| # | Proposal SHA256 | Sidecar SHA256 |
|---:|---|---|
| 1 | `ffa3dc0626ee55bee82e2561b01ee70e7e380de23fd7e28b7c7d636717172f89` | `a8d651f4b76b1bf246e53c75c2eb3bb78688d350cf9be25d25801dbd24a731ac` |
| 2 | `6aa28a3dc68615b14fc10d6f366b59e5d649969fd6af6e156801956fde66feed` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 3 | `09e2ffdc7ce407990d9c7d3dff9b4ab2fa4b4f5d67575abc7094a7695f6ec359` | `a8d651f4b76b1bf246e53c75c2eb3bb78688d350cf9be25d25801dbd24a731ac` |
| 4 | `cf87d77932fa4177b77735291c08bc06a57b9f6122d797121c20eb4f0a864776` | `a8d651f4b76b1bf246e53c75c2eb3bb78688d350cf9be25d25801dbd24a731ac` |
| 5 | `240c120b0e968e60d8fe6074b4d64b216ead03d546df6cf03e5d1f47ed9f6baf` | `a8d651f4b76b1bf246e53c75c2eb3bb78688d350cf9be25d25801dbd24a731ac` |
| 6 | `a55625f6c0172f0bb5e6ba758786b6475dc6579be7c89a562b77409f5a447411` | `903964f2b8a6da32dd144614d70a94ae236f63c0c83ee9a5d9b8e9617b78be38` |
| 7 | `200eb98c44f17ee533e99f585d1add51b1d2a7c12b48a75f0b10e82b3d1481f0` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 8 | `4eda96fd98c0627040073f05c261ef65ab373786e9ce2936524a149471a05f4b` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 9 | `21bca99cec01cd9500c1deabb503c10cb1884bc377e17da29d4d1dd4f4cd892d` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 10 | `7f903460dfc4a7aa48edd20a328979a8271d74c805d7967127a8566195413e08` | `a8d651f4b76b1bf246e53c75c2eb3bb78688d350cf9be25d25801dbd24a731ac` |

## Concurrency boundary

Mutable global progress and global R4/model-proposal manifest were not hash-locked. Registry access was limited to ownership verification. Later appends elsewhere do not alter this frozen snapshot.
