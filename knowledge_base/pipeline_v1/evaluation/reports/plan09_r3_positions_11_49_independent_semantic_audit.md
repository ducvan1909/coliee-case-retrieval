# Plan 09 R3 independent semantic audit: positions 11–49

Date: 2026-10-05  
Scope: exactly attribution-risk queue positions 11–49. Positions 1–10 were not re-audited. All conclusions remain model-only/model-silver.

## Verdict

**R3 semantic audit: FAIL pending two mandatory revisions.**

- Agree: **37/39**.
- Disagree: **2/39** — positions 11 and 32.
- Insufficient evidence: **0/39**.
- Current contract/encoding/harness failures: **0**.
- P09-S01 remains open. It has a source-grounded final correction available and should not remain `unresolved`.

No canonical queue, registry, review, amendment, proposal, or progress artifact was modified.

## Snapshot lock

- Queue SHA-256: `b693b883fdf4ad7966b882282d5c0e5194562689315b63bc911e0270f1e653a5`.
- 39 review-head manifest SHA-256: `a239ee8065a9491237072dacae37e527b53f2f4afc7ad2922de79d70f6523431`.
- 33 relevant amendment-head manifest SHA-256: `8ba8419ca0bd8f36bebac8834c23b68a77da8c4fa4cef1018d1e5678bfe777aa`.
- Five raw-source manifest SHA-256: `fcf90217f0b2376d2504dfd3400d1aad87d0f15489db82245611677de5280a49`.
- Raw source hashes: `011904=c2bc7c...96b12`, `013009=fb6707...f7a3`, `013948=157187...4352`, `045155=93d2b9...d6eb`, `099980=49d56b...319`.

The same hashes were recomputed after report creation and remained unchanged.

## Mandatory revisions

### Position 11 — wrong AU kind (moderate)

- Target: `011904 / at-a5b5b0fdf3bab9574aa4429e`.
- Evidence: raw `[14358,14826)`.
- Effective claim: state-protection analysis must assess whether protection is effective.
- Assessment: attribution and proposition are supported, but this is a general analytical requirement, not the case disposition itself. `holding` is misleading; use `procedural_rule`. Preserve `current_court` and exact evidence. The neighboring paragraphs can remain context showing application.

### Position 32 — P09-S01 remains incorrectly unresolved (severe)

- Target: `013948 / at-3f8c7b00587a03395a1070fa`.
- Current effective outcome: label-free `unresolved`.
- Party-submission portion: raw `[11460,11888)`; it must not become a court proposition.
- Independent court heading: `The Board never ruled on Mr. Bayavuge's risks of return`, exact raw `[11890,11945)`.
- Supporting current-court analysis: paragraphs 35–39, beginning at `[11953,...)`, explains that the Board did not decide personalized section-97 return risk.
- Requested correction: create a final positive `holding/current_court` AU scoped to “The Board never ruled on Mr. Bayavuge's risks of return”, use only `[11890,11945)` as primary evidence, and attach exact paragraph 35–39 cross-block/context witnesses. Do not include paragraph 34's party submission in proposition evidence.

The target itself contains a complete court-authored heading, and neighboring reasons resolve its meaning. Therefore there is enough evidence for a final non-unresolved correction. This audit does not itself write the amendment or close P09-S01.

## Per-item audit

| Pos. | Target | Result | Severity | Evidence | Assessment |
|---:|---|---|---|---|---|
| 11 | `at-a5b5b0fdf3bab9574aa4429e` | disagree | moderate | `011904[14358,14826)` | Change `holding` to `procedural_rule`; speaker and claim otherwise supported. |
| 12 | `at-08bf65c4ca25403730d5353c` | agree | none | `013009[1211,2383)` | Narrow court witness avoids quoted officer voice. |
| 13 | `at-fad288640dd0c7aa6b551320` | agree | none | `013009[4222,4868)` | Explicit current-court unreasonableness finding. |
| 14 | `at-5522df4fca96eee9c7176c4c` | agree | none | `013009[12230,12405)` | Case-specific error and disposition correctly scoped as holding. |
| 15 | `at-6fd1350b5e4ed36850040c15` | agree | none | `013009[1041,1204)` | Application-specific H&C disposition. |
| 16 | `at-79ddc136c68ac1dccc949df4` | agree | none | `013009[7970,8693)` | Withdrawn/dismissed-charge scope, cited/current court voices and limit preserved. |
| 17 | `at-81ed7da8dd8cb3dab2bdd33e` | agree | none | `013009[10553,11266)` | Qualified applicant-specific holding preserved. |
| 18 | `at-d1a9498ecd408d28317aa793` | agree | none | `013009[11274,12222)` | Current-court inference separated from nested citation. |
| 19 | `at-f4a073144323210976dace57` | agree | none | `013009[8700,10545)` | Procedural-fairness boundary and quoted authority separated correctly. |
| 20 | `at-085b9017aac39b55a1c66d99` | agree | none | `013948[4130,4509)` | Section-163 condition and decision-time limit retained. |
| 21 | `at-9647c642f34e461afed2bcd3` | agree | none | `013948[4940,5301)` | Statutory quote isolated with legislature attribution. |
| 22 | `at-4f47ee824d830713909b5207` | agree | none | `013948[18176,18394)` | Explicit case-specific approval of officer decision. |
| 23 | `at-18bd69bd7657d6f7040f6e4a` | agree | none | `013948[12482,12755)` | Board-decision interpretation correctly treated as holding. |
| 24 | `at-19cb3b2ba4ac3c000e7e80ea` | agree | none | `013948[13032,13231)` | Current-court reading of exclusion/inclusion issue. |
| 25 | `at-1bdec346bae3fbd73ee645b0` | agree | none | `013948[13239,13778)` | Officer quotation excluded; section-97 distinction and limit retained. |
| 26 | `at-55d68209bf19c9c985db1b0f` | agree | none | `013948[12763,13024)` | Applicant-specific holding with qualification. |
| 27 | `at-eae6586b56aa73cb4d5ca550` | agree | none | `013948[333,790)` | Section-1F condition and Convention-refugee limit preserved. |
| 28 | `at-12a803f163fabfad29b3f956` | agree | none | `013948[16991,17349)` | Case-specific evidentiary holding and because-condition supported. |
| 29 | `at-363f52092d33564069b394ee` | agree | none | `013948[17898,18168)` | No-evidence condition correctly attached to rejection holding. |
| 30 | `at-4adb5e627730e8e054bee5a7` | agree | none | `013948[17747,17890)` | Applicant-specific no-speculation holding. |
| 31 | `at-726483a83077ee92addf3aff` | agree | none | `013948[8689,9915)` | Court procedure and quoted administrative-manual voice separated. |
| 32 | `at-3f8c7b00587a03395a1070fa` | disagree | severe | `013948[11460,11945)` | Final narrow court-heading holding is supportable; do not retain unresolved. |
| 33 | `at-286fc0f30a53d4bce2eeb5c3` | agree | none | `013948[6222,6633)` | Issue question removed; affirmative record rule retained. |
| 34 | `at-329c7590de0a0f2cb690f50c` | agree | none | `013948[5545,5850)` | Officer-decision history correctly changed to hard negative. |
| 35 | `at-3afd82f9ffea744294fd4624` | agree | none | `013948[13786,14019)` | Heading excluded; no-inclusion condition retained. |
| 36 | `at-7544c78cf589f672a909022b` | agree | none | `013948[14027,14265)` | Evidentiary obligation correctly classified procedural rule. |
| 37 | `at-4b45893be1af385679d8c79a` | agree | none | `013948[16135,16327)` | Conditional applicant-specific onus finding. |
| 38 | `at-a323323de17b57ed9f104642` | agree | none | `013948[16335,16563)` | Case-specific no-search holding supported. |
| 39 | `at-ba8ab2cc049d5dbf250b0516` | agree | none | `013948[15791,16127)` | Non-submission condition and file qualification explicit. |
| 40 | `at-3d0be6036210c5ff292aecc6` | agree | none | `013948[10625,10960)` | Written-assessment disposition and negative-risk condition supported. |
| 41 | `at-ec01061e01622d86bb3107a2` | agree | none | `013948[10243,10617)` | Negative-risk premise correctly attached to case holding. |
| 42 | `at-d1425cdc57fccc22bca63b22` | agree | none | `013948[1319,1560)` | Fault attribution remains applicant-specific and conditioned on missing evidence. |
| 43 | `at-4745273a6ff2708807d277d2` | agree | none | `013948[6874,7216)` | Subsection-112 condition and subsection-172 exception captured. |
| 44 | `at-d92f9fa84ec2df3db74965a2` | agree | none | `013948[6641,6866)` | Court criticism separated from applicant submission. |
| 45 | `at-06c77e704242747ebd7f5f94` | agree | none | `013948[15435,15783)` | Court onus sentence separated from officer quote. |
| 46 | `at-2d5dc405fcc3b68543fb36f8` | agree | none | `013948[15228,15427)` | Prior-claim-evidence holding scoped by non-submission. |
| 47 | `at-3820d6c51502d2177b73a081` | agree | none | `013948[14926,15220)` | Burden failure and non-submitted-evidence limit preserved. |
| 48 | `at-531abd531d3559d2b6f298ca` | agree | none | `045155[24057,24549)` | Regulation isolated with legislature attribution and time/denial conditions. |
| 49 | `at-dc762fc78fb3970f9e23f864` | agree | none | `099980[93242,93858)` | Interview-specific disclosure rule, condition and relevance limit are explicit. |

## Validation and boundaries

- 39/39 effective risk-review heads validate.
- 33/33 relevant amendment heads validate.
- Revision lineage reports one head per identity; no fork, overwrite, or cycle was detected.
- Read-only revision-history/risk-review/batch tests: **11/11 PASS** in 124.382 s.
- There were no current UTF-8/code-point defects. The withdrawn item-06 harness issue from the earlier first-10 audit was not counted as a semantic or contract failure here.

R3 cannot pass until positions 11 and 32 receive new immutable revisions and are independently rechecked. Plan 10 remains locked.

