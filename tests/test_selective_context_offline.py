"""Independent synthetic contracts for selective context routing.

These fixtures exercise lexical delivery and request accounting only. They do
not assert legal dependency, AU correctness, or model behavior. The suite is
written against the frozen policy API; CLI/core tests are added after handoff.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from knowledge_base.pipeline_v1.region_priority_variants.scheduler import priority_order
from knowledge_base.pipeline_v1.selective_context_offline.policy import (
    POLICY,
    expand_context,
    request_cost,
    source_audit,
)
from knowledge_base.pipeline_v1.selective_context_offline.core import (
    DEFAULT_BASELINE,
    DEFAULT_ORDER_REPORT,
    schedule_selective,
)


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _inventory(block_specs, *, baseline_context=None, case_id="FIXTURE"):
    """Build a source-consistent inventory using the variants test shape.

    block_specs is [(region_id, text[, block_type])]. Baseline context maps a
    region ID to region IDs whose complete source spans are already delivered.
    """
    baseline_context = baseline_context or {}
    source_parts, spans, cursor = [], {}, 0
    for spec in block_specs:
        region_id, text = spec[0], spec[1]
        block_type = spec[2] if len(spec) > 2 else "numbered_paragraph"
        if source_parts:
            source_parts.append("\n")
            cursor += 1
        start, end = cursor, cursor + len(text)
        spans[region_id] = (start, end, text, block_type)
        source_parts.append(text)
        cursor = end
    source = "".join(source_parts)
    source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
    rows = []
    for region_id, text, *rest in block_specs:
        start, end, _, block_type = spans[region_id]
        target = {
            "start_char": start, "end_char": end, "text": text,
            "role": "TARGET", "block_id": region_id,
        }
        contexts = []
        for context_id in baseline_context.get(region_id, []):
            cstart, cend, ctext, _ = spans[context_id]
            contexts.append({
                "start_char": cstart, "end_char": cend, "text": ctext,
                "role": "CONTEXT", "block_id": context_id,
                "block_ids": [context_id], "atom_ids": [],
                "reason": "fixture_baseline", "reasons": ["fixture_baseline"],
            })
        packet = {
            "scaffold": {"prompt": "FIXTURE PROMPT repeated per request"},
            "case_id": case_id, "region_id": region_id,
            "source_hash": source_hash, "target": target, "context": contexts,
        }
        payload = _canonical(packet)
        rows.append({
            "region_id": region_id, "case_id": case_id,
            "source_hash": source_hash, "block_type": block_type,
            "target": {"start_char": start, "end_char": end},
            "features": {
                "counts": {key: 0 for key in (
                    "review", "duty", "rights", "standard", "qualification",
                    "fact", "consequence", "rationale", "citation", "reporting",
                )},
                "lane_scores": {key: 0 for key in (
                    "doctrine", "application", "reported_authority", "context",
                )},
                "open_quote": False,
            },
            "packet": packet,
            "serialized_payload": payload,
            "serialized_utf8_bytes": len(payload.encode("utf-8")),
            "serialized_chars": len(payload),
        })
    return {
        "version": "synthetic-selective-context-fixture-v1",
        "regions": rows,
        "sources": {case_id: source},
        "cases": [{"case_id": case_id, "atom_span_inventory": []}],
    }


def _row(inventory, region_id):
    return next(row for row in inventory["regions"] if row["region_id"] == region_id)


def _context_block_ids(row):
    return {block_id for item in row["packet"]["context"]
            for block_id in item.get("block_ids", [])}


class SelectiveContextRoutingTests(unittest.TestCase):
    def test_cue_without_owned_reference_is_candidate_but_packet_is_byte_identical(self):
        inventory = _inventory([
            ("before", "[19] A preceding paragraph with no address."),
            ("target", "[20] This rule is subject only to the written statute."),
            ("after", "[21] A neighboring paragraph without a local reference."),
            ("distant", "[22] A distant paragraph is unrelated to this cue."),
            ("p5", "[5] Required block must not be reached from a distant cue."),
        ])
        original = _row(inventory, "target")
        expanded = expand_context(inventory)
        result = _row(expanded, "target")
        audit = result["context_audit"]

        self.assertTrue(audit["qualification_dependency_cue"])
        self.assertEqual(audit["neighbor_block_ids_scanned"], ["before", "after"])
        self.assertTrue(audit["trigger_candidate"])
        self.assertFalse(audit["opened_additional_context"])
        self.assertFalse(audit["packet_changed"])
        self.assertEqual(result["serialized_payload"], original["serialized_payload"])
        self.assertEqual(result["serialized_utf8_bytes"], original["serialized_utf8_bytes"])
        self.assertEqual(result["packet"], original["packet"])
        self.assertEqual(_context_block_ids(result), set())

        counts = source_audit(expanded)["counts"]
        self.assertEqual(counts["qualification_dependency_cue"], 1)
        self.assertEqual(counts["packet_changed"], 0)
        no_resend = request_cost(original, result, mode="two_step")
        self.assertEqual(no_resend["hypothetical_requests"], 1)
        self.assertEqual(no_resend["hypothetical_second_requests"], 0)

    def test_owned_reference_in_initial_target_adds_complete_missing_block(self):
        inventory = _inventory([
            ("target", "[21] This point was set out earlier in paragraph 5 of these reasons."),
            ("middle", "[22] An unrelated source paragraph."),
            ("p5", "[5] The complete referenced paragraph, including its condition."),
        ])
        expanded = expand_context(inventory)
        row = _row(expanded, "target")
        audit_ref = row["context_audit"]["input_reference_hints"][0]
        self.assertTrue(audit_ref["ownership_confirmed_local"])
        self.assertEqual(audit_ref["admission"], "added_whole_bundle")
        self.assertEqual(audit_ref["resolution"], "resolved")
        self.assertEqual(_context_block_ids(row), {"p5"})
        p5 = _row(inventory, "p5")["packet"]["target"]
        delivered = next(c for c in row["packet"]["context"] if "p5" in c["block_ids"])
        self.assertEqual((delivered["start_char"], delivered["end_char"]),
                         (p5["start_char"], p5["end_char"]))
        self.assertEqual(delivered["text"], p5["text"])

    def test_cue_opens_only_adjacent_owned_bridge_and_its_missing_reference(self):
        inventory = _inventory([
            ("far_before", "[17] Distant paragraph 8 of these reasons."),
            ("bridge", "[19] The rule was set out earlier in paragraph 5 of these reasons."),
            ("target", "[20] The decision is subject to the statutory condition."),
            ("p5", "[5] Full condition block with its limiting language."),
            ("far_after", "[22] Distant paragraph 8 of these reasons."),
            ("p8", "[8] Must not be reached through non-adjacent blocks."),
        ])
        expanded = expand_context(inventory)
        row = _row(expanded, "target")
        audit = row["context_audit"]

        self.assertEqual(audit["neighbor_block_ids_scanned"], ["bridge", "p5"])
        self.assertEqual(_context_block_ids(row), {"bridge", "p5"})
        bridge_ref = next(ref for ref in audit["input_reference_hints"]
                          if ref["seed_role"] == "BRIDGE_SCAN")
        self.assertEqual(bridge_ref["admission"], "added_whole_bundle")
        self.assertEqual(bridge_ref["resolution"], "resolved")
        self.assertEqual(bridge_ref["bridge_block_id"], "bridge")
        self.assertTrue(bridge_ref["bridge_whole_delivery"])
        self.assertTrue(bridge_ref["required_whole_delivery"])
        self.assertNotIn("p8", _context_block_ids(row))

    def test_fetched_reference_is_not_recursively_scanned(self):
        inventory = _inventory([
            ("bridge", "[19] See paragraph 5 of these reasons."),
            ("target", "[20] This outcome is subject to the statutory condition."),
            ("adjacent", "[21] No owned reference here."),
            ("p5", "[5] This fetched block points to paragraph 9 of these reasons."),
            ("p9", "[9] Must not be fetched recursively."),
        ])
        row = _row(expand_context(inventory), "target")
        self.assertEqual(_context_block_ids(row), {"bridge", "p5"})
        self.assertNotIn("p9", _context_block_ids(row))
        self.assertTrue(all(ref["reference_hop"] == 1
                            for ref in row["context_audit"]["input_reference_hints"]))

    def test_already_delivered_reference_does_not_change_or_resend_packet(self):
        inventory = _inventory([
            ("p5", "[5] Complete referenced text already present in the first packet."),
            ("target", "[21] See paragraph 5 of these reasons."),
        ], baseline_context={"target": ["p5"]})
        original = _row(inventory, "target")
        expanded = expand_context(inventory)
        row = _row(expanded, "target")
        hint = row["context_audit"]["input_reference_hints"][0]

        self.assertTrue(hint["ownership_confirmed_local"])
        self.assertEqual(hint["admission"], "already_delivered")
        self.assertEqual(hint["resolution"], "resolved")
        self.assertEqual(row["packet"], original["packet"])
        self.assertEqual(row["serialized_payload"], original["serialized_payload"])
        cost = request_cost(original, row, mode="two_step")
        self.assertEqual(cost["hypothetical_second_requests"], 0)

    def test_quoted_external_ambiguous_and_citation_year_refs_stay_unresolved(self):
        cases = [
            _inventory([
                ("target", '[21] Smith said, "paragraph 5 of these reasons".'),
                ("p5", "[5] Local number coincidence only."),
            ]),
            _inventory([
                ("target", "[21] The other decision states paragraph 5 of these reasons."),
                ("p5", "[5] Local number coincidence only."),
            ]),
            _inventory([
                ("target", "[21] This matter was set out earlier in paragraph 5 of these reasons."),
                ("p5a", "[5] First ambiguous local marker."),
                ("p5b", "[5] Second ambiguous local marker."),
            ]),
            _inventory([
                ("target", "[21] This matter was set out earlier in paragraph 2006 of these reasons."),
                ("citation", "[2006] FCJ No. 17 (QL), citation metadata.", "unnumbered_paragraph"),
            ]),
        ]
        for index, inventory in enumerate(cases):
            with self.subTest(case=index):
                original = _row(inventory, "target")
                row = _row(expand_context(inventory), "target")
                refs = row["context_audit"]["input_reference_hints"]
                self.assertTrue(refs)
                self.assertFalse(refs[0]["ownership_confirmed_local"])
                self.assertNotEqual(refs[0]["resolution"], "resolved")
                self.assertEqual(_context_block_ids(row), set())
                self.assertEqual(row["serialized_payload"], original["serialized_payload"])

    def test_oversized_atomic_bridge_bundle_is_unknown_without_partial_delivery(self):
        huge = "[5] " + ("condition text " * 500)
        inventory = _inventory([
            ("bridge", "[19] See paragraph 5 of these reasons."),
            ("target", "[20] This is subject to the missing condition."),
            ("p5", huge),
        ])
        original = _row(inventory, "target")
        row = _row(expand_context(inventory), "target")
        ref = next(r for r in row["context_audit"]["input_reference_hints"]
                   if r["seed_role"] == "BRIDGE_SCAN")

        self.assertEqual(ref["admission"], "capped_unknown")
        self.assertEqual(ref["resolution"], "open")
        self.assertEqual(_context_block_ids(row), set())
        self.assertFalse(row["context_audit"]["opened_additional_context"])
        self.assertEqual(row["serialized_payload"], original["serialized_payload"])
        self.assertEqual(row["context_audit"]["context_cap_residual"][0]["status"], "unknown")
        self.assertEqual(row["context_audit"]["context_cap_residual"][0]["reason"],
                         "whole_context_cap_no_truncation")

    def test_interval_cap_keeps_baseline_and_rejects_whole_new_block(self):
        specs = [(f"base{i}", f"[{100+i}] baseline context {i}.") for i in range(12)]
        specs.extend([
            ("target", "[21] See paragraph 5 of these reasons."),
            ("p5", "[5] New block would create the thirteenth context interval."),
        ])
        inventory = _inventory(specs, baseline_context={"target": [f"base{i}" for i in range(12)]})
        original = _row(inventory, "target")
        row = _row(expand_context(inventory), "target")

        self.assertEqual(len(row["packet"]["context"]), 12)
        self.assertEqual(_context_block_ids(row), {f"base{i}" for i in range(12)})
        self.assertEqual(row["serialized_payload"], original["serialized_payload"])
        self.assertEqual(row["context_audit"]["context_cap_residual"][0]["status"], "unknown")

    def test_candidate_packet_and_second_request_counts_are_separate(self):
        inventory = _inventory([
            ("cue_only_a", "[11] This paragraph is subject to a rule; no reference is present."),
            ("barrier_a", "[12] Unrelated paragraph between independent fixtures."),
            ("cue_only_b", "[13] This paragraph is subject to another rule; no reference."),
            ("barrier_b", "[14] Unrelated paragraph between independent fixtures."),
            ("cue_only_c", "[15] This paragraph is subject only to a rule; no reference."),
            ("barrier_c", "[16] Unrelated paragraph between independent fixtures."),
            ("bridge_a", "[19] See paragraph 5 of these reasons."),
            ("cue_a", "[20] This outcome is subject to the statutory condition."),
            ("p5", "[5] A whole block that is actually added."),
            ("barrier_d", "[21] Unrelated paragraph between independent fixtures."),
            ("bridge_b", "[22] See paragraph 7 of these reasons."),
            ("cue_b", "[23] This outcome is subject to the second statutory condition."),
            ("p7", "[7] A second whole block that is actually added."),
        ])
        expanded = expand_context(inventory)
        counts = source_audit(expanded)["counts"]
        cue_candidates = counts["qualification_dependency_cue"]
        changed_packets = counts["packet_changed"]
        self.assertEqual(cue_candidates, 5)
        self.assertEqual(changed_packets, 4)
        self.assertGreater(cue_candidates, changed_packets)

        original_by_id = {r["region_id"]: r for r in inventory["regions"]}
        expanded_by_id = {r["region_id"]: r for r in expanded["regions"]}
        preassembled_second_requests = sum(
            request_cost(original_by_id[rid], expanded_by_id[rid], mode="preassembled")
            ["hypothetical_second_requests"] for rid in original_by_id
        )
        simulated_second_requests = sum(
            request_cost(original_by_id[rid], expanded_by_id[rid], mode="two_step")
            ["hypothetical_second_requests"] for rid in original_by_id
        )
        self.assertEqual(preassembled_second_requests, 0)
        self.assertEqual(simulated_second_requests, changed_packets)

        # A constrained two-step schedule selects one changed target, so the
        # request count is independently lower than the all-source changed-row
        # count. All other packet costs are positive and cannot fit afterward.
        selected_id = "cue_a"
        first_selected_cost = request_cost(original_by_id[selected_id],
                                           expanded_by_id[selected_id], 4, "two_step")
        ordered_ids = [selected_id] + [rid for rid in original_by_id if rid != selected_id]
        selected = schedule_selective(
            inventory, expanded, ordered_ids,
            budget=first_selected_cost["estimated_tokens"],
            bytes_per_token=4, mode="two_step",
        )
        self.assertEqual([r["region_id"] for r in selected["reads"]], [selected_id])
        second_requests = selected["hypothetical_second_requests"]
        self.assertEqual(second_requests, 1)
        self.assertGreater(changed_packets, second_requests)

    def test_global_order_ids_targets_features_and_hashes_are_unchanged(self):
        inventory = _inventory([
            ("p5", "[5] The referenced condition."),
            ("target", "[21] See paragraph 5 of these reasons."),
            ("tail", "[22] Tail paragraph."),
        ])
        expanded = expand_context(inventory)
        self.assertEqual(priority_order(inventory), priority_order(expanded))
        self.assertEqual([r["region_id"] for r in inventory["regions"]],
                         [r["region_id"] for r in expanded["regions"]])
        before = {r["region_id"]: r for r in inventory["regions"]}
        after = {r["region_id"]: r for r in expanded["regions"]}
        self.assertEqual(set(before), set(after))
        for region_id in before:
            for field in ("target", "features", "source_hash", "block_type"):
                self.assertEqual(before[region_id][field], after[region_id][field],
                                 (region_id, field))


class SelectiveRequestCostTests(unittest.TestCase):
    def _packet_row(self, payload):
        return {"serialized_payload": payload,
                "serialized_utf8_bytes": len(payload.encode("utf-8"))}

    def test_preassembled_and_two_step_bill_full_requests_separately(self):
        baseline = self._packet_row(
            '{"prompt":"P repeated","source":"S original","context":[]}')
        expanded = self._packet_row(
            '{"prompt":"P repeated","source":"S original","context":["new block"]}')
        base_n = baseline["serialized_utf8_bytes"]
        expanded_n = expanded["serialized_utf8_bytes"]
        first_input = json.loads(baseline["serialized_payload"])
        second_input = json.loads(expanded["serialized_payload"])
        self.assertEqual(first_input["prompt"], second_input["prompt"])
        self.assertEqual(first_input["source"], second_input["source"])

        one = request_cost(baseline, expanded, divisor=4, mode="preassembled")
        self.assertEqual(one["serialized_bytes"], expanded_n)
        self.assertEqual(one["estimated_tokens"], math.ceil(expanded_n / 4))
        self.assertEqual(one["hypothetical_requests"], 1)
        self.assertEqual(one["hypothetical_second_requests"], 0)

        two = request_cost(baseline, expanded, divisor=4, mode="two_step")
        self.assertEqual(two["serialized_bytes"], base_n + expanded_n)
        self.assertEqual(two["estimated_tokens"], math.ceil(base_n / 4) + math.ceil(expanded_n / 4))
        self.assertEqual(two["hypothetical_requests"], 2)
        self.assertEqual(two["hypothetical_second_requests"], 1)
        self.assertGreater(two["serialized_bytes"], expanded_n - base_n)

    def test_two_step_uses_per_request_ceil_not_ceil_of_delta_or_sum(self):
        baseline = self._packet_row("12345")
        expanded = self._packet_row("123456")
        result = request_cost(baseline, expanded, divisor=4, mode="two_step")
        self.assertEqual(result["estimated_tokens"], math.ceil(5 / 4) + math.ceil(6 / 4))
        self.assertEqual(result["estimated_tokens"], 4)
        self.assertNotEqual(result["estimated_tokens"], math.ceil((5 + 6) / 4))

    def test_unchanged_packet_has_no_second_request_in_two_step_mode(self):
        packet = self._packet_row('{"prompt":"repeated","source":"same"}')
        result = request_cost(packet, copy.deepcopy(packet), divisor=5, mode="two_step")
        self.assertEqual(result["serialized_bytes"], packet["serialized_utf8_bytes"])
        self.assertEqual(result["hypothetical_requests"], 1)
        self.assertEqual(result["hypothetical_second_requests"], 0)

    def test_cost_rejects_invalid_mode_and_nonpositive_divisor(self):
        packet = self._packet_row("x")
        for divisor, mode in ((0, "preassembled"), (-1, "two_step"), (4, "delta")):
            with self.subTest(divisor=divisor, mode=mode):
                with self.assertRaises(ValueError):
                    request_cost(packet, packet, divisor=divisor, mode=mode)

    def test_two_step_scheduler_charges_full_requests_at_each_divisor(self):
        inventory = _inventory([
            ("target", "[21] See paragraph 5 of these reasons."),
            ("p5", "[5] Full source text repeated in the second request."),
        ])
        expanded = expand_context(inventory)
        ordered = priority_order(inventory)
        before = {r["region_id"]: r for r in inventory["regions"]}
        after = {r["region_id"]: r for r in expanded["regions"]}
        for divisor in (3, 4, 5):
            with self.subTest(divisor=divisor):
                result = schedule_selective(inventory, expanded, ordered,
                                            budget=10**9, bytes_per_token=divisor,
                                            mode="two_step")
                expected = [request_cost(before[rid], after[rid], divisor, "two_step")
                            for rid in ordered]
                self.assertEqual(result["serialized_bytes"],
                                 sum(item["serialized_bytes"] for item in expected))
                self.assertEqual(result["estimated_tokens"],
                                 sum(item["estimated_tokens"] for item in expected))
                self.assertEqual(result["hypothetical_second_requests"],
                                 sum(item["hypothetical_second_requests"] for item in expected))
                self.assertEqual(result["hypothetical_second_requests"],
                                 source_audit(expanded)["counts"]["packet_changed"])


class SelectiveOfflineCliTests(unittest.TestCase):
    root = Path(__file__).resolve().parents[1]
    tester_output_root = (root / "knowledge_base/pipeline_v1/outputs/"
                          "selective_context_offline_20261013/tester")

    @classmethod
    def setUpClass(cls):
        cls.tester_output_root.mkdir(parents=True, exist_ok=True)

    def _command(self, *args):
        return [sys.executable, "-m", "knowledge_base.pipeline_v1.selective_context_offline", *args]

    def test_fresh_cli_is_self_contained_and_refuses_nonempty_output(self):
        with tempfile.TemporaryDirectory(prefix="fresh_cli_", dir=self.tester_output_root) as tmp:
            output = Path(tmp) / "fresh-run"
            command = self._command("--output-root", str(output))
            completed = subprocess.run(command, cwd=self.root, capture_output=True,
                                       text=True, encoding="utf-8", timeout=240)
            self.assertEqual(completed.returncode, 0,
                             "stdout:\n" + completed.stdout + "\nstderr:\n" + completed.stderr)
            report_path = output / "report.json"
            self.assertTrue(report_path.is_file())
            report_bytes = report_path.read_bytes()
            report = json.loads(report_bytes.decode("utf-8-sig"))
            self.assertEqual(report["protocol_status"], "pass")
            self.assertTrue(all(report["protocol_checks"].values()))
            self.assertEqual(report["semantic_quality"], "not_assessed")
            self.assertEqual(report["evaluation_split"], "development/calibration; not heldout")
            self.assertEqual(report["cost"]["network_requests"], 0)
            self.assertEqual(report["cost"]["inference_requests"], 0)
            self.assertEqual(report["cost"]["actual_requests"], 0)

            for entry in report["budget_curves"]:
                self.assertEqual(entry["absolute_budget"],
                                 math.floor(247339 * entry["fraction"]))
                self.assertEqual(entry["baseline_budget_denominator"], 247339)
                self.assertIn(entry["divisor"], (3, 4, 5))
            self.assertEqual({entry["divisor"] for entry in report["budget_curves"]}, {3, 4, 5})

            # Independently recompute matched packet costs from the two saved
            # inventories; do not call request_cost or trust report totals.
            baseline_inventory = json.loads(
                (Path(DEFAULT_BASELINE) / "inventory.json").read_text(encoding="utf-8-sig"))
            selective_inventory = json.loads(
                (output / "inventory.json").read_text(encoding="utf-8-sig"))
            baseline_rows = {r["region_id"]: r for r in baseline_inventory["regions"]}
            selective_rows = {r["region_id"]: r for r in selective_inventory["regions"]}
            for comparison in report["target_matched_cost"]:
                divisor = comparison["divisor"]
                ids = comparison["selected_target_ids"]
                expected = {mode: {"serialized_bytes": 0, "estimated_tokens": 0,
                                   "hypothetical_requests": 0,
                                   "hypothetical_second_requests": 0}
                            for mode in ("preassembled", "two_step")}
                for region_id in ids:
                    before, after = baseline_rows[region_id], selective_rows[region_id]
                    changed = before["serialized_payload"] != after["serialized_payload"]
                    bbytes, abytes = (before["serialized_utf8_bytes"],
                                      after["serialized_utf8_bytes"])
                    for mode in expected:
                        resend = mode == "two_step" and changed
                        expected[mode]["serialized_bytes"] += bbytes + abytes if resend else abytes
                        expected[mode]["estimated_tokens"] += (
                            (bbytes + divisor - 1) // divisor + (abytes + divisor - 1) // divisor
                            if resend else (abytes + divisor - 1) // divisor
                        )
                        expected[mode]["hypothetical_requests"] += 2 if resend else 1
                        expected[mode]["hypothetical_second_requests"] += int(resend)
                self.assertEqual(comparison["costs"]["selective"], expected,
                                 (comparison["target_set_basis"], comparison["fraction"], divisor))
            print("fresh offline CLI TemporaryDirectory output=" + str(output))

            repeated = subprocess.run(command, cwd=self.root, capture_output=True,
                                      text=True, encoding="utf-8", timeout=60)
            self.assertNotEqual(repeated.returncode, 0)
            self.assertIn("nonempty output; overwrite refused", repeated.stderr)
            self.assertEqual(report_path.read_bytes(), report_bytes)

    def test_cli_rejects_tampered_frozen_order_before_creating_output(self):
        with tempfile.TemporaryDirectory(prefix="tampered_order_", dir=self.tester_output_root) as tmp_order, \
                tempfile.TemporaryDirectory(prefix="tampered_output_", dir=self.tester_output_root) as tmp_output:
            source_root = Path(DEFAULT_ORDER_REPORT).parent
            bundle = Path(tmp_order) / "complete-order-bundle"
            bundle.mkdir()
            for name in ("report.json", "frozen_snapshot.json", "inventory.json",
                         "selection_snapshot.json"):
                shutil.copy2(source_root / name, bundle / name)
            tampered = bundle / "report.json"
            document = json.loads(tampered.read_text(encoding="utf-8-sig"))
            ids = document["lock"]["full_ordered_ids"]
            ids[0], ids[1] = ids[1], ids[0]
            tampered.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
            output = Path(tmp_output) / "must-not-be-created"
            completed = subprocess.run(
                self._command("--output-root", str(output), "--order-report", str(tampered)),
                cwd=self.root, capture_output=True, text=True, encoding="utf-8", timeout=180,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn(
                "order/input/target/features/policy/code identity lock differs",
                completed.stderr,
            )
            self.assertFalse(output.exists())


class FrozenInputPreservationTests(unittest.TestCase):
    root = Path(__file__).resolve().parents[1]
    snapshot_path = (root / "knowledge_base/pipeline_v1/outputs/"
                     "selective_context_offline_20261013/main_preservation_snapshot.json")

    @unittest.skipUnless(snapshot_path.is_file(),
                         "Main-owned preservation snapshot is absent; run its verifier separately")
    def test_main_preservation_snapshot_still_matches_all_protected_files(self):
        snapshot = json.loads(self.snapshot_path.read_text(encoding="utf-8-sig"))
        failures = []
        for relative, expected in snapshot["files"].items():
            path = self.root / relative
            actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
            if actual != expected:
                failures.append(relative)
        self.assertEqual(failures, [])

    def test_frozen_policy_retains_whole_block_caps_and_one_hop_limit(self):
        self.assertEqual(POLICY["max_context_chars"], 6000)
        self.assertEqual(POLICY["max_context_intervals"], 12)
        self.assertEqual(POLICY["max_reference_hops"], 1)
        self.assertFalse(POLICY["recursive_fetched_reference"])
        self.assertEqual(POLICY["unchanged_packet"],
                         "byte-identical baseline when no new source span is admitted")


if __name__ == "__main__":
    unittest.main()
