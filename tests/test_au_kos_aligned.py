"""Independent local tests for source-aligned KOS calibration.

Uses the frozen local source/KOS inputs and synthetic mock model replies only.
No provider, network inference, deployment, or semantic-quality claim is made.
"""
from __future__ import annotations

import copy
import contextlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from knowledge_base.pipeline_v1.au_target_context import core, kos_aligned as kos, runner
from knowledge_base.pipeline_v1.au_target_context.contracts import stage1_version
from knowledge_base.pipeline_v1.au_context_paired.build import read_json


class KOSAlignedIndependentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="au-kos-aligned-independent-")
        cls.root = Path(cls.temp.name)
        cls.prepared = cls.root / "prepared"
        cls.workload_path = cls.prepared / "workload.json"
        cls.reference_path = cls.prepared / "reference_checklist.json"
        with patch("knowledge_base.pipeline_v1.au_context_paired.__main__.study_config",
                   return_value=(None, {}, {})), contextlib.redirect_stdout(io.StringIO()):
            result = kos.main(["prepare", "--output-root", str(cls.prepared)])
            if result != 0:
                raise RuntimeError("KOS aligned CLI prepare failed")
            result = kos.main(["preflight", "--workload", str(cls.workload_path),
                               "--output-root", str(cls.root / "preflight-cli")])
            if result != 0:
                raise RuntimeError("KOS aligned CLI preflight failed")
        cls.workload = read_json(cls.workload_path)
        cls.reference = read_json(cls.reference_path)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_prepare_core_dispatch_source_coverage_and_context_are_locked(self):
        workload = self.workload
        self.assertEqual(workload["artifact_type"], "AUKOSAlignedWorkload")
        checked = core.preflight(workload, cfg=None)
        self.assertEqual(checked["status"], "pass")
        self.assertEqual(checked["target_count"], 16)
        self.assertEqual(checked["reference_count"], 18)
        self.assertEqual(checked["network_requests"], 0)

        refs = self.reference["references"]
        self.assertEqual(len(refs), 18)
        self.assertEqual(len({r["kos_id"] for r in refs}), 18)
        self.assertEqual({case: sum(r["case_id"] == case for r in refs)
                          for case in ("011904", "045155", "099980")},
                         {"011904": 8, "045155": 5, "099980": 5})
        case_rows = {r["case_id"]: r for r in self.reference["cases"]}
        for case_id in ("013009", "013948"):
            self.assertEqual(case_rows[case_id]["status"], "no_reference")
            self.assertFalse(case_rows[case_id]["is_negative"])
            self.assertEqual(case_rows[case_id]["reference_count"], 0)

        rows = {r["target_id"]: r for r in workload["rows"]}
        selections = workload["selected_regions"]
        self.assertEqual(len(selections), 16)
        blocks_by_case = {}
        for source_entry in workload["sources"]:
            case_id = source_entry["case_id"]
            atom_file = (Path(workload["atom_root"]) /
                         source_entry["atom_binding"]["atom_map_relative_path"])
            atom_map = read_json(atom_file)
            if source_entry["boundary_method"] == "bound_atom_parent_blocks":
                spans = [item["span"] for item in atom_map["parent_block_refs"]]
                blocks_by_case[case_id] = [{"start_char": item["start_char"],
                                            "end_char": item["end_char"]} for item in spans]
            else:
                source = next(r for r in workload["rows"] if r["case_id"] == case_id)
                source_text = kos.open_source(workload["source_store"], case_id, source["source_hash"])
                cuts = {0, len(source_text)}
                cuts.update(m.end() for m in re.finditer(r"\n[ \t]*\n", source_text))
                cuts.update(m.start() for m in re.finditer(r"(?m)^[ \t]*\[\d+\][ \t]*", source_text))
                ordered = sorted(cuts)
                blocks_by_case[case_id] = [{"start_char": a, "end_char": b}
                                           for a, b in zip(ordered, ordered[1:]) if a < b]
        for selection in selections:
            row = rows[selection["target_id"]]
            target = selection["target"]
            self.assertEqual(row["target"], {k: target[k] for k in ("start_char", "end_char")})
            self.assertEqual(row["case_id"], selection["case_id"])
            # Context contains at most the immediate full source block at either edge.
            context = selection["context"]
            self.assertLessEqual(len(context), 2)
            first, last = selection["block_indices"]
            blocks = blocks_by_case[selection["case_id"]]
            self.assertEqual(target["start_char"], blocks[first]["start_char"])
            self.assertEqual(target["end_char"], blocks[last]["end_char"])
            expected_context = [blocks[i] for i in (first - 1, last + 1)
                                if 0 <= i < len(blocks)]
            self.assertEqual(context, expected_context)
            for block in context:
                self.assertTrue(block["end_char"] == target["start_char"] or
                                block["start_char"] == target["end_char"])

        source_by_case = {}
        for ref in refs:
            row = rows[ref["target_id"]]
            self.assertEqual(row["case_id"], ref["case_id"])
            self.assertEqual(row["source_hash"], ref["source_hash"])
            span = ref["alignment"]["spans"][0]
            self.assertLessEqual(row["target"]["start_char"], span["start_char"])
            self.assertGreaterEqual(row["target"]["end_char"], span["end_char"])
            if ref["case_id"] not in source_by_case:
                source_by_case[ref["case_id"]] = kos.open_source(
                    workload["source_store"], ref["case_id"], ref["source_hash"])
            excerpt = source_by_case[ref["case_id"]][span["start_char"]:span["end_char"]]
            self.assertIn(ref["alignment"]["status"], ("exact", "whitespace_normalized"))
            if ref["alignment"]["status"] == "exact":
                self.assertEqual(excerpt, ref["evidence_text"])
            else:
                self.assertEqual(" ".join(excerpt.split()), " ".join(ref["evidence_text"].split()))

    def test_kos_annotation_metadata_does_not_enter_any_stage1_model_payload(self):
        for row in self.workload["rows"]:
            job = core.build_stage1(row, self.workload["identity"])
            payload = json.dumps(job["payload"], ensure_ascii=False, sort_keys=True)
            self.assertNotIn("AUKOSAlignedReferenceChecklist", payload)
            self.assertNotIn("kos_id", payload)
            self.assertNotIn("issue_ids", payload)
            self.assertNotIn("evidence_text", payload)
            self.assertNotIn("alignment", payload)
            for ref in self.reference["references"]:
                if ref["target_id"] == row["target_id"]:
                    self.assertNotIn(ref["kos_id"], payload)
                    if ref["claim_text"]:
                        self.assertNotIn(ref["claim_text"], payload)
                    if ref["limits_text"]:
                        self.assertNotIn(ref["limits_text"], payload)
            row_keys = set(row)
            self.assertFalse(row_keys.intersection({"kos_references", "kos_claims", "issue_ids", "limits"}))

    def test_preflight_rebuilds_and_rejects_rehashed_workload_tampering(self):
        changes = []
        altered = copy.deepcopy(self.workload)
        altered["input_bindings"][0]["sha256"] = "0" * 64
        changes.append(("input hash", altered))

        altered = copy.deepcopy(self.workload)
        altered["sources"][0]["source_hash"] = "2" * 64
        changes.append(("source hash", altered))

        altered = copy.deepcopy(self.workload)
        altered["rows"][0]["target"]["start_char"] += 1
        changes.append(("row/source selection", altered))

        altered = copy.deepcopy(self.workload)
        altered["sources"][0]["atom_binding"]["sha256"] = "1" * 64
        changes.append(("atom binding", altered))

        altered = copy.deepcopy(self.workload)
        altered["selected_regions"][0]["context"] = []
        changes.append(("context selection", altered))

        altered = copy.deepcopy(self.workload)
        altered["identity"]["model"] = "forged-model"
        changes.append(("identity", altered))

        altered = copy.deepcopy(self.workload)
        altered["workload_sha256"] = "3" * 64
        with self.assertRaises((ValueError, KeyError, TypeError, OSError)):
            kos.preflight(altered)

        for label, altered in changes:
            altered["workload_sha256"] = kos.fingerprint(
                {k: v for k, v in altered.items() if k != "workload_sha256"})
            with self.subTest(label=label), self.assertRaises((ValueError, KeyError, TypeError, OSError)):
                kos.preflight(altered)

        # A checklist at another path is independently re-read and compared with
        # a freshly reconstructed reference, even after the workload is rehashed.
        altered = copy.deepcopy(self.workload)
        copied_reference = self.root / "tampered-reference.json"
        changed_reference = copy.deepcopy(self.reference)
        changed_reference["references"][0]["claim_text"] += " tampered"
        copied_reference.write_text(json.dumps(changed_reference), encoding="utf-8")
        altered["reference_checklist_path"] = str(copied_reference)
        altered["workload_sha256"] = kos.fingerprint(
            {k: v for k, v in altered.items() if k != "workload_sha256"})
        with self.assertRaises((ValueError, KeyError, TypeError, OSError)):
            kos.preflight(altered)

    def test_mock_resume_and_partial_compare_keep_stage1_candidates_and_usage(self):
        # Select one reference-bearing TARGET and point the synthetic stage1
        # primary at its exact source evidence. Force an invalid stage2 reply.
        reference = self.reference["references"][0]
        row = next(r for r in self.workload["rows"] if r["target_id"] == reference["target_id"])
        evidence_span = reference["alignment"]["spans"][0]
        target_ref = next(r for r in row["target_refs"].values()
                          if r["start_char"] < evidence_span["end_char"] and
                          evidence_span["start_char"] < r["end_char"])
        target_id = row["target_id"]
        output = self.root / "partial-run"

        original_mock_jobs = runner.MockJobs

        class Stage2FailureMock(original_mock_jobs):
            def __init__(self, jobs, *args, **kwargs):
                def response(job):
                    if job["stage"] == 1:
                        return {
                            "version": stage1_version(job["prompt_profile"]),
                            "request_id": job["request_id"], "target_id": job["target_id"],
                            "decision": "positive", "needs_context": [], "reason": "none",
                            "anchors": [{"anchor_id": job["anchor_ids"][0], "kind": "holding",
                                         "primary_ref_id": target_ref["ref_id"],
                                         "supporting_ref_ids": [], "needs_context": ["scope"]}],
                        }
                    return {"version": "invalid-stage2", "request_id": job["request_id"],
                            "target_id": job["target_id"]}
                super().__init__(jobs, *args, response_factory=response, **kwargs)

        with patch("knowledge_base.pipeline_v1.au_context_paired.__main__.study_config",
                   return_value=(None, {}, {})), patch.object(runner, "MockJobs", Stage2FailureMock):
            run_code = kos.main(["run", "--mock", "--workload", str(self.workload_path),
                                 "--target-id", target_id, "--output-root", str(output)])
        # The deliberately invalid stage2 response makes the run incomplete,
        # while still leaving durable stage1 and stage2 receipts for comparison.
        self.assertEqual(run_code, 1)
        run_path = output / "run.json"
        report = read_json(run_path)
        self.assertFalse(report["network_executed"])
        row_report = next(r for r in report["results"] if r["target_id"] == target_id)
        self.assertEqual(row_report["stage1_status"], "verified")
        self.assertEqual(row_report["stage2_status"], "invalid")

        ledger_path = output / "runtime_ledger.json"
        before = read_json(ledger_path)
        with patch("knowledge_base.pipeline_v1.au_context_paired.__main__.study_config",
                   return_value=(None, {}, {})), patch.object(Stage2FailureMock, "__call__",
                                                               side_effect=AssertionError("resume dispatched")):
            resumed = runner.run(self.workload_path, output_root=output, mock=True,
                                 concurrency=2, target_ids=[target_id])
        after = read_json(ledger_path)
        self.assertEqual(after["attempts"], before["attempts"])
        self.assertEqual(after["provider_attempts"], before["provider_attempts"])
        self.assertFalse(resumed["network_executed"])

        # The report's claimed derived state is untrusted; comparison must
        # re-derive it from the bound receipts and preserve the stage1 candidate.
        report = read_json(run_path)
        row_report = next(r for r in report["results"] if r["target_id"] == target_id)
        row_report["status"] = "resolved"
        row_report["output"] = {"decision": "negative", "anchors": []}
        report["results"] = [row_report]
        run_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        compare_root = self.root / "comparison"
        code = kos.main(["compare", "--workload", str(self.workload_path),
                         "--reference-checklist", str(self.reference_path), "--run", str(run_path),
                         "--output-root", str(compare_root)])
        self.assertEqual(code, 0)
        comparison = read_json(compare_root / "comparison.json")
        self.assertEqual(comparison["semantic_review_status"], "semantic_review_pending")
        self.assertEqual(comparison["pipeline_anchor_count"], 0,
                         "an invalid stage2 receipt must not promote stage1 anchors to final output")
        self.assertTrue(comparison["stage1_candidates"])
        self.assertTrue(any(item["kos_overlap_candidates"] for item in comparison["stage1_candidates"]))
        self.assertTrue(all(item["semantic_review_status"] == "semantic_review_pending"
                            for item in comparison["references"]))
        targets = [item for item in comparison["targets"] if item["target_id"] == target_id]
        self.assertEqual(len(targets), 1)
        self.assertIn(targets[0]["status"], {"partial", "pending", "provider_or_protocol_failure"})
        self.assertNotEqual(targets[0]["status"], "unresolved",
                            "a stage2 protocol failure is not semantic unresolvedness")
        self.assertNotIn("semantic_correct", {item["status"] for item in comparison["references"]})
        self.assertTrue(any(item["stage1_overlap_candidates"] for item in comparison["references"]))
        self.assertIn("execution_summary", comparison)
        self.assertIn("known_provider_usage_observed_subtotal", comparison["execution_summary"])
        self.assertIn("usage_is_complete", comparison["execution_summary"])


if __name__ == "__main__":
    unittest.main()
