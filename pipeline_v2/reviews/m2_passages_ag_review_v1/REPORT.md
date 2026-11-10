# Independent AG Review Report — M2 Token Passages (`m2_passages_20261106_v1`)

## 1. Executive Summary & Overall Verdict

- **Overall Verdict:** **`ready_with_documented_limits`**
- **Target Bundle Reviewed:** `pipeline_v2/artifacts/m2_passages_20261106_v1/`
  - `seal.json` SHA-256: `0ed42d51023adaf47c1205fa925f18f31b7aacb58b0c8e44c7d23288d123dda6`
  - `manifest.json` SHA-256: `8049baf26cdc1ccb60d9c1b821623babfdd5f507a8a8f761cc7ce996a76d1bb6`
  - `summary.json` SHA-256: `073e4490250b716e3da2604f2093d06c12312db71e480d3dd54252a42118b83f`
  - `source_registry.json` SHA-256: `65005305c8f667debe0a47eba4b7ccf8ab6eb8940e57775cb66c4cfa933a36c2`
  - File universe: `7,711` sealed entries (`7,708` per-case `sources/*.json` + `manifest.json` + `source_registry.json` + `summary.json`) + `seal.json` = **`7,712` files**, **`938,891,921` bytes**
- **Upstream & Configuration Bindings Verified:**
  - Raw train corpus: `data/task1_train_files_2026/cases/` (`7,708` UTF-8 text files, `225,398,607` bytes)
  - M0 baseline cohort & inventory: `pipeline_v2/artifacts/m0_20261105_v2/` (`inventory.json` SHA-256: `e873514712f7e6f9ef03af7ec14993dfe78e3cac0aa89f8f23ce79af6d2f80db`)
  - M1 structural sidecar bundle: `pipeline_v2/artifacts/m1_20261105_v2/` (`seal.json` SHA-256: `cd807dea79ecab5b895dbb182cfea0cec6417322d3a890d92ca32ed7c615ed7e`)
  - M2 navigation v3 bundle: `pipeline_v2/artifacts/m2_navigation_20261106_v3/` (`seal.json` SHA-256: `43ca58589704e94754be3ed6b343ffa73f806a0c757c752abffa1fdb4942234c`)
  - Passages profile: `pipeline_v2/configs/m2_passages.json` (SHA-256: `430ad6fe1c9c5541c29335fbd8d9150f11d59c571cc48d5b1cca13018096deb7`)
  - Tokenizer lock: `pipeline_v2/configs/qwen3_embedding_4b_tokenizer.lock.json` (SHA-256: `2ce6b78aefd3415e1a06ab1fc5fe3e88b3a565e175227b7ee055054db3382dd8`, fingerprint: `1588b3e70f144e9ced344f840fdd68ab75034ecb8f8bb573a74dcd0bcaa29885`)
- **Review Output Directory:** `pipeline_v2/reviews/m2_passages_ag_review_v1/`
- **Summary of Findings:**
  - **`0` production defects** were found across all `7,708` cases (`382,343` parents, `415,693` passages, `9,856` split parents, `55,346,360` full-input tokens, `4,244,972` content overlap tokens).
  - **5 documented design limits** (`M2-PASSAGES-LIMIT-001` through `M2-PASSAGES-LIMIT-005`) are truthfully declared in `manifest.json`, `summary.json`, and `M2_PASSAGES.md`.
  - **Local token validation vs. endpoint readiness:** Local token counts and passage spans are `ready`, whereas `embedding_runtime` (`dense_runtime`) and `indexes` are properly marked `not_ready` (`runtime_compatibility: "pending_endpoint_preflight"`), and `M4` agent payload budgeting/delivery remains unimplemented (`diagnostic_only: true`, `M4_delivery_recorded: false`).

---

## 2. Scope, Read-Only Hygiene, and Resource Accounting

- **Strict Read-Only on Production & Historical Artifacts:** Zero files outside `pipeline_v2/reviews/m2_passages_ag_review_v1/` were created or modified.
- **Data & Model Hygiene:**
  - `labels_accessed = false`, `test_sources_accessed = false` (`cohort.json` was read solely to exclude the 10 `discovery_queries` and 10 `holdout_queries` before sampling).
  - `weights_downloaded = false`, `modal_deployed = false`, `M3_or_later_executed = false`.
  - `model_inference_requests = 0`, `model_inference_retries = 0`, `model_inference_tokens = 0`.
  - `development_chat_tokens = unknown` (not measured by runtime).

---

## 3. Verification of the 6 Mandatory Review Checks

### Check 1: Real CLI, Test Suites, Seal, Tamper/Reseal, and Drift After Reader Initialization (`PASS`)

Executed via unit test suites and `scripts/tamper_tokenizer_and_cli_tests.py` (`tamper_tokenizer_and_cli_results.json`):
1. **Unit Test Suites:**
   - Full discovery suite (`python -m unittest discover -s pipeline_v2/tests -v`): **`65/65 PASS` in `10.504s`**.
   - Targeted M2 passages suite (`test_m2_passages_core`, `test_m2_passages_store`): **`9/9 PASS` in `7.305s`**.
2. **CLI Execution (`python -m pipeline_v2.m2_passages`):**
   - Verified `--help`, `inspect --case 041666.txt --offset 0 --limit 3` (`total=555`, exit code `0`), `open --case 041666.txt --passage-id 041666:6aa38298330c0005b7207373` (exit code `0`), and invalid passage ID rejection (`exit_code = 2`, `{"valid": false, "error": "Unknown passage ID"}`).
3. **Tamper & Reseal Rejection (Isolated Temp Copy):**
   - Unsealed edit to `sources/000001.json` -> rejected with `PassageError: Passage seal integrity failure`.
   - **Resealed token-count tamper** (incrementing `full_input_tokens`, updating `source_registry.json`, and resealing `seal.json`) -> rejected with `PassageError: Passage differs from exact source/tokenizer/profile`.
   - **Resealed text tamper** (modifying passage `text`, updating `source_registry.json`, and resealing `seal.json`) -> rejected with `PassageError: Passage differs from exact source/tokenizer/profile`.
   - Adding an unsealed file `sources/extra.json` -> rejected by `validate_bundle` with `PassageError: Unexpected/missing passage bundle files`.
4. **Upstream Drift After `PassageReader` Initialization (Same Reader Instance):**
   - Because `PassageReader._case(..., verify_tokenizer=True)` reconstructs `NavigationReader` (which reconstructs `SourceReader`) and calls `self.tokenizer.verify()` and `load_profile()` on every interactive read, mutating any of the following **after** `PassageReader(temp_root, bundle)` is constructed is immediately rejected on the next `reader.inspect("000001.txt")` call:
     - Raw source file `cases/000001.txt` -> `M1Error: Source drift: 000001.txt`
     - `configs/m2_passages.json` -> `PassageError: Passage inputs drifted after reader construction`
     - `configs/m2.json` -> `M2Error: M2 profile/code/M1 provenance drift`
     - `configs/m1.json` -> `M1Error: M1 code/config/M0 provenance drift`
     - `configs/qwen3_embedding_4b_tokenizer.lock.json` -> `PassageError: Tokenizer lock drift`
     - Vendor asset `tokenizer_config.json` -> `PassageError: Tokenizer asset drift: tokenizer_config.json`
     - `m1-fixture/sources/000001.json` -> `M1Error: Artifact integrity failure: sources/000001.json`
     - `m2-fixture/sources/000001.json` -> `M2Error: M2 artifact seal integrity failure`

---

### Check 2: Independent Full-Corpus Raw/Token/Provenance Audit (`PASS`)

Executed via `scripts/independent_corpus_audit.py` (`independent_corpus_audit.json`, **`0` errors across `7,708` sources in `569.320s`**) without importing `pipeline_v2.passages`:

| Invariant / Metric | Verified Value | Status |
|---|---:|---|
| Train case universe (`raw == M0 == M1 == M2_nav == M2_passages`) | `7,708 / 7,708` cases | `PASS` |
| Total raw corpus bytes (`data/task1_train_files_2026/cases/*.txt`) | `225,398,607` bytes | `PASS` |
| Indexed navigation parent units (`paragraph` + `unnumbered`) | `382,343` units (`223,375,957` bytes, `99.1026%` of raw) | `PASS` |
| Unindexed standalone `heading` units in M1 partition | `48,990` units (`481,721` bytes, `0.2137%` of raw) | `PASS` (Reported, source-addressable) |
| Unindexed standalone `whitespace` units in M1 partition | `514,659` units (`1,540,929` bytes, `0.6836%` of raw) | `PASS` (Reported, source-addressable) |
| Exact byte partition reconciliation (`parent + heading + whitespace == raw`) | `223,375,957 + 481,721 + 1,540,929 == 225,398,607` | `PASS` |
| Total passages (`passage_id == chunk_id`, globally unique & hash-verified) | `415,693` passages | `PASS` |
| Split parents (`unsplit_parent_full_tokens > 448`) | `9,856` parents (`43,206` child passages) | `PASS` |
| Intact parents (`unsplit_parent_full_tokens <= 448`, `split_count == 1`) | `372,487` parents (`9,742` with `320 < tokens <= 448`) | `PASS` |
| Contiguous parent coverage (`first.a == ua`, `last.b == ub`, `a <= prev_end < b`, `a > prev_start`) | `382,343 / 382,343` parents | `PASS` |
| Exact raw UTF-8 slice & char/byte round-trip (`raw[a:b].decode() == text == case_text[ca:cb]`) | `415,693 / 415,693` passages | `PASS` |
| Passages by `unit_kind` (`paragraph` / `unnumbered`) | `385,697` / `29,996` | `PASS` |
| Passages by `paragraph_role` (`unknown` / `quoted` / `None`) | `384,419` / `1,278` / `29,996` | `PASS` |
| Navigation units without preview (`preview_refs == []`) still indexed | `267 / 267` parents | `PASS` |
| French language-region (`fr:*`) parents / passages preserved | `13,189` parents / `14,289` passages | `PASS` |

---

### Check 3: Pinned Tokenizer Lock, `<|endoftext|>` (`151643`) Postprocessor, Content-Only Overlap & Edge Cases (`PASS`)

1. **Pinned Assets & Package Version:**
   - `Qwen/Qwen3-Embedding-4B` revision `5cf2132abc99cad020ac570b19d031efec650f2b`, `tokenizers==0.22.2`.
   - All 6 vendor files (`tokenizer.json`, `tokenizer_config.json`, `vocab.json`, `merges.txt`, `config.json`, `README.md`) match exact SHA-256 and byte lengths in `qwen3_embedding_4b_tokenizer.lock.json`.
   - Document rendering uses exact raw `{body}` without instruction or chat template (`add_bos_token=False`, `add_eos_token=False`, `truncation=False`, `padding=False`).
2. **Official Postprocessor & Special-Token Accounting:**
   - `tokenizer.json` defines a `Sequence` postprocessor (`ByteLevel` + `TemplateProcessing`) that appends **one `<|endoftext|>` (`151643`)** when `add_special_tokens=True`.
   - Across all `415,693` passages in the corpus, independent re-encoding confirmed:
     - `encode(text, add_special_tokens=True).ids[-1] == 151643`
     - `full_input_tokens == len(encode(text, add_special_tokens=True).ids) == len(encode(text, add_special_tokens=False).ids) + 1 <= 448`
     - `overlap_tokens_with_previous == len(encode(overlap_slice, add_special_tokens=False).ids) <= 128` (content-only, never adding a synthetic `<|endoftext|>` to the overlap slice).
3. **Edge-Case & Property Verification (`test_3_tokenizer_lock_postprocessor_and_edge_cases`):**
   - Verified exact raw slice preservation and token bounds on:
     - Fitting parent above target (`"word "*400`, `402` full tokens -> kept as `1` intact slice).
     - CRLF + UTF-8 BOM (`"\ufeff" + "  clause\r\n"*1000` -> `15` slices, max `321` full tokens, max `128` overlap).
     - Multi-codepoint Unicode / CJK / ZWJ emoji (`"\u00e9\u6cd5\U0001f9d1\u200d\u2696\ufe0f "*400` -> `11` slices, max `374` full tokens, max `128` overlap).
     - Long unbroken string without whitespace (`"A"*9000` -> `6` slices, max `321` full tokens, `word_boundary_splits=5`).
     - Literal special tokens in raw text (`"<|endoftext|> literal <|im_start|> "*500` -> `13` slices, max `321` full tokens, max `127` overlap).
     - Impossible caps (`overlap_tokens=320 >= target_tokens=320`, `target_tokens=449 > max_input_tokens=448`, empty parent `""`, and `max_input_tokens=1` on a multi-token codepoint `\U0001f9d1`) all raise `PassageError`.

---

### Check 4: Profile Variant (`320` / `128` / `448`), Token Histograms & Overhead Reconciliation (`PASS`)

1. **Profile Verification:**
   - `variant = "within_parent_overlap_128_not_nonoverlap_baseline"`, `target_tokens = 320`, `overlap_tokens = 128`, `max_input_tokens = 448`, `merge_parents = false`.
   - Every parent with `unsplit_parent_full_tokens <= 448` (`372,487` parents) is kept intact (`split_count == 1`), including **`9,742` intact parents with `320 < full_input_tokens <= 448`** and **`37` intact parents at the exact `448`-token cap**.
   - Every parent with `unsplit_parent_full_tokens > 448` (`9,856` parents) is split into `43,206` children (`9,856` first children + `33,350` non-first children), each `<= 448` full-input tokens.
2. **Full-Input Token Distribution (`415,693` passages):**
   - Percentiles: `min = 2`, `p25 = 63`, `median = 106`, `mean = 133.1424`, `p75 = 177`, `p95 = 321`, `p99 = 376`, `max = 448` (`37` passages at `448`).
   - 64-token histogram bins (`summary.json` match):
     - `token_bin_0` (`0..63`): `104,446`
     - `token_bin_64` (`64..127`): `144,108`
     - `token_bin_128` (`128..191`): `75,233`
     - `token_bin_192` (`192..255`): `31,693`
     - `token_bin_256` (`256..319`): `21,988`
     - `token_bin_320` (`320..383`): `34,623`
     - `token_bin_384` (`384..447`): `3,565`
     - `token_bin_448` (`448`): `37`
3. **Overlap Content Token Distribution (`33,350` non-first split children):**
   - `min = 90`, `p25 = 127`, `median = 128`, `mean = 127.2855`, `p75 = 128`, `p95 = 128`, `max = 128`.
   - `22,275` children (`66.79%`) have exactly `128` overlap tokens; `11,075` children (`33.21%`) have `90..127` overlap tokens because `split_text` snaps `next_start` forward to the next whitespace boundary (`whites[0].end()`).
4. **Exact Corpus Token & Overhead Reconciliation:**
   - Unsplit parent content tokens (`382,343` parents): `50,685,695`
   - Unsplit parent full tokens (`+382,343` `<|endoftext|>`): `51,068,038`
   - Passage content tokens (`415,693` passages): `54,930,667`
   - Overlap content tokens (`33,350` non-first children): `4,244,972`
   - **Exact BPE conservation identity:** `54,930,667 - 4,244,972 == 50,685,695` (`passage_content_tokens - overlap_content_tokens == unsplit_parent_content_tokens`), proving zero content tokens were lost or corrupted across all `9,856` split parents.
   - Passage `<|endoftext|>` tokens: `415,693`
   - Total passage full-input tokens: `54,930,667 + 415,693 = 55,346,360` (`1.083777x` expansion over unsplit parent full tokens; overlap content tokens represent `7.6698%` of total full-input tokens).

---

### Check 5: Real Middle-Child `PassageReader.open_context` Verification (`PASS`)

Executed via `test_5_real_middle_child_open_context_scenarios` in `scripts/tamper_tokenizer_and_cli_tests.py` (`tamper_tokenizer_and_cli_results.json`) on `m2_passages_20261106_v1`:

| Scenario | Case / Parent Handle | Middle Child `passage_id` (`split_order / split_count`) | Hit Span Bytes | Parent Span Bytes | Opened Envelope Span Bytes | Opened Components & Intervening Structure |
|---|---|---|---|---|---|---|
| 1. End-of-source largest split parent | `041666.txt` / `p000417` (`[328]`) | `041666:6aa38298330c0005b7207373` (`55 / 110`) | `282037..283127` | `234305..318510` (`84,205` B) | `233500..318510` (`85,010` B) | `previous_context=p000416` (`[327]`), `parent=p000417` (`[328]`), no `next_context` (`next_absence_reason="source_boundary"`), + `1` intervening heading `"JUDGMENT"` (`234295..234303`) |
| 2. Interior split parent skipping unnumbered units | `041666.txt` / `p000153` (`[84]`) | `041666:3f296642490ce0314e005143` (`1 / 24`) | `50291..51613` | `49563..67497` (`17,934` B) | `49196..67951` (`18,755` B) | `previous_context=p000151` (`[83]`), `parent=p000153` (`[84]`), `next_context=p000155` (`[85]`), skipping `u000152`/`u000154` in `paragraph_order` while raw envelope retains them + `3` intervening headings (`"VII."`, `"VIII."`, `"ANALYSIS"`) |
| 3. Start-of-source split unnumbered parent | `000287.txt` / `u000001` (`None`) | `000287:0c56c7e263f36cbed6b46e84` (`2 / 5`) | `1169..2194` | `0..3169` (`3,169` B) | `0..3533` (`3,533` B) | No `previous_context` (`previous_absence_reason="source_boundary"`), `parent=u000001`, `next_context=p000002` (`[1]`) under `content_unit_order` |
| 4. Jumping-marker split parent | `000054.txt` / `p000009` (`[9]`) | `000054:90b705b4109e9f85d65f7c2d` (`2 / 4`) | `5662..7287` | `3898..7456` (`3,558` B) | `3349..8282` (`4,933` B) | `previous_context=p000008` (`[8]`), `parent=p000009` (`[9]`), `next_context=p000010` (**marker `[11]`**, jumping over missing `[10]` by source order rather than marker arithmetic) |
| 5. Intervening-heading split parent | `000002.txt` / `p000042` (`[42]`) | `000002:f3a85de463da7a5b691dc0ba` (`1 / 3`) | `20403..21696` | `19490..22408` (`2,918` B) | `19117..24081` (`4,964` B) | `previous_context=p000041` (`[41]`), `parent=p000042` (`[42]`), `next_context=p000044` (`[43]`), preserving intervening heading `"CONCLUSION"` (`22410..22420`) and unnumbered `u000043` in raw slice |

In all 5 scenarios (and all `126` regions in `extracted_regions_raw.json`), `opened["hit_is_distinct_from_context"] == True`, `opened["diagnostic_only"] == True`, `opened["M4_delivery_recorded"] == False`, and `opened["text"] == raw[opened["span_bytes"][0]:opened["span_bytes"][1]].decode("utf-8")`.

---

### Check 6: Locked Sample (`seed=20261106`, `20` Random + `20` Risk Cases) & Content/Boundary Adjudication (`PASS`)

1. **Locked Sample Hygiene (`sampling_manifest.json`):**
   - Locked before reading raw case text using `seed = 20261106`.
   - Excluded M0 `discovery_queries` (`10` cases) and `holdout_queries` (`10` cases) from `pipeline_v2/artifacts/m0_20261105_v2/cohort.json`.
   - Separated `22` previously exposed regression cases (`041666.txt`, `4` M1/M2 structural fixtures `050936/061295/062436/067620`, `8` prompt preview regressions, and `9` v2 tag-clip regressions) into `separate_regression_groups`.
   - Eligible pool: `7,666` cases -> drew `20` uniform random cases + `20` risk-stratified cases (`4` per stratum across `5` strata), with `overlap_between_uniform_and_risk = 0`, `overlap_with_discovery_or_holdout = 0`, and `overlap_with_separate_regressions = 0`:
     - **`uniform_random_20`:** `000777.txt`, `001201.txt`, `002348.txt`, `004252.txt`, `008003.txt`, `010465.txt`, `012505.txt`, `020000.txt`, `021926.txt`, `025667.txt`, `026294.txt`, `030557.txt`, `038541.txt`, `060970.txt`, `064822.txt`, `064829.txt`, `067022.txt`, `088722.txt`, `092785.txt`, `095694.txt`.
     - **`risk_1_long_split_parents_and_448_cap`:** `011919.txt`, `044492.txt`, `049243.txt`, `080634.txt`.
     - **`risk_2_unicode_multibyte_and_french`:** `033536.txt`, `039093.txt`, `044061.txt`, `054218.txt`.
     - **`risk_3_tight_whitespace_or_fallback_boundary`:** `016872.txt`, `046523.txt`, `067658.txt`, `074591.txt`.
     - **`risk_4_jumping_or_repeated_markers_and_quoted`:** `020740.txt`, `063659.txt`, `070740.txt`, `084744.txt`.
     - **`risk_5_unknown_unnumbered_and_no_preview`:** `027864.txt`, `050528.txt`, `065680.txt`, `076001.txt`.
2. **Region Extraction & Adjudication Summary (`extracted_regions_raw.json`, `reviewed_regions.json`):**
   - `120` sampled regions (`3` per case across `40` cases) + `6` separate regression regions = `126` regions inspected with exact raw slices, overlap slices, token counts, and `PassageReader.open_context` calls:
     - **Mechanical Integrity:** **`120 / 120` (`100%`) `PASS`** on sampled regions; **`6 / 6` (`100%`) `PASS`** on separate regression regions.
     - **Coverage of Risk Categories in Sampled Regions:**
       - `35` split-parent regions (middle children and overlap boundaries inspected)
       - `85` intact whole-parent regions, including `13` intact parents with `320 < full_input_tokens <= 448` and `4` parents at the exact `448`-token cap (`011919/p000025`, `044492/p000006`, `049243/p000015`, `080634/p000012`)
       - `7` units without preview (`preview_refs == []`, `preview_absence_reason == "no_meaningful_opening_or_anchor"`) confirmed indexed as valid passages and expandable via `open_context`
       - `11` `paragraph_role == "quoted"` regions, `47` `unit_kind == "unnumbered"` regions, and `5` French (`fr:*`) regions.
     - **Content & Boundary Assessment (Distinguished from Mechanical Check):**
       - On the `85` intact whole-parent regions (`split_count == 1`), the passage boundary is the exact structural unit boundary (`cut_classification = "intact_whole_parent"`).
       - On the `35` split-parent regions (`split_count > 1`), cuts occur at whitespace near the `320`-token soft target (`cut_classification = "split_parent_whitespace_cut_not_sentence_verified"`). As recorded in `reviewed_regions.json`, many split boundaries cut mid-sentence between words or inside statutory/citation blocks (for example, `000777.txt/u000001` child `2/3` ends at `'...Dr. Fernando Muzzio (On Validity)\r\n25\r\n'`, and `041666.txt/p000153` child `2/24` ends at `'...less than 12 months, or, in the case '`). These boundaries are **not** certified sentence boundaries (`semantic_sentence_verified = "unresolved_whitespace_cut_only"`), and `open_context` is required (and verified) to restore the full parent and neighboring paragraphs.
       - Across all `126` regions, semantic paragraph ownership (`current_case` vs `quoted`), legal authority identity, and chunking retrieval optimality remain `unresolved_by_design_in_M2`.

---

## 4. Complete Log of Commands, Receipts, Failed Attempts & Retries (`commands_and_results.json`)

| Step / Receipt | Command / Artifact | Exit Code | Elapsed (s) | Status & Explanation |
|---|---|---|---|---|
| Historical Receipt 1 | `pipeline_v2/reviews/m2_tokenizer_acquisition_v1.json` | N/A | `6.216` | **`FAIL` (Expected Gate Stop):** Stopped after 6 HTTP 200 downloads when non-null `post_processor` was detected in `tokenizer.json` (preceded by 1 sandbox-refused metadata call and 1 approved metadata call). |
| Historical Receipt 2 | `pipeline_v2/reviews/m2_tokenizer_acquisition_v2.json` | N/A | `0.790` | **`PASS`:** Verified local SHA-256 hashes of all 6 tokenizer files and locked the `<|endoftext|>` (`151643`) postprocessor. |
| Historical Receipt 3 | `pipeline_v2/artifacts/m2_passages_20261106_v1.build-receipt.json` | `0` | `921.598` (`921.792` wrapper) | **`PASS`:** Full build of `m2_passages_20261106_v1` (`7,708` sources, `382,343` parents, `415,693` passages). |
| Historical Receipt 4 | `pipeline_v2/reviews/m2_passages_validation_v1/validator_receipt.json` | `0` | `947.305` (`947.560` wrapper) | **`PASS`:** Full `m2_passages validate` rebuild-check across all `7,708` sources. |
| Historical Receipt 5 | `pipeline_v2/reviews/m2_passages_validation_v1/middle_child_result.json` | `0` | `16.510` | **`PASS`:** Middle-child context check on `041666/p000417` and `041666/p000153` (includes `prior_attempt: FAIL` where checker assumed `next_context` existed at end of file). |
| Historical Receipt 6 | `pipeline_v2/reviews/m2_passages_validation_v1/full_corpus_audit.json` | `0` | `450.474` | **`PASS`:** Tester corpus audit (`0` errors). |
| AG Review Step 1 | `python -m pipeline_v2.m2_passages --help` + full unittest (`65` tests) + targeted (`9` tests) | `0` | `20.100` | **`PASS`:** `65/65` tests in `10.504s`; `9/9` passage tests in `7.305s`. |
| AG Review Step 2 | `python .../scripts/tamper_tokenizer_and_cli_tests.py` | `0` | `39.901` | **`PASS`:** `5/5` test groups passed (`tamper_tokenizer_and_cli_results.json`). |
| AG Review Step 3 | `python .../scripts/independent_corpus_audit.py` (Run 1) | `1` | `8.900` | **`FAILED_REVIEW_SCRIPT_KEY_FIXED_IN_RETRY`:** Script accessed `m0_inventory["cases"]` instead of `m0_inventory["sources"]`. Fixed script key; production untouched. |
| AG Review Step 4 | `python .../scripts/lock_sample_and_extract_passages.py` | `0` | `148.559` | **`PASS`:** Locked `40` cases (`120` regions) + `6` separate regressions (`sampling_manifest.json`, `extracted_regions_raw.json`). |
| AG Review Step 5 | `python .../scripts/adjudicate_passages_regions.py` | `0` | `0.011` | **`PASS`:** Adjudicated all `126` regions (`reviewed_regions.json`). |
| AG Review Step 6 | `python .../scripts/independent_corpus_audit.py` (Run 2) | `0` | `569.320` | **`PASS`:** `0` errors across all `7,708` cases (`independent_corpus_audit.json`). |

---

## 5. Final Handover & Stage Gate Conclusion

- **Verdict:** **`ready_with_documented_limits`**
- **What Is Certified Ready Locally:**
  - `pipeline_v2/artifacts/m2_passages_20261106_v1/` (`7,712` files, `938,891,921` bytes) preserves exact UTF-8 raw slices, hashes, char/byte spans, parent/sibling links, and source-order `reading_expansion` across all `7,708` train sources (`382,343` parents, `415,693` passages), with exact token counts (`<= 448` full-input tokens including `<|endoftext|>` `151643`, content-only overlap `<= 128`) under the pinned `Qwen/Qwen3-Embedding-4B` (`5cf2132abc99cad020ac570b19d031efec650f2b`, `tokenizers==0.22.2`) lock.
- **What Remains Gated for Subsequent Stages (Do Not Claim Ready Now):**
  1. **Modal / Embedding Runtime Preflight (Before M3 Dense Indexing):** Must verify remote engine revision, tokenizer, special-token handling (`<|endoftext|>`), document rendering (`{body}`), and effective endpoint token cap against the local lock before running paid inference.
  2. **Retrieval Quality & Overlap Policy (M3):** The `320 / 128 / 448` within-parent overlap profile is a provisional variant; retrieval effectiveness and case-level deduplication must be evaluated in M3 without counting overlapping children as independent case votes.
  3. **Agent Context Budgeting & Delivery Ledger (M4):** Agent tokenizer counting, payload pagination caps, and `requested / delivered / pending` context accounting belong to M4.
