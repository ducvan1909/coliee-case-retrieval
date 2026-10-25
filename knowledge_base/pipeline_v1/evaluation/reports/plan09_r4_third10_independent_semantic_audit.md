# Plan 09 R4 third10 — independent semantic audit

Report revision: **1** (initial; supersedes none). Audit date: 2026-10-06. Independent reviewer: `gpt-5.6-sol` low. Producer: `gpt-6.1-sol` low.

## Verdict

**PASS WITH QUALIFICATIONS** for exactly frozen batch `p09-r4-099980-third10-sol-v1`: **10 agree, 0 disagree, 0 insufficient**; 4 AUs, 5 hard negatives and 1 unresolved. Items 2, 6 and 10 have low-severity qualifications. No canonical correction is required.

This audit is not semantic gold, does not complete R5, and does not unlock Plan 10. No target outside the batch was audited, and no canonical artifact was modified.

## Item findings

| # | Target | Verdict | Independent assessment |
|---:|---|---|---|
| 1 | `at-1f8713f545365df1f151daa4` | agree / none | Paragraph 200 is a non-operative closing request for institutional reflection. The formal judgment has another owner. `editorial` is correct. |
| 2 | `at-23e0d9d111911c28fba85628` | agree / **low** | Paragraph 173 supports the final-report draft/comment rule for directly affected people. The final-report condition and before-approval limit are correct. Qualification: paragraph 174 confirmation is indispensable because primary evidence is phrased as a rhetorical question; it is recorded exactly. |
| 3 | `at-246ff349485b66f67fe5c39d` | agree / none | Paragraph 182 is remedy-transition rhetoric, not the operative remedy or a standalone test. |
| 4 | `at-25a47b63b5767f7bc735f6be` | agree / none | Paragraph 150 expressly finds the dated notice insufficient because it omitted that this applicant was suspected of fraud. Scope and attribution are exact. |
| 5 | `at-27935875158c3bd52e6220aa` | agree / none | Paragraph 141 quotes the investigator's factual scope. It is not adopted court law or a court fraud finding. |
| 6 | `at-27d52ebdf0fe44b1ec832078` | agree / **low** | Nested cited-court confirmation is followed by an expressly identified investigator argument. `citation_without_proposition` is plausible, but suppressed citation and speaker/adoption ambiguity justify conservative `unresolved`. |
| 7 | `at-2830ad7af31dc36e2dfd45a2` | agree / none | The first sentence of paragraph 87 is a court paraphrase of the five-year statutory review hook. Review Team policy recommendations are correctly excluded. |
| 8 | `at-298921465b894cd1e165f1c2` | agree / none | Paragraph 66 is case-record appraisal of a cursory jurisdiction review and omitted Policy, not a final jurisdiction rule. |
| 9 | `at-2ad9077730065065ecf5523f` | agree / none | Paragraph 68 expressly quotes the investigator's jurisdiction response; later court reasoning does not convert this target to current-court speech. |
| 10 | `at-2be613d920e6ea831c8e3022` | agree / **low** | Paragraph 191 supports the narrow current-court holding. Qualification: it is limited to this impugned decision and cannot become a universal retroactivity bar or validation of the permission condition. |

## Technical checks and snapshot

- Frozen batch SHA256: `c292811c09e0f356b988ddf587892100f4a4f60f2b2aa2d061c40aad0b736d03`.
- Raw source computed/declared SHA256: `49d56b1477fed32e9c45e52582884818f7632735542b22388911fccd602f2319`.
- All ten checkpoints pass `validate_model_proposal`; source identity, exact half-open spans/quotes, region identity and review-trace checksums revalidated.
- All ten sidecars exactly equal newly recomputed validation results.
- All producer records are exactly `model:gpt-6.1-sol` / `gpt-6.1-sol` / `low`, prompt `r4-au-annotation-prompt-v1`.
- Current registry read found one owner per frozen target. Checkpoint and rebuild paths reject duplicate target ownership with `checkpoint_duplicate_target`.

| # | Proposal SHA256 | Sidecar SHA256 |
|---:|---|---|
| 1 | `5ce2ee6ea0ea81791527b73bf4666aaaf8c5e39a65a18a48a85247528bc24dbc` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 2 | `e4cd82ea6c7b8293f6bfc471667dde7d951d87e7b9da76ed3f38ae65de43b1da` | `a8d651f4b76b1bf246e53c75c2eb3bb78688d350cf9be25d25801dbd24a731ac` |
| 3 | `4d1dfce1dc24d6a6ba48d95e2c06ba5ac2491404d3da4062ceeb1c484d890864` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 4 | `eb41a9434ff49fb0a62f588e767f965323f50dacbb09afef687caad30f5a1fd2` | `a8d651f4b76b1bf246e53c75c2eb3bb78688d350cf9be25d25801dbd24a731ac` |
| 5 | `6740e9b801291c4968d7279f6f69e9b4c2d347796749285c47a900962d5be443` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 6 | `c1be1756d50baf449de9c47c33408bc6a2b4e0173baec3c01acdcdf48a767472` | `708dcb8b0f0fd734f24940fea1aca2e6195190bfd8573af26510491352c012bc` |
| 7 | `d45448fdd468183888e2c72e545811048433d6e5c1d1930f902e49191ee1c5f4` | `a8d651f4b76b1bf246e53c75c2eb3bb78688d350cf9be25d25801dbd24a731ac` |
| 8 | `95807f4255bf5979052bc6d0382b27d346be8cc6a7e9ff8fe221369f3e25d5fb` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 9 | `d4de44bd2521a0b0ee1c2110cba1c463c557654a96acb8c53770991c5f0420a3` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 10 | `88038dd7dd15fb9b83714a1d6b9b53025e9dd941b3d9e4cc3840c711a9a87bcb` | `a8d651f4b76b1bf246e53c75c2eb3bb78688d350cf9be25d25801dbd24a731ac` |

## Concurrency boundary

Mutable global progress and the global R4/model-proposal manifest were deliberately not hash-locked. The registry was read only for ownership. Appends to other batches do not alter this frozen batch/checkpoint/sidecar/source audit snapshot.
