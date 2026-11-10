# Independent Review Report — M2 Navigation (`m2_navigation_20261105_v1`)

- **Reviewer:** Antigravity (Independent Review)
- **Date:** 2026-11-06
- **Repo Root:** `E:/Git/coliee-case-retrieval`
- **Target Bundle:** `pipeline_v2/artifacts/m2_navigation_20261105_v1`
- **Bundle Seal SHA-256:** `e237cf60760c38fa430f332e1085784d464587324b47c7b7dd4266304b97c7ee`
- **Upstream Bundles Cross-Verified:** `pipeline_v2/artifacts/m0_20261105_v2` & `pipeline_v2/artifacts/m1_20261105_v2`
- **Overall Conclusion:** **`fixes_required_before_next_stage`**

---

## 1. Executive Summary & Overall Verdict

We conducted an independent end-to-end audit of `pipeline_v2/artifacts/m2_navigation_20261105_v1` following `pipeline_v2/docs/AG_REVIEW_M2_NAVIGATION_PROMPT.md` across all `7,708` raw train cases (`431,333` M1 structural units, `382,343` navigable content units, `481,926` previews, `216,946` unit anchors, and `1,237` full source anchors), supplemented by 8 adversarial tamper/runtime boundary tests and a locked manual/semi-manual adjudication of `144` regions across `48` cases (`20` uniform random, `20` risk-stratified across 5 risk groups, and `8` regression exposed cases, strictly excluding the `10` discovery and `10` holdout cases from `m0_20261105_v2/cohort.json`).

### Two-Part Assessment
1. **Protocol, Provenance, Mapping, Coverage, and Runtime Boundary Contract (`100% PASS`, 0 defects):**
   - Every single case (`7,708 / 7,708`), byte span, SHA-256 digest, M0/M1 cross-stage seal, `p/u` handle sequence, `paragraph_order` / `content_unit_order` neighbor chain (`698,530` paragraph links + `46,017` unnumbered links), multi-hit parent deduplication, heading attachment (`48,990` headings), and deferred token readiness flag (`token_count: null`, `not_ready`) satisfies the M2 contract with zero drift or hallucination.
2. **Preview & Context Selection Usability (`fixes_required_before_next_stage` — 3 confirmed deterministic defects in `pipeline_v2/navigation/core.py`):**
   - **`M2-FINDING-001` (High):** Naive sentence-boundary punctuation regex (`r"[.!?](?=\s|$)"` in `core.py` line 35) clips **`85,518 / 382,286` (`22.37%`)** of all `opening` previews mid-sentence at judicial titles (`Pinard, J.`, `Mandamin, J.`, `O'Keefe, J.`), honorifics/initials (`Mr.`, `Ms.`, `Dr.`, `Charlotte M.`, `John H.`, `1.`), reporter citations (`F.C.`, `R.S.C.`), or statutory abbreviations (`s.`), producing `34,974` (`9.15%`) previews of `<= 30` chars despite substantive text continuing in the unit—and line 128 falsely marks **`100%` (`85,518 / 85,518`)** of them as `partial_sentence: false`.
   - **`M2-FINDING-002` (High):** Anchor window calculation (`left = max(start, a - radius)` in `core.py` line 104) pulls in the leading `[N]\r\n` paragraph marker before `opening[0]`, triggering line 110's merge block (`lo < opening[0]`) and one-way containment check (line 113). This causes **`56,996` units** (`57.20%` of all anchor previews) to emit overlapping `opening` + `anchor` previews (`31,352` blocked solely because `left < opening[0]`), and in **`11,505` units** wastes the second display slot (`max_display = 2`) on a duplicate substring while **crowding out a deeper citation/quote anchor** later in the same paragraph.
   - **`M2-FINDING-003` (Medium):** The leading placeholder-only line filter (`PLACEHOLDER.sub("", value).strip()` in `core.py` line 27) fails whenever a line contains stray punctuation alongside placeholders (e.g., `<FRAGMENT_SUPPRESSED> )  <FRAGMENT_SUPPRESSED>`), affecting **`932` content units** where `_opening()` starts on a suppressed placeholder line instead of advancing to the first alphanumeric line.

Because fixes to `M2-FINDING-001`, `M2-FINDING-002`, and `M2-FINDING-003` are localized to `_opening()` and `_unit_previews()` in `pipeline_v2/navigation/core.py` (without changing M1 or M2's storage/runtime architecture) and directly govern what the agent sees in `map()` before spending its `open()` budget, **these 3 defects should be fixed and the M2 bundle regenerated before proceeding to the next stage.**

---

## 2. Section A — Independent Machine Audit Across Full Corpus (`7,708` Cases)

All 8 machine audit categories required by Section A of `AG_REVIEW_M2_NAVIGATION_PROMPT.md` were executed independently via:
- `pipeline_v2/reviews/m2_navigation_ag_review_v1/scripts/independent_corpus_audit.py` -> `machine_audit_results.json`
- `pipeline_v2/reviews/m2_navigation_ag_review_v1/scripts/tamper_and_runtime_boundary_tests.py` -> `tamper_and_boundary_results.json`

### A.1 Universe, Provenance & Seal Checks
| Check | Scope / Denominator | Result | Evidence |
|---|---:|---|---|
| Case count across M0, M1, M2, raw `cases/`, M2 sidecars | `7,708` cases | **PASS (`0` mismatches)** | `m0_case_count = m1_case_count = m2_case_count = m2_sidecar_count = 7,708` |
| `case_id` + `source_hash` identity across M0/M1/M2 & raw bytes | `7,708` cases | **PASS (`0` mismatches)** | All `7,708` raw files hashed via SHA-256 match M0, M1, and M2 |
| `m1_bundle_ref` & `m1_seal_sha256` match `m1_20261105_v2` | `1` bundle seal | **PASS** | `91ff35a3335a4dc8eb2e0fe5219d26fd4610018a5ef8db0bc20f7c7da6db05e5` |
| `profile_hash` & `code_hash` match `configs/m2.json` & `pipeline_v2/{m2.py,navigation/*.py}` | `1` profile + `4` code files | **PASS** | `profile_hash = 6fb6269a0dcbb72fd2e45ec6ac12095f95f97e29a6f4700bb095857689e33417`, `code_hash = dd2dfef77f8e93d6896be15426630597c6066a979144517ca003084342be9761` |
| Every file in `seal.json` (`7,720` artifacts) matches SHA-256 & byte size | `7,720` files | **PASS (`0` mismatches)** | `bundle_sha256 = e237cf60760c38fa430f332e1085784d464587324b47c7b7dd4266304b97c7ee` |
| Tamper & reseal tests (corrupt sidecar, reseal tampered sidecar, raw byte drift, profile drift, M1 seal drift) | `5` adversarial fixture tests | **PASS (`5/5` rejected with `M2Error`)** | `tamper_and_boundary_results.json` Tests 1–5 & 7 |

### A.2 Structural Coverage & Handle Mapping
| Check | Scope / Denominator | Result | Evidence |
|---|---:|---|---|
| M1 `paragraph` + `unnumbered` units mapped 1-to-1 to M2 `navigation_units` | `382,343` content units (`356,973` `p` + `25,370` `u`) | **PASS (`0` missing, `0` extra)** | `m1_content_units_total = 382,343`, `m2_navigation_units_total = 382,343` |
| `unknown` paragraphs & `fr:*` French units preserved without drop | `355,736` `unknown` `p`, `13,189` `fr:*` units | **PASS (`100%` preserved)** | `paragraph_role_counts = {"unknown": 355736, "quoted": 1237, "null": 25370}` |
| `handle` (`p000001` / `u000002`) unique per case & monotonically increasing in `source_order` | `382,343` units across `7,708` cases | **PASS (`0` violations)** | `nav_ordinal` strictly `1..N` per case in `source_order` |
| `heading` units excluded from `p/u` handles and matched in `section_headings` | `48,990` headings | **PASS (`0` violations)** | All `48,990` headings verified against raw byte slices and SHA-256 |
| `parent_unit_id`, `span_bytes`, `span_chars`, `source_order`, `observed_marker`, `paragraph_role`, `language_region`, `uncertainties` match M1 & raw bytes | `382,343` units | **PASS (`0` mismatches)** | Verified across all `7,708` cases |

### A.3 Neighbor & Reading-Context Contract
| Check | Scope / Denominator | Result | Evidence |
|---|---:|---|---|
| Paragraph units use `neighbor_policy = paragraph_order` | `356,973` paragraphs | **PASS (`100%`)** | `paragraph_neighbor_links_checked = 698,530` |
| Unnumbered units use `neighbor_policy = content_unit_order` | `25,370` unnumbered units | **PASS (`100%`)** | `content_unit_neighbor_links_checked = 46,017` |
| Repeated / non-monotonic `observed_marker` values follow `source_order`, never arithmetic `marker +/- 1` | `33,955` repeated markers + `9,865` non-sequential transitions | **PASS (`0` marker-arithmetic errors)** | Verified across full corpus and `tamper_and_boundary_results.json` Test 7 (`[1], [5], [5], [3]`) |
| `previous_absence_reason` / `next_absence_reason` at boundaries | `382,343` units | **PASS (`0` invalid reasons)** | `source_boundary` or `no_paragraph_neighbor_in_direction` only |
| Runtime `open()` modes (`parent`, `parent_plus_previous`, `parent_plus_next`, `neighbors`) & intervening headings | Full corpus + boundary fixture | **PASS (`0` inversions)** | All components strictly ordered by `span_bytes`; `M4_delivery_recorded = false`, `diagnostic_only = true` |

### A.4 Preview Contract & Usability Diagnostics
| Metric | Count / Denominator | Rate | Contract vs Usability Status |
|---|---:|---:|---|
| Total previews audited (`opening` + `anchor`) | `481,926` (`382,286` opening + `99,640` anchor) | `100.00%` | **Contract PASS** (`0` byte/hash/240-char violations) |
| Units with `1..2` previews | `382,288 / 382,343` | `99.986%` | **Contract PASS** |
| Units with `0` previews (`preview_absence_reason = no_meaningful_opening_or_anchor`) | `55 / 382,343` | `0.014%` | **Contract PASS** (`55/55` are marker-only paragraphs like `[2]`) |
| Opening previews clipped at title/initial/citation/statute abbreviation & marked `partial_sentence = false` | `85,518 / 382,286` | **`22.37%`** | **Usability Defect (`M2-FINDING-001`)** |
| Opening previews `<= 30` chars despite unit having more substantive text | `34,974 / 382,286` | **`9.15%`** | **Usability Defect (`M2-FINDING-001`)** |
| Opening previews `<= 15` chars despite unit having more substantive text | `21,242 / 382,286` | **`5.56%`** | **Usability Defect (`M2-FINDING-001`)** |
| Units where `opening` and `anchor` previews overlap in byte span | `56,996 / 99,640` | **`57.20%`** | **Usability Defect (`M2-FINDING-002`)** |
| Units where `anchor` merge with `opening` was blocked solely because `left < opening[0]` | `31,352 / 56,996` | **`55.01%` of overlaps** | **Usability Defect (`M2-FINDING-002`)** |
| Units where unmerged duplicate `opening`+`anchor` preview **crowded out a deeper anchor** (`anchor_count > visible_anchor_count`) | `11,505` units | **`11.55%` of anchor previews** | **Usability Defect (`M2-FINDING-002`)** |
| Content units where `_opening()` failed to skip a leading placeholder+punctuation-only line | `932 / 382,343` | **`0.24%`** | **Usability Defect (`M2-FINDING-003`)** |

### A.5 Anchor & Partial-Cue Honesty
| Check | Scope / Denominator | Result | Evidence |
|---|---:|---|---|
| Unit-level `anchors` (`placeholder` + `quote_introduction_candidate`) | `216,946` (`215,688` placeholders + `1,258` quote-cue fragments) | **PASS (`0` byte/hash mismatches)** | Verified against raw bytes and M1 sidecars |
| Case-level `source_anchors` (`q000001`, ...) | `1,237` (`1,201` single-unit, `36` multi-unit, `21` multi-content-unit, `0` heading-only) | **PASS (`0` silent drops or clippings)** | Every multi-unit cue preserved in full in `source_anchors` with `original_cue_span_bytes` on each unit fragment |
| Anchor visibility metadata (`full` vs `partial`, `fully_visible`, `source_cue_fully_visible`) | `238,539` visibility records (`233,883` full, `4,656` partial; `1,164` partial source cues) | **PASS (`100%` honest)** | Every clipped anchor/cue is explicitly marked `visibility = "partial"` |

### A.6 Multi-Hit Parent Dedup Contract
- Tested via `M2NavigationStore.dedup_hits()` in `tamper_and_boundary_results.json` Test 8: when two synthetic hits (`hit_alpha` on `p000001:v01` and `hit_beta` on `p000002:v01`) map to the same parent unit `p000001`, `dedup_hits()` returns **1** deduplicated parent record in deterministic first-seen order while preserving `hit_refs: ["hit_alpha", "hit_beta"]` and `preview_refs: ["p000001:v01", "p000002:v01"]`.

### A.7 Deferred Token / Readiness Honesty
- Across all `382,343` navigation units, `token_count` is `null` (`0` non-null values).
- In `manifest.json` and `validation_report.json`:
  - `embedding_tokenizer_id = null`, `agent_tokenizer_id = null`
  - `token_validated_RETRIEVAL_UNIT_spec = "not_ready"`
  - `dense_retrieval_index = "not_ready"`
  - `agent_payload_token_budget = "not_ready"`

---

## 3. Section B — Locked Manual / Semi-Manual Review (`144` Regions Across `48` Cases)

### B.1 Locked Sampling Protocol
- **Seed:** `20261105` (`pipeline_v2/reviews/m2_navigation_ag_review_v1/sampling_manifest.json`)
- **Exclusions Enforced:** All `10` `discovery` cases and `10` `holdout` cases from `pipeline_v2/artifacts/m0_20261105_v2/cohort.json` were strictly excluded from the `uniform_random_20` and `risk_stratified_20` pools (`overlap = 0`). The `8` `regression_exposed` cases from `m0_20261105_v2/cohort.json` were isolated in their own separate diagnostic group (`regression_exposed_8`) and excluded from the `20 + 20` main sample.
- **Sample Composition (`48` cases, `144` regions total — 3 regions per case: `[opening, anchor_or_partial_cue, parent_neighbor_window]`):**
  1. **`uniform_random_20` (`20` cases, `60` regions):** `009914.txt`, `011922.txt`, `012194.txt`, `014101.txt`, `016412.txt`, `016851.txt`, `021549.txt`, `031099.txt`, `041335.txt`, `045473.txt`, `064802.txt`, `068193.txt`, `071570.txt`, `072716.txt`, `073230.txt`, `074285.txt`, `080359.txt`, `081945.txt`, `085311.txt`, `087842.txt`.
  2. **`risk_stratified_20` (`20` cases, `60` regions across 5 risk subgroups, 4 cases / 12 regions each):**
     - `risk_1_repeated_or_non_monotonic_markers`: `076711.txt`, `071688.txt`, `025614.txt`, `001106.txt`
     - `risk_2_long_cross_unit_or_heading_cues`: `048208.txt`, `075799.txt`, `027187.txt`, `015740.txt`
     - `risk_3_very_short_abbrev_or_placeholder_previews`: `000841.txt`, `079842.txt`, `001867.txt`, `051807.txt`
     - `risk_4_high_unnumbered_ratio`: `027775.txt`, `010665.txt`, `019027.txt`, `022215.txt`
     - `risk_5_french_or_mixed_language`: `081611.txt`, `009771.txt`, `059171.txt`, `097824.txt`
  3. **`regression_exposed_8` (`8` cases, `24` regions):** `007314.txt`, `023047.txt`, `032656.txt`, `038025.txt`, `051846.txt`, `077416.txt`, `079438.txt`, `095857.txt`.

### B.2 Adjudication Summary by Sample Group (Reported Separately)

| Metric / Dimension | `uniform_random_20` (`60` regions) | `risk_stratified_20` (`60` regions) | `regression_exposed_8` (`24` regions) | Total (`144` regions) |
|---|---:|---:|---:|---:|
| **1. Handle & Span Accuracy (`PASS`)** | `60 / 60` (`100.0%`) | `60 / 60` (`100.0%`) | `24 / 24` (`100.0%`) | `144 / 144` (`100.0%`) |
| **2. Preview Usefulness:** `PASS` | `31 / 60` (`51.7%`) | `28 / 60` (`46.7%`) | `13 / 24` (`54.2%`) | `72 / 144` (`50.0%`) |
| **2. Preview Usefulness:** `WARN` (usable but noisy/redundant) | `16 / 60` (`26.7%`) | `13 / 60` (`21.7%`) | `5 / 24` (`20.8%`) | `34 / 144` (`23.6%`) |
| **2. Preview Usefulness:** `FAIL` (clipped at title/abbrev or crowded out deeper anchor) | `13 / 60` (`21.7%`) | `19 / 60` (`31.7%`) | `6 / 24` (`25.0%`) | `38 / 144` (`26.4%`) |
| **3. Anchor Visibility Honesty (`PASS`)** | `60 / 60` (`100.0%`) | `60 / 60` (`100.0%`) | `24 / 24` (`100.0%`) | `144 / 144` (`100.0%`) |
| **4. Reading-Context Coherence (`PASS`)** | `60 / 60` (`100.0%`) | `60 / 60` (`100.0%`) | `24 / 24` (`100.0%`) | `144 / 144` (`100.0%`) |
| **5. Role / Language Conservatism (`PASS`)** | `60 / 60` (`100.0%`) | `60 / 60` (`100.0%`) | `24 / 24` (`100.0%`) | `144 / 144` (`100.0%`) |

#### Breakdown of `risk_stratified_20` by Risk Subgroup (`12` regions each)
- **`risk_1_repeated_or_non_monotonic_markers` (`076711.txt`, `071688.txt`, `025614.txt`, `001106.txt`):** `12/12` handle/neighbor/context PASS; Preview usefulness: `4 PASS`, `4 WARN`, `4 FAIL` (e.g., `076711.txt` `p000010` `[1]\r\nRussell, J.` clipped to `"Russell, J."`, and `p000038` where duplicate opening+anchor preview crowded out `p000038:a0002`).
- **`risk_2_long_cross_unit_or_heading_cues` (`048208.txt`, `075799.txt`, `027187.txt`, `015740.txt`):** `12/12` handle/anchor-honesty/context PASS; Preview usefulness: `3 PASS`, `3 WARN`, `6 FAIL` (e.g., `048208.txt` `p000001` opening clipped to `"Cullen, J."` while `q000001` spans `155-935` across `p000001` and body heading `Facts:`; `048208.txt` `p000015` where `[15]` prefix prevented merging `v01` and `v02` and crowded out `p000015:a0002` and `a0003`).
- **`risk_3_very_short_abbrev_or_placeholder_previews` (`000841.txt`, `079842.txt`, `001867.txt`, `051807.txt`):** `12/12` handle/neighbor/context PASS; Preview usefulness: `4 PASS`, `2 WARN`, `6 FAIL` (e.g., `000841.txt` `p000007` is marker-only `[2]` and honestly sets `preview_absence_reason = "no_meaningful_opening_or_anchor"`; `001867.txt` `u000003` clips `"John H. Sims, Deputy Attorney General..."` to `"John H."`; `051807.txt` `u000030` clips numbered issue `"1. Did the Citizenship Judge err..."` to `"1."`).
- **`risk_4_high_unnumbered_ratio` (`027775.txt`, `010665.txt`, `019027.txt`, `022215.txt`):** `12/12` handle/neighbor/context PASS (`content_unit_order` cleanly chains unnumbered blocks); Preview usefulness: `8 PASS`, `3 WARN`, `1 FAIL` (`022215.txt` `u000001` clipped at `"1."`).
- **`risk_5_french_or_mixed_language` (`081611.txt`, `009771.txt`, `059171.txt`, `097824.txt`):** `12/12` handle/neighbor/context/language PASS; Preview usefulness: `9 PASS`, `1 WARN`, `2 FAIL` (`009771.txt` `p000005` clipped at `"Pinard, J."` and `p000007` crowded out `a0002`).

---

## 4. Section C — Answers to the 4 Required Review Questions

### Question 1: Is the M2 navigation bundle contract-valid across all `7,708` cases?
**Yes — 100% contract-valid across all `7,708` cases.**
Every structural invariant specified in `M2.md` and `SOURCE_CHUNK_INDEX.md` holds without exception across all `7,708` cases (`431,333` structural units, `382,343` content units, `48,990` headings, `481,926` previews, `216,946` unit anchors, and `1,237` source anchors). Byte spans and SHA-256 digests match raw source bytes 100%; cross-stage provenance to `m0_20261105_v2` and `m1_20261105_v2` is intact; `tamper_and_runtime_boundary_tests.py` confirmed that tampering, resealing without rebuilding, source byte drift, profile drift, M1 seal drift, and invalid `open()` / `map()` boundaries all fail loud with `M2Error`; and deferred token fields (`token_count: null`, readiness `"not_ready"`) are 100% honest.

### Question 2: Are `map` previews useful and honest for agent navigation, or do they hide/distort important legal signals?
**They are 100% byte-honest, but have 3 deterministic selection defects (`M2-FINDING-001`, `M2-FINDING-002`, `M2-FINDING-003`) that hide important legal signals in a substantial fraction of units:**
1. **Abbreviation clipping + false sentence-completion flag (`M2-FINDING-001`):** `85,518 / 382,286` (`22.37%`) of `opening` previews stop at the first period after a judge's title (`Pinard, J.`), honorific/initial (`Mr.`, `Ms.`, `Dr.`, `John H.`), statutory citation (`s.`), or list number (`1.`), yielding `34,974` (`9.15%`) previews of `<= 30` chars while falsely setting `partial_sentence: false` on `100%` (`85,518 / 85,518`) of them. Paragraph `[1]` of a decision—which almost always begins `[1]\r\n<Judge>, J.: This is an application for judicial review of...`—is reduced to `"<Judge>, J."` unless an anchor happens to appear in the same paragraph.
2. **Unmerged marker-prefixed anchor windows crowding out deeper anchors (`M2-FINDING-002`):** Because `left = max(start, a - 120)` includes the leading `[N]\r\n` marker that `_opening()` skipped, `left < opening[0]` blocks merging in `31,352` units and emits two overlapping previews (`56,996` units total). In **`11,505` units**, this duplicate preview consumes the 2nd display slot (`max_display = 2`) and hides a deeper citation or quote-introduction anchor later in the paragraph.
3. **Placeholder+punctuation opening lines (`M2-FINDING-003`):** In `932` units, leading lines containing only `<FRAGMENT_SUPPRESSED>` plus stray punctuation (`)`, `.`) are not skipped by `_opening()`.

### Question 3: Does parent + neighbor expansion (`open`) provide coherent reading context across normal paragraphs, unnumbered regions, repeated/non-monotonic markers, and French/mixed-language regions?
**Yes — 100% coherent (`144 / 144` sampled regions PASS, `744,547 / 744,547` neighbor links PASS).**
- **Normal paragraphs & party submissions (`unknown` role):** Opening `parent` with `neighbors` (`paragraph_order`) cleanly supplies the preceding and following numbered paragraphs plus any intervening section headings (`intervening_headings`), resolving whether an `unknown` paragraph is a party submission, statutory block quote, or judicial analysis (e.g., `071570.txt` `p000018`, `041335.txt` `p000014`).
- **Repeated / non-monotonic markers:** Because neighbor links follow `source_order` rather than arithmetic marker numbers, cases with repeated `[1]` blocks, appendices, or numbering resets (`33,955` repeated markers, `9,865` non-sequential jumps, e.g., `076711.txt`, `071688.txt`, `025614.txt`) expand without jumping or dropping text.
- **Unnumbered regions:** `content_unit_order` links unnumbered header/summary/order blocks to adjacent paragraphs or unnumbered blocks in exact document order (`027775.txt`, `010665.txt`).
- **French & mixed-language regions:** All `13,189` `fr:*` content units and bilingual statutory quotes (`081611.txt`, `059171.txt`, `023047.txt`) preserve exact UTF-8 byte offsets and neighbor chains.

### Question 4: What concrete issues must be fixed before connecting token-based chunking or agent evaluation, and what issues are acceptable documented limitations?

#### Must Be Fixed Before Next Stage (`fixes_required_before_next_stage`)
1. **`M2-FINDING-001` (High — `pipeline_v2/navigation/core.py` lines 35–36, 128):** Make `_opening()` and `partial_sentence` abbreviation-aware so judicial titles (`Pinard, J.`, `J.A.`), honorifics/initials (`Mr.`, `Ms.`, `Dr.`, `M.`, `[A-Z].`), list markers (`1.`, `A.`), and statutory/reporter abbreviations (`s.`, `ss.`, `para.`, `v.`, `F.C.`, `R.S.C.`) do not terminate the opening preview mid-sentence or set `partial_sentence: false`.
2. **`M2-FINDING-002` (High — `pipeline_v2/navigation/core.py` lines 103–116):** Clamp anchor window start to `content_start = opening[0] if opening else start` (excluding the leading `[N]\r\n` marker and skipped placeholder lines) and use two-way containment/overlap merging between `opening` and `anchor` windows so duplicate substrings do not waste the second preview slot and crowd out deeper anchors (`11,505` units affected).
3. **`M2-FINDING-003` (Medium — `pipeline_v2/navigation/core.py` lines 26–27):** Require at least one alphanumeric character (`any(ch.isalnum() for ch in PLACEHOLDER.sub("", value))`) when advancing past leading placeholder-only lines in `_opening()` (`932` units affected).

#### Acceptable Documented Limitations (No Architecture Change Required)
- **`M2-FINDING-004` (Low):** Hard character-offset cuts in `anchor` windows (`4,656` partial anchor visibilities, `1,164` partial source-cue visibilities) are honestly flagged via `visibility: "partial"`, `fully_visible: false`, and `source_cue_fully_visible: false` (optionally improvable by reducing pre-anchor padding when `b - a > 120`).
- **`M2-FINDING-005` (Info):** Conservative `paragraph_role: "unknown"` (`355,736` paragraphs), `55` marker-only units with `preview_absence_reason: "no_meaningful_opening_or_anchor"`, and deferred tokenizer/chunk readiness flags (`token_count: null`, `not_ready`) are faithful to the M1/M2 contract.
- **Uncertified Downstream Components:** Embedding tokenizer, agent tokenizer, token-validated `RETRIEVAL_UNIT` chunks, lexical/dense retrieval indexes, and live M4 agent budget enforcement remain intentionally uncertified at M2.

---

## 5. Deliverables & Evidence Index

All review artifacts are stored in `pipeline_v2/reviews/m2_navigation_ag_review_v1/`:
1. `REPORT.md` — This independent review report.
2. `machine_audit_results.json` — Full-corpus independent audit results across all `7,708` cases (`77.89s`).
3. `tamper_and_boundary_results.json` — Results of all 8 adversarial tamper, reseal, provenance drift, pagination, and multi-hit dedup tests (`0.698s`).
4. `sampling_manifest.json` — Locked deterministic sample (`seed = 20261105`, `48` cases, `0` discovery/holdout overlap).
5. `extracted_regions_raw.json` — Raw evidence and M2 `map`/`open` views for all `144` sampled regions.
6. `reviewed_regions.json` — Per-region adjudication across all `144` regions (`uniform_random_20`, `risk_stratified_20`, `regression_exposed_8`).
7. `findings.json` — Structured defect and limitation records (`M2-FINDING-001` through `M2-FINDING-005`) with exact byte spans, verbatim text, reproduction commands, and minimal fix directions.
8. `commands_and_results.json` — Complete log of all executed commands, including failed runs and retries.
9. `scripts/` — Reproducible audit and review scripts (`independent_corpus_audit.py`, `tamper_and_runtime_boundary_tests.py`, `lock_sampling_and_extract_regions.py`, `adjudicate_reviewed_regions.py`).
