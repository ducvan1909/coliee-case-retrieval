"""Independent contracts for the sequential local region-priority variants.

These tests intentionally treat feature tiers and context as scheduling hints;
they do not assert legal correctness or AU acceptance.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from knowledge_base.pipeline_v1.region_priority_variants.context import (
    _ownership,
    expand_context,
)
from knowledge_base.pipeline_v1.region_priority_variants.scheduler import (
    priority_order,
    rank_reason,
    schedule_order,
)
from knowledge_base.pipeline_v1.region_priority_offline.features import PATTERNS


def _row(region_id, case_id, start, text, *, tier=0, lane_scores=None,
         counts=None, context=None, source_hash="fixture-source",
         block_type="numbered_paragraph"):
    counts = counts or {}
    lanes = lane_scores or {}
    return {
        "region_id": region_id,
        "case_id": case_id,
        "source_hash": source_hash,
        "block_type": block_type,
        "target": {"start_char": start, "end_char": start + len(text)},
        "features": {
            "counts": {k: 0 for k in (
                "review", "duty", "rights", "standard", "qualification",
                "fact", "consequence", "rationale", "citation", "reporting",
            )} | counts,
            "lane_scores": {k: 0 for k in (
                "doctrine", "application", "reported_authority", "context",
            )} | lanes,
            "open_quote": False,
        },
        "packet": {
            "case_id": case_id,
            "source_hash": source_hash,
            "target": {
                "start_char": start, "end_char": start + len(text),
                "text": text, "role": "TARGET", "block_id": region_id,
            },
            "context": copy.deepcopy(context or []),
        },
        "serialized_utf8_bytes": len(text.encode("utf-8")) + 100,
    }


def _inventory(rows, source, *, atoms=()):
    by_case = {}
    for row in rows:
        by_case.setdefault(row["case_id"], []).append(row)
    return {
        "regions": rows,
        "sources": {cid: source for cid in by_case},
        "cases": [{
            "case_id": cid,
            "atom_span_inventory": [a for a in atoms if a["case_id"] == cid],
        } for cid in by_case],
    }


class PriorityOrderTests(unittest.TestCase):
    def test_global_tie_break_is_cue_then_case_and_source_offsets(self):
        # Same tier and cue score: the stable key must be case/offset, not the
        # incoming inventory order. KOS-like metadata is deliberately noisy.
        rows = [
            _row("z", "099980", 30, "z", lane_scores={"doctrine": 2}),
            _row("b", "013009", 20, "b", lane_scores={"doctrine": 2},
                 counts={"citation": 1},),
            _row("a2", "013009", 12, "a2", lane_scores={"doctrine": 2}),
            _row("a1", "013009", 5, "a1", lane_scores={"doctrine": 2}),
        ]
        rows[0]["kos_kind"] = "holding"
        rows[1]["issue_ids"] = ["must-not-rank"]
        rows[2]["claim"] = "must-not-rank"
        rows[3]["gold_label"] = "must-not-rank"
        inventory = {"regions": rows}

        self.assertEqual(priority_order(inventory), ["b", "a1", "a2", "z"])
        self.assertEqual(priority_order({"regions": list(reversed(rows))}),
                         ["b", "a1", "a2", "z"])

    def test_tiers_follow_frozen_thresholds_without_semantic_claims(self):
        tier3 = _row("review", "013009", 0, "x", counts={"review": 1})
        tier2 = _row("app", "013009", 1, "x", lane_scores={"application": 3})
        tier1 = _row("weak", "013009", 2, "x", lane_scores={"context": 1})
        tier0 = _row("none", "013009", 3, "x")
        self.assertEqual([rank_reason(r)["tier"] for r in (tier3, tier2, tier1, tier0)],
                         [3, 2, 1, 0])
        self.assertEqual(rank_reason(tier3)["reasons"], ["review"])

    def test_fixed_absolute_budget_scans_same_full_order_and_keeps_residual(self):
        rows = [
            _row("large", "013009", 0, "x" * 50),
            _row("small", "013009", 100, "y"),
        ]
        order = ["large", "small"]
        # Budget excludes the first packet but still permits the next fitting
        # packet; it never changes the frozen full order.
        result = schedule_order({"regions": rows}, order, budget=30)
        self.assertEqual([r["region_id"] for r in result["reads"]], ["small"])
        self.assertEqual([r["region_id"] for r in result["unknown_residual"]], ["large"])
        self.assertEqual(result["unknown_residual"][0]["status"], "not_assessed")
        self.assertEqual([r["full_order_rank"] for r in result["reads"]], [1])

    def test_preview_and_name_surface_edits_do_not_change_feature_priority(self):
        from knowledge_base.pipeline_v1.region_priority_offline.features import extract_features

        original = "Judge Alice Morgan held that the applicant is liable under section 12."
        renamed = "Judge Bruno Rivera held that the applicant is liable under section 12."
        first_features, renamed_features = extract_features(original), extract_features(renamed)
        self.assertEqual(first_features, renamed_features)
        a = _row("a", "013009", 0, original,
                 counts=first_features["counts"],
                 lane_scores=first_features["lane_scores"])
        b = copy.deepcopy(a)
        b["features"] = {
            "counts": renamed_features["counts"],
            "lane_scores": renamed_features["lane_scores"],
        }
        b["preview_views"] = [{"text": original[:20]}, {"text": original[:20]}]
        self.assertEqual(priority_order([a]), priority_order([b]))

    def test_similar_negation_and_exception_regions_remain_separate_ids(self):
        rows = [
            _row("affirmative", "013009", 0, "liable under section 12",
                 lane_scores={"doctrine": 2}),
            _row("qualified", "013009", 100, "not liable under section 12 unless",
                 lane_scores={"doctrine": 2}),
        ]
        full_order = priority_order(rows)
        schedule = schedule_order({"regions": rows}, full_order)
        self.assertEqual(set(full_order), {"affirmative", "qualified"})
        self.assertEqual({r["region_id"] for r in schedule["reads"]},
                         {"affirmative", "qualified"})

    def test_context_cost_can_reduce_selected_set_without_changing_locked_order(self):
        baseline = [
            _row("a", "013009", 0, "a"),
            _row("b", "013009", 10, "b"),
            _row("c", "013009", 20, "c"),
        ]
        locked = priority_order(baseline)
        expanded = copy.deepcopy(baseline)
        for row in expanded:
            row["serialized_utf8_bytes"] += 200
        budget = 100
        before = schedule_order({"regions": baseline}, locked, budget=budget)
        after = schedule_order({"regions": expanded}, locked, budget=budget)
        self.assertEqual(locked, priority_order(expanded))
        self.assertLess(len(after["reads"]), len(before["reads"]))
        self.assertEqual([r["region_id"] for r in after["reads"]], [locked[0]])

    def test_supplied_or_snapshot_order_must_be_a_complete_unique_identity(self):
        rows = [_row("a", "013009", 0, "a"), _row("b", "013009", 10, "b")]
        for invalid in (["a"], ["a", "a"], ["a", "missing"]):
            with self.subTest(order=invalid), self.assertRaises(ValueError):
                schedule_order({"regions": rows}, invalid)


class OwnershipAndContextTests(unittest.TestCase):
    def test_external_quote_reference_is_unresolved_but_current_narration_is_owned(self):
        quoted = 'The Court quoted Smith: "paragraph 5 of these reasons".'
        match = re.search(PATTERNS["paragraph_reference"], quoted, re.I)
        self.assertIsNotNone(match)
        self.assertEqual(_ownership(quoted, match),
                         (False, "unresolved_external_or_quoted_ownership"))

        owned = "Section 27 has been set out earlier in paragraph 5 of these reasons."
        match = re.search(PATTERNS["paragraph_reference"], owned, re.I)
        self.assertIsNotNone(match)
        self.assertEqual(_ownership(owned, match),
                         (True, "explicit_current_narration"))

    def test_external_citation_and_other_decision_scopes_do_not_resolve_local_number(self):
        examples = (
            "Smith (2001) says paragraph 5 of these reasons applies.",
            "In that decision, paragraph 5 of these reasons explains the rule.",
            "The Court quoted Smith: 'paragraph 5 of these reasons'.",
        )
        for text in examples:
            with self.subTest(text=text):
                match = re.search(PATTERNS["paragraph_reference"], text, re.I)
                self.assertIsNotNone(match)
                owned, _ = _ownership(text, match)
                self.assertFalse(owned)

    def test_owned_reference_in_supplied_context_can_open_whole_same_case_block(self):
        p5 = "[5] The statutory test requires reasonable grounds before withholding the material."
        p20 = "[20] Section 27 has been set out earlier in paragraph 5 of these reasons."
        p21 = "[21] The decision-maker withheld the material under subsection 27(3)."
        source = p5 + "\n" + p20 + "\n" + p21
        starts = {"p5": 0, "p20": len(p5) + 1, "p21": len(p5) + len(p20) + 2}
        span = lambda key, text: {"start_char": starts[key], "end_char": starts[key] + len(text)}

        rows = [
            _row("p5", "045155", starts["p5"], p5),
            _row("p20", "045155", starts["p20"], p20),
            _row("p21", "045155", starts["p21"], p21,
                 counts={"qualification": 1}, context=[{
                     **span("p20", p20), "text": p20, "role": "CONTEXT",
                     "block_id": "p20", "reason": "adjacent_atom",
                     "reasons": ["adjacent_atom"], "atom_ids": [],
                 }]),
        ]
        inventory = _inventory(rows, source)
        expanded = expand_context(inventory)
        target = next(r for r in expanded["regions"] if r["region_id"] == "p21")

        self.assertEqual(target["target"], rows[2]["target"])
        self.assertEqual(target["features"], rows[2]["features"])
        self.assertEqual(target["context_audit"]["reference_hops"], 1)
        ref = next(r for r in target["context_audit"]["input_reference_hints"]
                   if r["paragraph_number"] == "5")
        self.assertTrue(ref["ownership_confirmed_local"])
        self.assertEqual(ref["matching_block_ids"], ["p5"])
        self.assertEqual(ref["resolution"], "resolved")
        context = target["packet"]["context"]
        self.assertTrue(any(c["text"] == p5 and c["block_ids"] == ["p5"]
                            for c in context))
        self.assertFalse(any(c["start_char"] < target["target"]["end_char"]
                             and c["end_char"] > target["target"]["start_char"]
                             for c in context))

    def test_external_quoted_reference_never_adds_same_number_local_block(self):
        p5 = "[5] Local paragraph with unrelated content."
        target_text = '[21] The Court quoted Smith: "paragraph 5 of these reasons".'
        source = p5 + "\n" + target_text
        start = len(p5) + 1
        rows = [
            _row("p5", "045155", 0, p5),
            _row("p21", "045155", start, target_text,
                 counts={"reporting": 1}),
        ]
        expanded = expand_context(_inventory(rows, source))
        row = next(r for r in expanded["regions"] if r["region_id"] == "p21")
        ref = next(r for r in row["context_audit"]["input_reference_hints"]
                   if r["paragraph_number"] == "5")
        self.assertFalse(ref["ownership_confirmed_local"])
        self.assertEqual(ref["resolution"], "unresolved")
        self.assertNotIn("p5", [bid for c in row["packet"]["context"]
                                 for bid in c.get("block_ids", [])])

    def test_citation_year_marker_on_unnumbered_block_is_not_a_paragraph_address(self):
        # Some source blocks begin with a bracketed citation year. It must not
        # satisfy a current-reasons paragraph reference by number coincidence.
        citation_header = "[2006] FCJ No. 17 (QL), reported decision metadata."
        target_text = "[21] The test was set out earlier in paragraph 2006 of these reasons."
        source = citation_header + "\n" + target_text
        start = len(citation_header) + 1
        rows = [
            _row("citation-header", "045155", 0, citation_header,
                 block_type="unnumbered_paragraph"),
            _row("p21", "045155", start, target_text),
        ]
        expanded = expand_context(_inventory(rows, source))
        row = next(r for r in expanded["regions"] if r["region_id"] == "p21")
        ref = next(r for r in row["context_audit"]["input_reference_hints"]
                   if r["paragraph_number"] == "2006")
        self.assertFalse(ref["ownership_confirmed_local"])
        self.assertEqual(ref["resolution"], "unresolved")
        self.assertEqual(ref["ownership_reason"], "missing_or_ambiguous_local_marker")
        self.assertNotIn("citation-header", [bid for c in row["packet"]["context"]
                                             for bid in c.get("block_ids", [])])

    def test_oversized_dependency_is_reported_whole_as_unknown_residual(self):
        huge = "[5] " + ("condition evidence " * 400)
        target_text = "[21] This rule was set out earlier in paragraph 5 of these reasons."
        source = huge + "\n" + target_text
        start = len(huge) + 1
        rows = [
            _row("p5", "045155", 0, huge),
            _row("p21", "045155", start, target_text),
        ]
        expanded = expand_context(_inventory(rows, source))
        row = next(r for r in expanded["regions"] if r["region_id"] == "p21")
        residual = row["context_audit"]["context_cap_residual"]
        self.assertTrue(any(item["block_ids"] == ["p5"]
                            and item["status"] == "unknown"
                            and item["reason"] == "whole_context_cap_no_truncation"
                            for item in residual))
        self.assertFalse(any(c["text"] == huge for c in row["packet"]["context"]))
        self.assertFalse(any("condition evidence" in c["text"]
                             for c in row["packet"]["context"]))

    def test_context_union_excludes_target_and_respects_char_and_interval_caps(self):
        # Oversized disconnected baseline contexts must remain explicitly
        # unassessed; they cannot be silently clipped into a passing packet.
        target_text = "[1] target"
        source = "x" * 20000
        target_start = 10000
        contexts = [
            {"start_char": i * 1400, "end_char": i * 1400 + 700,
             "text": source[i * 1400:i * 1400 + 700], "role": "CONTEXT",
             "reason": f"fixture-{i}", "reasons": [f"fixture-{i}"],
             "atom_ids": [], "block_ids": []}
            for i in range(13)
        ]
        # Make one region whose source coordinates and text are consistent.
        row = _row("r", "013009", target_start, target_text, context=contexts)
        row["target"] = {"start_char": target_start, "end_char": target_start + len(target_text)}
        row["packet"]["target"].update(row["target"])
        source = source[:target_start] + target_text + source[target_start + len(target_text):]
        expanded = expand_context(_inventory([row], source))["regions"][0]
        context = expanded["packet"]["context"]
        residual = expanded["context_audit"]["context_cap_residual"]
        self.assertLessEqual(len(context), 12)
        self.assertLessEqual(sum(len(c["text"]) for c in context), 6000)
        self.assertTrue(residual)
        self.assertTrue(all(x["status"] == "unknown" for x in residual))
        for c in context:
            self.assertFalse(c["start_char"] < row["target"]["end_char"]
                             and c["end_char"] > row["target"]["start_char"])


class SequentialCliAndArtifactTests(unittest.TestCase):
    """Fresh, sequential CLI run; no manually prepared report is consumed."""

    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.tester_root = (cls.root / "knowledge_base/pipeline_v1/outputs/"
                           "region_priority_variants_20261013/tester")
        cls.tester_root.mkdir(parents=True, exist_ok=True)
        run_id = dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        cls.run_root = cls.tester_root / ("fresh_cli_" + run_id)
        cls.order_root = cls.run_root / "order"
        cls.context_root = cls.run_root / "context"
        cls.run_root.mkdir(parents=True)

        cls.order_command = [
            sys.executable, "-m", "knowledge_base.pipeline_v1.region_priority_variants",
            "--stage", "order", "--output-root", str(cls.order_root),
        ]
        order = subprocess.run(cls.order_command, cwd=cls.root, capture_output=True,
                               text=True, encoding="utf-8", timeout=180)
        if order.returncode:
            raise RuntimeError("fresh Stage 1 CLI failed\nstdout:\n" + order.stdout +
                               "\nstderr:\n" + order.stderr)
        # Stage 2 is deliberately not invoked until the complete, persisted
        # Stage 1 report and lock are visible on disk.
        cls.order_report_path = cls.order_root / "report.json"
        cls.order_lock_path = cls.order_root / "frozen_snapshot.json"
        if not cls.order_report_path.is_file() or not cls.order_lock_path.is_file():
            raise RuntimeError("Stage 1 did not materialize its report and lock before Stage 2")

        cls.context_command = [
            sys.executable, "-m", "knowledge_base.pipeline_v1.region_priority_variants",
            "--stage", "context", "--order-report", str(cls.order_report_path),
            "--output-root", str(cls.context_root),
        ]
        context = subprocess.run(cls.context_command, cwd=cls.root, capture_output=True,
                                 text=True, encoding="utf-8", timeout=180)
        if context.returncode:
            raise RuntimeError("fresh Stage 2 CLI failed\nstdout:\n" + context.stdout +
                               "\nstderr:\n" + context.stderr)
        cls.cli_stdout = {"order": order.stdout, "context": context.stdout}
        cls.order_report = json.loads(cls.order_report_path.read_text(encoding="utf-8-sig"))
        cls.context_report = json.loads((cls.context_root / "report.json").read_text(encoding="utf-8-sig"))
        cls.order_inventory = json.loads((cls.order_root / "inventory.json").read_text(encoding="utf-8-sig"))
        cls.context_inventory = json.loads((cls.context_root / "inventory.json").read_text(encoding="utf-8-sig"))
        cls.order_selection = json.loads((cls.order_root / "selection_snapshot.json").read_text(encoding="utf-8-sig"))
        cls.context_selection = json.loads((cls.context_root / "selection_snapshot.json").read_text(encoding="utf-8-sig"))

    def test_cli_runs_in_order_and_reports_only_offline_protocol(self):
        self.assertIn("stage=order", self.cli_stdout["order"])
        self.assertIn("stage=context", self.cli_stdout["context"])
        for report in (self.order_report, self.context_report):
            self.assertEqual(report["protocol_status"], "pass")
            self.assertTrue(all(report["protocol_checks"].values()))
            self.assertEqual(report["semantic_quality"], "not_assessed")
            self.assertEqual(report["qualified_evidence_quality"], "not_assessed")
            self.assertEqual(report["cost"]["network_requests"], 0)
            self.assertEqual(report["cost"]["inference_requests"], 0)

    def test_stage1_matches_exact_baseline_inventory_packets_features_and_cost(self):
        baseline_root = self.root / "knowledge_base/pipeline_v1/outputs/region_priority_offline_20261013"
        prior_inventory = json.loads((baseline_root / "inventory.json").read_text(encoding="utf-8-sig"))
        rows = self.order_inventory["regions"]
        self.assertEqual(len(rows), 431)
        self.assertEqual(self.order_inventory, prior_inventory)
        self.assertEqual(self.order_report["inventory_summary"]["atom_count"], 1240)
        self.assertEqual(self.order_report["inventory_summary"]["source_chars"], 206853)
        prior_cost = {r["region_id"]: r["serialized_utf8_bytes"] for r in prior_inventory["regions"]}
        self.assertEqual({r["region_id"]: r["serialized_utf8_bytes"] for r in rows}, prior_cost)
        ordered = self.order_report["lock"]["full_ordered_ids"]
        self.assertEqual(len(ordered), 431)
        self.assertEqual(len(set(ordered)), 431)
        self.assertEqual(self.order_report["lock"]["order_sha256"],
                         self.context_report["lock"]["order_sha256"])
        self.assertEqual(self.context_report["order_report_binding"]["sha256"],
                         hashlib.sha256(self.order_report_path.read_bytes()).hexdigest())

    def test_stage2_keeps_full_order_features_and_targets_while_context_cost_changes(self):
        before = {r["region_id"]: r for r in self.order_inventory["regions"]}
        after = {r["region_id"]: r for r in self.context_inventory["regions"]}
        self.assertEqual(set(before), set(after))
        self.assertEqual(self.order_report["lock"]["full_ordered_ids"],
                         self.context_report["lock"]["full_ordered_ids"])
        self.assertEqual(self.context_report["schedules"]["global_priority"]["reads"],
                         self.order_report["schedules"]["global_priority"]["reads"])
        for region_id in before:
            self.assertEqual(before[region_id]["target"], after[region_id]["target"], region_id)
            self.assertEqual(before[region_id]["features"], after[region_id]["features"], region_id)
            self.assertEqual(before[region_id]["packet"]["target"], after[region_id]["packet"]["target"], region_id)
            context = after[region_id]["packet"]["context"]
            self.assertLessEqual(len(context), 12, region_id)
            self.assertLessEqual(sum(c["end_char"] - c["start_char"] for c in context), 6000, region_id)
            target = after[region_id]["target"]
            self.assertTrue(all(not (c["start_char"] < target["end_char"]
                                     and c["end_char"] > target["start_char"])
                                for c in context), region_id)

    def test_every_arm_and_divisor_uses_baseline_absolute_budgets(self):
        expected_fractions = {0.1, 0.25, 0.5, 0.75, 1.0}
        for selection in self.order_selection["selections"] + self.context_selection["selections"]:
            self.assertEqual(selection["baseline_budget_denominator"], 247339)
            self.assertEqual(selection["absolute_budget"],
                             int(247339 * selection["fraction"]))
            self.assertIn(selection["fraction"], expected_fractions)
            self.assertIn(selection["divisor"], (3, 4, 5))
        self.assertEqual({s["divisor"] for s in self.context_selection["selections"]}, {3, 4, 5})
        self.assertEqual({s["fraction"] for s in self.context_selection["selections"]}, expected_fractions)
        # The locked order is unchanged, while context packet cost may admit a
        # different target set at the same absolute budget.
        differences = self.context_report["selected_set_cost_consequences"]
        self.assertEqual(len(differences), 15)
        self.assertTrue(all(d["shared_full_order"] for d in differences))
        self.assertTrue(all(d["cause"].startswith("cost-only") for d in differences))

    def test_matched_target_cost_is_recomputed_on_identical_region_ids(self):
        before = {r["region_id"]: r for r in self.order_inventory["regions"]}
        after = {r["region_id"]: r for r in self.context_inventory["regions"]}
        comparisons = self.context_report["matched_order_context_comparisons"]
        self.assertEqual(len(comparisons), 30)
        for comparison in comparisons:
            ids = comparison["selected_target_ids"]
            self.assertEqual(len(ids), len(set(ids)))
            self.assertTrue(set(ids) <= set(before) and set(ids) <= set(after))
            divisor = comparison["divisor"]
            original_bytes = sum(before[rid]["serialized_utf8_bytes"] for rid in ids)
            changed_bytes = sum(after[rid]["serialized_utf8_bytes"] for rid in ids)
            original_tokens = sum((before[rid]["serialized_utf8_bytes"] + divisor - 1) // divisor
                                  for rid in ids)
            changed_tokens = sum((after[rid]["serialized_utf8_bytes"] + divisor - 1) // divisor
                                 for rid in ids)
            self.assertEqual(comparison["original"]["serialized_bytes"], original_bytes)
            self.assertEqual(comparison["new_context"]["serialized_bytes"], changed_bytes)
            self.assertEqual(comparison["original"]["estimated_tokens"], original_tokens)
            self.assertEqual(comparison["new_context"]["estimated_tokens"], changed_tokens)
            self.assertEqual(comparison["serialized_byte_delta"], changed_bytes - original_bytes)
            self.assertEqual(comparison["estimated_token_delta"], changed_tokens - original_tokens)

    def test_tampered_stage1_snapshot_is_rejected_by_stage2_cli(self):
        tampered = self.run_root / "tampered_stage1"
        tampered.mkdir()
        for name in ("report.json", "frozen_snapshot.json"):
            shutil.copy2(self.order_root / name, tampered / name)
        frozen_path = tampered / "frozen_snapshot.json"
        frozen = json.loads(frozen_path.read_text(encoding="utf-8-sig"))
        frozen["full_ordered_ids"][0], frozen["full_ordered_ids"][1] = (
            frozen["full_ordered_ids"][1], frozen["full_ordered_ids"][0])
        frozen_path.write_text(json.dumps(frozen, ensure_ascii=False, indent=2), encoding="utf-8")
        output = self.run_root / "tampered_context_must_not_exist"
        command = [
            sys.executable, "-m", "knowledge_base.pipeline_v1.region_priority_variants",
            "--stage", "context", "--order-report", str(tampered / "report.json"),
            "--output-root", str(output),
        ]
        rejected = subprocess.run(command, cwd=self.root, capture_output=True, text=True,
                                  encoding="utf-8", timeout=180)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("order/input/target/features/policy/code identity lock differs",
                      rejected.stderr)
        self.assertFalse(output.exists())

    def test_real_probe_packets_record_text_delivery_and_keep_remote_s27_unknown(self):
        au = {item["kos_id"]: item for item in self.context_report["au_audit"]}
        expected = {
            "au-045155-classification-reasons-s27": "authorized by the Commissioner or his delegate",
            "au-045155-policy-reasons-exhaust": "However, there will be circumstances in which the internal remedies are not adequate",
            "au-045155-exhaust-grievance-general": "There are exceptions to this general rule",
            "au-099980-right-to-make-submissions": "appointment of a person is at issue (section 72)",
        }
        observed = {}
        for kos_id, tail in expected.items():
            row = au[kos_id]
            self.assertIn(row["alignment"]["status"], ("exact", "whitespace_normalized"))
            first = row["arms"]["dependency_context"]["first_target"]
            self.assertIsNotNone(first, kos_id)
            packet = next(p for p in row["arms"]["dependency_context"]["raw_context_packets"]
                          if p["region_id"] == first["region_id"])
            target_text = packet["target"]["text"]
            context_text = "\n".join(c["text"] for c in packet["context"])
            observed[kos_id] = {
                "first_target_region": first["region_id"],
                "tail_in_target": tail in target_text,
                "tail_in_context": tail in context_text,
            }
            self.assertTrue(tail in target_text or tail in context_text, kos_id)

        s27 = au["au-045155-classification-reasons-s27"]
        first = s27["arms"]["dependency_context"]["first_target"]
        packet = next(p for p in s27["arms"]["dependency_context"]["raw_context_packets"]
                      if p["region_id"] == first["region_id"])
        opened = packet["target"]["text"] + "\n" + "\n".join(c["text"] for c in packet["context"])
        # This is a recorded open dependency probe. Presence in a packet is
        # delivery evidence only; absence stays unresolved and never becomes a
        # semantic pass. Include the [20] -> [5] context chain as a separate
        # packet observation because an adjacent packet's context is not model
        # memory for the [21] target request.
        observed["s27_remote_reasonable_grounds"] = {
            "available_in_first_target_packet": "reasonable grounds" in opened,
            "status_if_absent": "unresolved",
        }
        self.assertEqual(self.context_report["semantic_quality"], "not_assessed")
        self.assertEqual(self.context_report["qualified_evidence_quality"], "not_assessed")
        self.assertEqual(len(observed), 5)

    def test_kos_diagnostics_do_not_enter_selector_snapshot(self):
        # Selector ordering is computed over the source inventory. Extra KOS
        # labels and Issue/Claim fields cannot alter the API's rank result.
        from knowledge_base.pipeline_v1.region_priority_variants.scheduler import priority_order

        rows = self.order_inventory["regions"][:30]
        clean = {"regions": copy.deepcopy(rows)}
        noisy = {"regions": copy.deepcopy(rows)}
        for i, row in enumerate(noisy["regions"]):
            row.update(kind="holding", issue_ids=[f"issue-{i}"],
                       claim="diagnostic-only", evidence="diagnostic-only",
                       query_role="query", gold_link=True)
        self.assertEqual(priority_order(clean), priority_order(noisy))


if __name__ == "__main__":
    unittest.main()
