"""Generate `findings.json` and `commands_and_results.json` for M2 Preview Revision 2 AG Review."""
from __future__ import annotations

import json
from pathlib import Path


def main():
    out_dir = Path(__file__).resolve().parents[1]
    audit = json.loads((out_dir / "machine_audit_results.json").read_text(encoding="utf-8"))
    tamper = json.loads((out_dir / "tamper_and_boundary_results.json").read_text(encoding="utf-8"))
    sampled = json.loads((out_dir / "sampling_manifest.json").read_text(encoding="utf-8"))
    reviewed = json.loads((out_dir / "reviewed_regions.json").read_text(encoding="utf-8"))

    findings_payload = {
        "schema_version": "m2-preview-revision2-ag-review-findings-v1",
        "bundle_reviewed": "pipeline_v2/artifacts/m2_navigation_20261106_v3",
        "bundle_seal_sha256": audit["seals_and_inventory"]["m2_navigation_20261106_v3"]["seal_sha256"],
        "overall_verdict": "ready_with_documented_limits",
        "new_defect_findings_count": 0,
        "new_defect_findings": [],
        "six_main_adjudications": [
            {
                "criterion_id": "ADJUDICATION-1",
                "title": "Opening previews are useful bounded windows, not premature period clips",
                "verdict": "PASS",
                "evidence_summary": (
                    "In v1, _opening() used a regex stopping at the first '.!?' and claimed partial_sentence=False, "
                    "producing 33,441 opening previews <= 30 chars (and 22,942 <= 15 chars) with > 20 chars of remaining unit text "
                    "and 110,088 openings with < 100 non-placeholder chars in units >= 120 non-placeholder chars. "
                    "In v3, _opening() delegates to _safe_window(..., max_chars=240), reducing short openings <= 30 chars with more text "
                    "from 33,441 -> 0 (and <= 15 chars from 22,942 -> 0), and reducing < 100 clean-char openings in >= 120 clean-char units "
                    "from 110,088 -> 6 (all 6 are placeholder-dense units whose raw preview is 235-238 chars)."
                ),
                "concrete_examples": [
                    {
                        "case_id": "011922.txt",
                        "source_hash": "ae50db46d34a0ba0b85bdaab59084af6197e9313b91d8a1f0bf5dcda1efac8a2",
                        "unit_id": "011922:ae50db46d34a0ba0:625-1316:20c8805023c2",
                        "handle": "p000005",
                        "v1_preview": {
                            "preview_id": "p000005:v01",
                            "span_bytes": [637, 647],
                            "span_chars": [637, 647],
                            "text": "Pinard, J.",
                            "partial_sentence": False
                        },
                        "v3_preview": {
                            "preview_id": "p000005:v01",
                            "span_bytes": [637, 874],
                            "span_chars": [637, 874],
                            "text": "Pinard, J. \r\n : On March 14, 2011, Luftar Hysa (the \"applicant\") filed the present appeal, under subsection 14(5) of the  \r\n Citizenship Act \r\n , R.S.C. 1985, c. C-29 (the \"Act\"), from a decision of Judge Marcel Tremblay, the Citizenship",
                            "partial_sentence": None,
                            "start_clipped": False,
                            "end_clipped": True,
                            "truncated": True,
                            "word_boundary_clipped": False,
                            "tag_boundary_clipped": False
                        },
                        "reproduction_command": ".venv/Scripts/python.exe -m pipeline_v2.m2 map --repo-root . --bundle pipeline_v2/artifacts/m2_navigation_20261106_v3 --case-id 011922.txt --offset 4 --limit 1"
                    },
                    {
                        "case_id": "051807.txt",
                        "source_hash": "cceab97ca4511b717bb91f892c0558ffb5afb882bc4e6bb00a8ae5c62d4de692",
                        "unit_id": "051807:cceab97ca4511b71:11325-11688:20c8805023c2",
                        "handle": "u000030",
                        "v1_preview": {
                            "preview_id": "u000030:v01",
                            "span_bytes": [11325, 11327],
                            "span_chars": [11325, 11327],
                            "text": "1.",
                            "partial_sentence": False
                        },
                        "v3_preview": {
                            "preview_id": "u000030:v01",
                            "span_bytes": [11325, 11558],
                            "span_chars": [11325, 11558],
                            "text": "1. Did Citizenship Judge Cruden err in finding that the applicant did not meet the requirements of paragraph 5(1)(c) of the Citizenship Act, supra?\r\n2. Did Citizenship Judge Cruden err in failing to exercise the discretion granted by",
                            "partial_sentence": None,
                            "start_clipped": False,
                            "end_clipped": True,
                            "truncated": True
                        },
                        "reproduction_command": ".venv/Scripts/python.exe -m pipeline_v2.m2 map --repo-root . --bundle pipeline_v2/artifacts/m2_navigation_20261106_v3 --case-id 051807.txt --offset 29 --limit 1"
                    },
                    {
                        "case_id": "080359.txt",
                        "source_hash": "ca5cc56b2ff54a357aaa53015039e96765560188113b79494ca06343e854bcff",
                        "unit_id": "080359:ca5cc56b2ff54a35:81-157:20c8805023c2",
                        "handle": "u000002",
                        "v1_preview": {
                            "preview_id": "u000002:v01",
                            "span_bytes": [81, 93],
                            "span_chars": [81, 93],
                            "text": "Charlotte M.",
                            "partial_sentence": False
                        },
                        "v3_preview": {
                            "preview_id": "u000002:v01",
                            "span_bytes": [81, 157],
                            "span_chars": [81, 157],
                            "text": "Charlotte M. Janssen, for the applicant;\r\nNegar Hashemi, for the respondent.",
                            "partial_sentence": None,
                            "start_clipped": False,
                            "end_clipped": False,
                            "truncated": False
                        },
                        "reproduction_command": ".venv/Scripts/python.exe -m pipeline_v2.m2 map --repo-root . --bundle pipeline_v2/artifacts/m2_navigation_20261106_v3 --case-id 080359.txt --offset 1 --limit 1"
                    }
                ]
            },
            {
                "criterion_id": "ADJUDICATION-2",
                "title": "Opening previews skip placeholder/punctuation-only prefix lines when alphanumeric text exists",
                "verdict": "PASS",
                "evidence_summary": (
                    "In v1, _content_start() only checked not line.isspace(), causing 1,520 opening previews to begin on lines "
                    "containing only <FRAGMENT_SUPPRESSED>/<REFERENCE_SUPPRESSED> plus punctuation or separator dots. "
                    "In v3, _content_start() requires any(ch.isalnum() for ch in PLACEHOLDER.sub('', value)), reducing "
                    "opening_starts_on_placeholder_punct_line from 1,520 -> 0 across all 381,959 opening previews: "
                    "1,193 units advanced to the first real alphanumeric line and 327 units with zero alphanumeric content "
                    "outside markers/placeholders ceased emitting an opening preview (115 with placeholder anchors kept a clean "
                    "anchor preview; 212 without anchors moved to preview_refs=[] with preview_absence_reason='no_meaningful_opening_or_anchor')."
                ),
                "concrete_examples": [
                    {
                        "case_id": "081945.txt",
                        "source_hash": "a4de6b0c9511c0fa23085d23ab9db46e648106bb941821bf76a639e2ef4fe137",
                        "unit_id": "081945:a4de6b0c9511c0fa:2-235:20c8805023c2",
                        "handle": "u000001",
                        "v1_previews": [
                            {"preview_id": "u000001:v01", "preview_kind": "anchor", "span_bytes": [2, 143], "text": "<FRAGMENT_SUPPRESSED>   <FRAGMENT_SUPPRESSED>  \r\n \r\n  <FRAGMENT_SUPPRESSED> )  <FRAGMENT_SUPPRESSED>  \r\n  <FRAGMENT_SUPPRESSED>   <FRAGMENT_S"},
                            {"preview_id": "u000001:v02", "preview_kind": "opening", "span_bytes": [56, 235], "text": "<FRAGMENT_SUPPRESSED> )  <FRAGMENT_SUPPRESSED>  \r\n  <FRAGMENT_SUPPRESSED>   <FRAGMENT_SUPPRESSED>  \r\n Federal Court \r\n \r\n Mandamin, J. \r\n \r\n March 16, 2010.  <FRAGMENT_SUPPRESSED>"}
                        ],
                        "v3_previews": [
                            {"preview_id": "u000001:v01", "preview_kind": "opening", "span_bytes": [158, 235], "text": "Federal Court \r\n \r\n Mandamin, J. \r\n \r\n March 16, 2010.  <FRAGMENT_SUPPRESSED>", "anchor_refs": ["u000001:a0007"]}
                        ],
                        "unit_anchor_catalog_preserved": True,
                        "unit_anchor_count": 7,
                        "reproduction_command": ".venv/Scripts/python.exe -m pipeline_v2.m2 map --repo-root . --bundle pipeline_v2/artifacts/m2_navigation_20261106_v3 --case-id 081945.txt --offset 0 --limit 1"
                    },
                    {
                        "case_id": "015740.txt",
                        "source_hash": "2db4d8515e1944307ce61622673e1777ab80f92956161901b80e4f2160247c3b",
                        "unit_id": "015740:2db4d8515e194430:2-153:20c8805023c2",
                        "handle": "u000001",
                        "v1_previews": [
                            {"preview_id": "u000001:v01", "preview_kind": "anchor", "span_bytes": [2, 143], "text": "<FRAGMENT_SUPPRESSED>   <FRAGMENT_SUPPRESSED>  \r\n \r\n  <FRAGMENT_SUPPRESSED> )  <FRAGMENT_SUPPRESSED>  \r\n  <FRAGMENT_SUPPRESSED>   <FRAGMENT_S"},
                            {"preview_id": "u000001:v02", "preview_kind": "opening", "span_bytes": [56, 153], "text": "<FRAGMENT_SUPPRESSED> )  <FRAGMENT_SUPPRESSED>  \r\n  <FRAGMENT_SUPPRESSED>   <FRAGMENT_SUPPRESSED>"}
                        ],
                        "v3_previews": [
                            {"preview_id": "u000001:v01", "preview_kind": "anchor", "span_bytes": [2, 153], "text": "<FRAGMENT_SUPPRESSED>   <FRAGMENT_SUPPRESSED>  \r\n \r\n  <FRAGMENT_SUPPRESSED> )  <FRAGMENT_SUPPRESSED>  \r\n  <FRAGMENT_SUPPRESSED>   <FRAGMENT_SUPPRESSED>", "anchor_refs": ["u000001:a0001", "u000001:a0002", "u000001:a0003", "u000001:a0004", "u000001:a0005", "u000001:a0006"]}
                        ],
                        "reproduction_command": ".venv/Scripts/python.exe -m pipeline_v2.m2 map --repo-root . --bundle pipeline_v2/artifacts/m2_navigation_20261106_v3 --case-id 015740.txt --offset 0 --limit 1"
                    }
                ]
            },
            {
                "criterion_id": "ADJUDICATION-3",
                "title": "Preview deduplication and Slot 2 novel anchor coverage selection",
                "verdict": "PASS",
                "evidence_summary": (
                    "In v1, _add_window() only checked one-way containment (a <= left and right <= b) after inserting the anchor window first, "
                    "resulting in 20,147 contained duplicate preview pairs, 11,181 overlaps reaching before content_start into [N] markers, "
                    "and 14,154 multi-anchor units where 2 overlapping previews covered only 1 anchor. "
                    "In v3, bidirectional containment and merge-within-240 (when min(a, left) >= content_start) reduce contained pairs from 20,147 -> 0, "
                    "mergeable <=240 overlaps from 20,147 -> 0, and pre-content_start overlaps from 11,181 -> 0. "
                    "Slot 2 deterministic novel coverage selection increases units with >=2 anchors displaying >=2 anchors from 23,933/43,383 (55.17%) "
                    "to 37,827/43,383 (87.19%) and total displayed unit anchors from 141,352 (138,148 full) to 169,166 (168,652 full)."
                ),
                "concrete_examples": [
                    {
                        "case_id": "068193.txt",
                        "source_hash": "e74a2760a29e6ac599f0f0d9df6150cdee152927db98ff21840c1c5c50dcecd5",
                        "unit_id": "068193:e74a2760a29e6ac5:17372-17654:20c8805023c2",
                        "handle": "p000025",
                        "v1_previews_count": 2,
                        "v3_previews_count": 1,
                        "v3_preview_span_bytes": [17378, 17614],
                        "v3_displayed_anchors": ["p000025:a0001", "p000025:a0002"],
                        "reproduction_command": ".venv/Scripts/python.exe -m pipeline_v2.m2 map --repo-root . --bundle pipeline_v2/artifacts/m2_navigation_20261106_v3 --case-id 068193.txt --offset 24 --limit 1"
                    },
                    {
                        "case_id": "014101.txt",
                        "source_hash": "190e664505334bec149c744bbeb13c6511ae49e34110a49e413b87f9e6a8b968",
                        "unit_id": "014101:190e664505334bec:3310-5897:20c8805023c2",
                        "handle": "p000008",
                        "v1_displayed_anchors": ["p000008:a0001", "p000008:a0002"],
                        "v3_displayed_anchors": ["p000008:a0001", "p000008:a0002", "p000008:a0003"],
                        "reproduction_command": ".venv/Scripts/python.exe -m pipeline_v2.m2 map --repo-root . --bundle pipeline_v2/artifacts/m2_navigation_20261106_v3 --case-id 014101.txt --offset 7 --limit 1"
                    },
                    {
                        "case_id": "048208.txt",
                        "source_hash": "c75679c07aaaadd34830f7b6fda6e296075227b4498a73da020ded9c7f3869e6",
                        "unit_id": "048208:c75679c07aaaadd3:6298-7610:20c8805023c2",
                        "handle": "p000015",
                        "v1_displayed_anchors": ["p000015:a0001"],
                        "v3_displayed_anchors": ["p000015:a0001", "p000015:a0002", "p000015:a0003"],
                        "reproduction_command": ".venv/Scripts/python.exe -m pipeline_v2.m2 map --repo-root . --bundle pipeline_v2/artifacts/m2_navigation_20261106_v3 --case-id 048208.txt --offset 14 --limit 1"
                    }
                ]
            },
            {
                "criterion_id": "ADJUDICATION-4",
                "title": "Word and protected-tag boundary safety (including v2 -> v3 9-case tag-clip regression fix)",
                "verdict": "PASS",
                "evidence_summary": (
                    "In v1, raw character slicing produced 68,754 mid-word clips and 3,367 mid-tag clips (e.g. '<FRAGMENT_S' or '<'). "
                    "In v2, _safe_window() respected word and PROTECTED_TAG boundaries except when tail candidates passed a pre-clipped span "
                    "(max(a, b - max_chars), b) into _safe_window, leaving 245 mid-word clips and 9 mid-tag clips. "
                    "In v3, tail candidates pass the full original cue span (a, b) into _safe_window, reducing word_clipped_raw from 68,754 (v1) / 245 (v2) -> 0 (v3) "
                    "and tag_clipped_raw from 3,367 (v1) / 9 (v2) -> 0 (v3) across all 454,275 previews. "
                    "Furthermore, synthetic fallback testing on >240-char unbroken tokens/tags confirmed that word_boundary_clipped and tag_boundary_clipped "
                    "flip to True and are accepted by validate_case when a single token/tag exceeds 240 chars."
                ),
                "v2_9_tag_clip_cases_verified_in_v3": [
                    {
                        "case_id": c["case_id"],
                        "handle": c["handle"],
                        "unit_id": c["unit_id"],
                        "v2_clipped_span_bytes": c["v2_clipped_preview"]["span_bytes"],
                        "v2_clipped_text_prefix": c["v2_clipped_preview"]["text"][:45],
                        "v3_fixed_span_bytes": c["v3_previews"][-1]["span_bytes"],
                        "v3_fixed_text_prefix": c["v3_previews"][-1]["text"][:45],
                        "v3_word_boundary_clipped": c["v3_previews"][-1]["word_boundary_clipped"],
                        "v3_tag_boundary_clipped": c["v3_previews"][-1]["tag_boundary_clipped"]
                    }
                    for c in audit["v2_9_tag_clip_regressions_in_v3"]
                ]
            },
            {
                "criterion_id": "ADJUDICATION-5",
                "title": "Honest clipping/sentence metadata and units without preview",
                "verdict": "PASS",
                "evidence_summary": (
                    "Across all 454,275 previews in v3, partial_sentence is None (0 false completeness claims), "
                    "boundary_status is 'content_window_not_sentence_verified', and start_clipped, end_clipped, truncated "
                    "match independent character-offset checks against [baseline, content_end] with 0 mismatches. "
                    "All 267 units without preview (55 from v1 + 212 that had punctuation/placeholder-only previews in v1) "
                    "were verified to have content_start is None (zero alphanumeric characters outside markers/placeholders) and 0 anchors, "
                    "while preserving handles, byte spans, neighbor links, and open_context access."
                ),
                "concrete_examples": [
                    {
                        "case_id": "000777.txt",
                        "source_hash": "c599a3595b2ea24c55d41bf86ac2875c2ff868e7330e24d9c96e3ff9e43879ba",
                        "unit_id": "000777:c599a3595b2ea24c:14929-14976:20c8805023c2",
                        "handle": "p000023",
                        "raw_text": "[21]\r\n[...]\r\n[...]\r\n[...]\r\n[...]\r\n[...]\r\n[...].",
                        "v1_preview_text": "[...]\r\n[...]\r\n[...]\r\n[...]\r\n[...]\r\n[...].",
                        "v3_preview_refs": [],
                        "v3_preview_absence_reason": "no_meaningful_opening_or_anchor",
                        "reproduction_command": ".venv/Scripts/python.exe -m pipeline_v2.m2 open --repo-root . --bundle pipeline_v2/artifacts/m2_navigation_20261106_v3 --case-id 000777.txt --handle p000023"
                    }
                ]
            },
            {
                "criterion_id": "ADJUDICATION-6",
                "title": "Provenance, seal, tamper resistance, and non-preview invariance",
                "verdict": "PASS",
                "evidence_summary": (
                    "All 7,708 case sidecars, source_registry.json, summary.json, manifest.json, and seal.json in v3 verified against raw bytes, "
                    "M0 (m0_20261105_v2), M1 (m1_20261105_v2), and v1 (m2_navigation_20261105_v1). "
                    "Across all 7,708 cases: 216,946 unit anchors, 1,237 source anchors, 48,990 headings, and all 382,343 navigation rows "
                    "(excluding preview_refs and preview_absence_reason) are 100% identical between v1 and v3. "
                    "Isolated tamper tests confirmed that NavigationReader rejects raw byte tamper (even after resealing), "
                    "M1 structure tamper (even after resealing), and preview/anchor offset tamper (even after resealing)."
                )
            }
        ],
        "prior_v1_findings_resolution": [
            {
                "prior_finding_id": "M2-FINDING-001",
                "prior_title": "Systematic Premature Truncation of Opening Previews on Legal Abbreviations and Judge Names",
                "status_in_v3": "RESOLVED",
                "verification_note": "short_opening_le_30_with_more_text dropped from 33,441 -> 0; partial_sentence is None across all 454,275 previews."
            },
            {
                "prior_finding_id": "M2-FINDING-002",
                "prior_title": "Redundant Contained Preview Windows Crowding Out Subsequent Unit Anchors",
                "status_in_v3": "RESOLVED",
                "verification_note": "contained_preview_pairs dropped from 20,147 -> 0; units with >=2 anchors covering >=2 anchors rose from 23,933 -> 37,827."
            },
            {
                "prior_finding_id": "M2-FINDING-003",
                "prior_title": "Arbitrary Mid-Token and Mid-Placeholder Slicing in Anchor Previews",
                "status_in_v3": "RESOLVED",
                "verification_note": "word_clipped_raw dropped from 68,754 (v1) / 245 (v2) -> 0 (v3); tag_clipped_raw dropped from 3,367 (v1) / 9 (v2) -> 0 (v3)."
            },
            {
                "prior_finding_id": "M2-FINDING-004",
                "prior_title": "Opening Previews Consisting Only of Suppression Placeholders and Punctuation",
                "status_in_v3": "RESOLVED",
                "verification_note": "opening_starts_on_placeholder_punct_line dropped from 1,520 -> 0 (1,193 advanced to alphanumeric line; 327 had no alphanumeric text in unit)."
            },
            {
                "prior_finding_id": "M2-V2-CHECKPOINT-TAG-CLIP",
                "prior_title": "Intermediate v2 Tail Candidate Pre-Clip Breaking <FRAGMENT_SUPPRESSED> in 9 Cases and Words in 245 Previews",
                "status_in_v3": "RESOLVED",
                "verification_note": "Passing full original cue span (a, b) into tail _safe_window eliminated all 9 mid-tag clips and all 245 mid-word clips."
            }
        ],
        "documented_non_blocking_limitations": [
            {
                "limitation_id": "M2-LIMIT-001",
                "category": "snippet_cap_and_placeholder_density",
                "description": (
                    "Preview windows are bounded to 240 Unicode codepoints and at most 2 previews per unit. "
                    "In 6 units across the corpus (007777/u000001, 014803/u000001, 016528/u000001, 028057/p000045, 040347/u000001, 081901/u000001), "
                    "repeated <FRAGMENT_SUPPRESSED> tags inside the 235-238 char opening window leave 88-91 non-placeholder characters. "
                    "Similarly, quote cues longer than 240 chars are marked fully_visible=False, source_cue_fully_visible=False, visibility='partial', "
                    "and units with >2 anchors (or 2,370 units where a long cue's head and tail occupy both slots) cannot display every anchor inline in map."
                ),
                "mitigation": (
                    "Map explicitly exposes anchor_count, anchor_visibility, start_clipped, end_clipped, and truncated; "
                    "full unit anchors and source quote cues are retrievable via NavigationReader.anchors() / source_anchors() and raw text via open_context()."
                )
            },
            {
                "limitation_id": "M2-LIMIT-002",
                "category": "units_without_preview_by_design",
                "description": (
                    "267 navigation units have preview_refs=[] and preview_absence_reason='no_meaningful_opening_or_anchor' "
                    "because their raw text contains zero alphanumeric characters outside [N] markers and suppression placeholders "
                    "(e.g. '[2]', ':', '.....', '[21]\\r\\n[...]\\r\\n[...].') and zero anchors."
                ),
                "mitigation": "All 267 units retain handles, byte spans, neighbor links, and full raw expansion via NavigationReader.open_context()."
            },
            {
                "limitation_id": "M2-LIMIT-003",
                "category": "stage_boundary_and_upstream_uncertainty",
                "description": (
                    "M2 is a deterministic navigation and preview layer, not a semantic parser or chunker: "
                    "paragraph_role remains 'unknown' with uncertainties=['paragraph_ownership_unresolved'], "
                    "partial_sentence is None ('content_window_not_sentence_verified'), and readiness marks "
                    "token_counts='not_ready' and token_validated_chunks='not_ready'."
                ),
                "mitigation": "Preserved as explicit machine-readable flags so downstream stages and agents do not assume unverified semantics."
            }
        ],
        "prior_review_report_discrepancies_corrected": [
            {
                "discrepancy": "Old review report (m2_navigation_ag_review_v1) referenced non-existent class M2NavigationStore and method dedup_hits() / start_ord, end_ord.",
                "correction_in_this_review": "All scripts and reproduction commands in this review use the real NavigationReader API (map, open_context, anchors, source_anchors) and python -m pipeline_v2.m2 CLI."
            },
            {
                "discrepancy": "Old review report stated 7,720 sealed files in M2.",
                "correction_in_this_review": "Verified exact counts: seal.json contains 7,711 file entries (7,708 case sidecars + manifest.json + source_registry.json + summary.json), making 7,712 files on disk including seal.json."
            },
            {
                "discrepancy": "Old review report cited fabricated text 'Pinard, J. : The applicant seeks judicial review of a decision of a visa officer...' for 011922/p000005.",
                "correction_in_this_review": "Verified exact raw bytes 625-1316 of 011922.txt (sha256 ae50db46...): '[1] \\r\\n   \\r\\n Pinard, J. \\r\\n : On March 14, 2011, Luftar Hysa (the \"applicant\") filed the present appeal...'."
            }
        ]
    }
    (out_dir / "findings.json").write_text(json.dumps(findings_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    commands_payload = {
        "schema_version": "m2-preview-revision2-commands-and-results-v1",
        "paid_api_or_llm_calls": 0,
        "labels_or_test_data_accessed": False,
        "commands": [
            {
                "step_order": 1,
                "command": "& .venv/Scripts/python.exe -m pipeline_v2.m2 --help; & .venv/Scripts/python.exe -m unittest discover -s pipeline_v2/tests -v",
                "purpose": "Verify CLI entrypoint and run full M0/M1/M2 unit test suite",
                "exit_code": 0,
                "elapsed_seconds": 3.811,
                "status": "PASS",
                "summary": "CLI help displayed (build, validate, map, open, anchors, source-anchors); 56 unit tests passed in 3.811s."
            },
            {
                "step_order": 2,
                "command": "& .venv/Scripts/python.exe -m pipeline_v2.m2 validate --repo-root . --bundle pipeline_v2/artifacts/m2_navigation_20261106_v3",
                "purpose": "Run official M2 validator on target bundle m2_navigation_20261106_v3",
                "exit_code": 0,
                "elapsed_seconds": 394.295,
                "status": "PASS",
                "summary": "valid=True, 7,708 sources, 382,343 navigation units, 454,275 previews, 216,946 anchors, 1,237 source quote cues, 48,990 headings, 267 units without preview."
            },
            {
                "step_order": 3,
                "command": "& .venv/Scripts/python.exe pipeline_v2/reviews/m2_preview_revision2_ag_review_v1/scripts/tamper_and_boundary_tests.py",
                "purpose": "Run 1 of isolated tamper/drift/reseal, pagination, CLI, and overlong fallback tests",
                "exit_code": 0,
                "elapsed_seconds": 2.275,
                "status": "FAILED_ASSERTION_FIXED_IN_RETRY",
                "failure_and_retry_note": "Test 2 initially hardcoded 19 navigation units for 014101.txt whereas 014101.txt has 12 navigation units. Fixed Test 2 to compare paged unit_ids against the sidecar's actual navigation list."
            },
            {
                "step_order": 4,
                "command": "& .venv/Scripts/python.exe pipeline_v2/reviews/m2_preview_revision2_ag_review_v1/scripts/tamper_and_boundary_tests.py",
                "purpose": "Run 2 (after fixing Test 2 unit count check) of isolated tamper/drift/reseal, pagination, CLI, and overlong fallback tests",
                "exit_code": 0,
                "elapsed_seconds": 2.265,
                "status": "PASS",
                "summary": "5/5 tests passed (test_1_tamper_and_reseal_detection, test_2_navigation_reader_pagination_and_bounds, test_3_open_context_policies_and_intervening_headings, test_4_cli_subcommands, test_5_overlong_word_and_tag_fallback). Wrote tamper_and_boundary_results.json."
            },
            {
                "step_order": 5,
                "command": "& .venv/Scripts/python.exe pipeline_v2/reviews/m2_preview_revision2_ag_review_v1/scripts/lock_sample_and_extract.py",
                "purpose": "Run 1: Lock deterministic 40-case / 120-region sample (seed 20261106) and extract Step 1 map + Step 2 open_context views",
                "exit_code": 0,
                "elapsed_seconds": 49.311,
                "status": "PASS",
                "summary": "Locked 20 uniform random + 20 risk-stratified cases (0 overlap with M0 discovery/holdout or separate regressions) and extracted 120 regions."
            },
            {
                "step_order": 6,
                "command": "& .venv/Scripts/python.exe pipeline_v2/reviews/m2_preview_revision2_ag_review_v1/scripts/independent_corpus_audit.py",
                "purpose": "Run 1 of independent full-corpus audit across 7,708 cases",
                "exit_code": 1,
                "elapsed_seconds": 1.12,
                "status": "FAILED_AND_RETRIED",
                "failure_and_retry_note": "Failed with FileNotFoundError on m0_20261105_v2/source_registry.json because M0 stores its source registry in inventory.json. Updated script to read m0_20261105_v2/inventory.json and re-ran."
            },
            {
                "step_order": 7,
                "command": "& .venv/Scripts/python.exe pipeline_v2/reviews/m2_preview_revision2_ag_review_v1/scripts/independent_corpus_audit.py",
                "purpose": "Run 2 of independent full-corpus audit across 7,708 cases comparing M0, M1, v1, v2, v3, and raw bytes",
                "exit_code": 0,
                "elapsed_seconds": 144.602,
                "status": "PASS",
                "summary": "error_count=0 across 7,708 cases, 382,343 units, 454,275 previews. Wrote machine_audit_results.json."
            },
            {
                "step_order": 8,
                "command": "& .venv/Scripts/python.exe pipeline_v2/reviews/m2_preview_revision2_ag_review_v1/scripts/lock_sample_and_extract.py; & .venv/Scripts/python.exe pipeline_v2/reviews/m2_preview_revision2_ag_review_v1/scripts/adjudicate_regions.py",
                "purpose": "Re-extract 120 sampled + 17 separate regression regions and run adjudication script (Run 1)",
                "exit_code": 1,
                "elapsed_seconds": 44.1,
                "status": "FAILED_AND_RETRIED",
                "failure_and_retry_note": "lock_sample_and_extract.py succeeded (43.82s), but adjudicate_regions.py raised KeyError: 'title' on item['sections'] because heading objects use key 'text'. Updated s['title'] -> s['text'] and re-ran adjudicate_regions.py."
            },
            {
                "step_order": 9,
                "command": "& .venv/Scripts/python.exe pipeline_v2/reviews/m2_preview_revision2_ag_review_v1/scripts/adjudicate_regions.py",
                "purpose": "Run 2 of region adjudication script across 120 sampled regions + 17 separate regression regions",
                "exit_code": 0,
                "elapsed_seconds": 0.03,
                "status": "PASS",
                "summary": "120/120 sampled regions PASS integrity (113 PASS usefulness, 7 NOT_APPLICABLE_NO_PREVIEW); 17/17 regression regions PASS integrity and usefulness. Wrote reviewed_regions.json."
            }
        ]
    }
    (out_dir / "commands_and_results.json").write_text(json.dumps(commands_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Wrote findings.json and commands_and_results.json successfully.")


if __name__ == "__main__":
    main()
