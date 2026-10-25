# Plan 09 R4 first10 — independent semantic audit

Report revision: **1** (initial; supersedes none). Audit date: 2026-10-05. Independent reviewer lane: `gpt-5.6-sol`, reasoning `low`. Producer under audit: `gpt-6.1-sol`, reasoning `low`.

## Verdict

**PASS WITH QUALIFICATION** for exactly the frozen batch `p09-r4-099980-first10-sol-v1`: **10 agree, 0 disagree, 0 insufficient**; 4 positive AUs and 6 hard negatives. Nine items have no finding; item 7 has one low-severity consumption qualification. No canonical correction is required.

This is not semantic gold, not R5 completion, and does not unlock Plan 10. I did not inspect or decide any target outside the batch and did not edit progress, manifests, proposals, sidecars, or other canonical state.

## Independent semantic findings

| # | Target | Verdict | Semantic assessment |
|---:|---|---|---|
| 1 | `at-002724763909ed3cbd562979` | agree / none | Paragraph 107 is current-court analysis. The procedural-rule claim correctly preserves the Commission fraud-investigation context and compelled-testimony/fair-play condition. |
| 2 | `at-04bf386d8c5d925091d491c6` | agree / none | Paragraphs 66–67 narrate the investigation trigger and omitted Policy considerations. The investigator's statutory interpretation starts only in paragraph 68, outside the target. `fact_only` is appropriate. |
| 3 | `at-054dfde5d03691a3ecdf1850` | agree / none | “I find” after the Baker analysis is a current-court holding. The claim and limit stay with the Commission procedure and crucial investigation phase; the next heading is excluded. |
| 4 | `at-057d175123c3feeaa748a894` | agree / none | Paragraph 178 introduces and quotes the Directorate's response. The court's actual disposition is paragraph 179/item 9. The sceptical introduction is not a distinct reusable AU. |
| 5 | `at-05b0930b0c23a8bd764d4430` | agree / none | Paragraph 128 inventories the affidavit and certified record. Credibility findings begin outside the target. `fact_only` is correct. |
| 6 | `at-05ddb4f2a8aa0a4312eef8e3` | agree / none | Paragraph 13 is reference-checking history, not a legal proposition. |
| 7 | `at-0875297b672250b6552a1a4c` | agree / **low** | Paragraph 193 supports considering irreparable harm/public interest; paragraph 190 expressly anchors those factors to costs discretion. The case-specific limit is present. Qualification: the target sentence alone does not mention costs, so the exact paragraph-190 `cross_block_refs` witness is indispensable and must travel with the AU. |
| 8 | `at-09d62c9c1e03e472ef963e5c` | agree / none | Paragraph 73 is expressly the applicant's request/submissions/arguments. No court adoption occurs in the target. |
| 9 | `at-0b86a942dd15b6bbbe7e3baa` | agree / none | Paragraph 179 directly finds a flagrant procedural-fairness breach in this applicant's case. The narrow evidence and limit correctly exclude agency/party speech. |
| 10 | `at-0be8a81021550bf6fad9cdb2` | agree / none | Paragraph 117 describes the practical transfer/advancement consequence of the permission condition. It is in court voice, but current-court voice alone does not make every case-specific factual consequence a reusable AU; `fact_only` is defensible and preferable to inventing a general validity rule. |

## Exact technical checks

- Frozen manifest SHA256: `c8ffdeeccd6d0c0180121255e3d0af414980aded3999a7abae0cccc2cb6fbd82`.
- Raw `data/task1_train_files_2026/cases/099980.txt` computed SHA256 equals declared source hash: `49d56b1477fed32e9c45e52582884818f7632735542b22388911fccd602f2319`.
- All 10 checkpoint files pass `validate_model_proposal`; every exact-span quote, source identity, target checksum, region trace and decision checksum therefore revalidated against the raw source.
- All 10 persisted validation sidecars exactly equal freshly recomputed validation results.
- All producer records are exactly `model:gpt-6.1-sol` / `gpt-6.1-sol` / `low`, with prompt `r4-au-annotation-prompt-v1`.
- Each frozen target has exactly one owner in the current registry read. The implementation rejects a second target owner in both checkpoint and rebuild paths with `checkpoint_duplicate_target`.

Proposal/sidecar SHA256 pairs (position order):

| # | Proposal SHA256 | Sidecar SHA256 |
|---:|---|---|
| 1 | `a6dd6d0aae25fd241f5504009350d73d00d3050c188591e18536bb380a2d3c1b` | `a8d651f4b76b1bf246e53c75c2eb3bb78688d350cf9be25d25801dbd24a731ac` |
| 2 | `89a126d5f8c9f07537fda8fdb754af270f8f8e92a9425cd92fb045b2c13f7bc7` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 3 | `f543d36cb92af6ba2488e893049adb86fa7f4215edca72d0ee8a17e8690931ea` | `a8d651f4b76b1bf246e53c75c2eb3bb78688d350cf9be25d25801dbd24a731ac` |
| 4 | `29cefb3cced479995dacb896df94f76d40da134663a8951c1734157b007ce1f6` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 5 | `184f8d3a075afc33ba7f7d9cd44dfc52ff7c9028aa7f99460928dbc7c449d394` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 6 | `b8940d3f07dea6fd68147657277e7f0b9ea284672c28113bd3d45bf4a42f745a` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 7 | `5b61c302090c40d1ab1dc7b760d42ea3cefff65e2aeedd4c11f5b39dd4101ff0` | `a8d651f4b76b1bf246e53c75c2eb3bb78688d350cf9be25d25801dbd24a731ac` |
| 8 | `2ed593adc4904022013308011cddde1924d5c66f3b63dd15938e040b0dbfbd72` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 9 | `ce04b4bca5f04a09bb49a2791cb6814eebc820e53aae3df34cacd5d598e22387` | `a8d651f4b76b1bf246e53c75c2eb3bb78688d350cf9be25d25801dbd24a731ac` |
| 10 | `f73942b67c258f92901683f4d673ee387cb48c0292f278bbb8fd3c492a9e0c25` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |

## Concurrency boundary

The mutable global progress and R4/model-proposal manifest were deliberately not hash-locked. The registry was read only to check ownership at audit time; another writer appending a different batch does not invalidate this report's frozen-manifest, ten-checkpoint, ten-sidecar and raw-source snapshot.
