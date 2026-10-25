"""Independent contract tests for the opt-in evidence_first_v1 AU profile.

All model responses are synthetic. These tests exercise protocol, source-span
reconstruction, stage-2 compatibility and the local mock/resume path only; they
do not establish legal-semantic quality or call a provider.
"""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from knowledge_base.pipeline_v1.au_target_context import core, runner
from knowledge_base.pipeline_v1.au_target_context import contracts, prompts
from knowledge_base.pipeline_v1.au_target_context.grammar import build_grammar


PROFILE = "evidence_first_v1"
IDENTITY = {"model": "fixture-model", "enable_thinking": False}


def row_with_spans():
    """Make two selected spans separated by source that must remain an explicit gap."""
    first = "The court applied the statutory test. "
    middle = "UNSELECTED MATERIAL MUST NOT BE JOINED AS CONTIGUOUS EVIDENCE. "
    second = "The application was therefore dismissed. "
    tail = "Context identifies the reported speaker."
    source = first + middle + second + tail
    spans = {}
    for ref_id, quote, role in (
        ("target-first", first, "target_body"),
        ("target-second", second, "target_body"),
        ("target-extra", middle, "target_body"),
        ("context-speaker", tail, "context"),
    ):
        start = source.index(quote)
        spans[ref_id] = {
            "ref_id": ref_id,
            "source_atom_id": "atom-" + ref_id,
            "case_id": "ef-fixture",
            "source_hash": "e" * 64,
            "start_char": start,
            "end_char": start + len(quote),
            "quote": quote,
            "role": role,
        }
    result = {
        "target_id": "ef-target",
        "case_id": "ef-fixture",
        "source_hash": "e" * 64,
        "target": {"start_char": 0, "end_char": len(first + middle + second)},
        "request": {"request_id": "ef-request"},
        "target_refs": {k: v for k, v in spans.items() if k.startswith("target-")},
        "context_refs": {k: v for k, v in spans.items() if k.startswith("context-")},
        "_source": source,
    }
    result.update(prompts.prompt_metadata(PROFILE))
    return result


def input_data(job):
    content = job["payload"]["messages"][0]["content"]
    return json.loads(content.split("\nINPUT:\n", 1)[1])


def selection(job, refs=("target-first",), *, decision="positive", needs=(),
              anchor_needs=(), kind="holding"):
    anchors = [{"anchor_id": job["anchor_ids"][0], "kind": kind,
                "target_ref_ids": list(refs), "needs_context": list(anchor_needs)}]
    if not refs:
        anchors = []
    reason = {"positive": "none", "negative": "no_legal_proposition",
              "needs_context": "insufficient_target", "unresolved": "unclear_attribution"}[decision]
    return {"version": contracts.STAGE1_EVIDENCE_FIRST,
            "request_id": job["request_id"], "target_id": job["target_id"],
            "decision": decision, "anchors": anchors,
            "needs_context": list(needs), "reason": reason}


class EvidenceFirstStage1Tests(unittest.TestCase):
    def test_profile_has_distinct_wire_version_and_no_claim_generation_slot(self):
        row = row_with_spans()
        ef = core.build_stage1(row, IDENTITY)
        baseline = core.build_stage1({**row, **prompts.prompt_metadata("baseline_v2")}, IDENTITY)
        data = input_data(ef)
        self.assertEqual(data["version"], "au-target-selection-v1")
        self.assertEqual(data["anchor_keys"], ["anchor_id", "kind", "target_ref_ids", "needs_context"])
        self.assertNotIn("primary_claim", data["anchor_keys"])
        self.assertNotIn('"primary_claim"', ef["payload"]["ebnf"])
        self.assertNotEqual(ef["request_id"], baseline["request_id"])
        self.assertNotEqual(ef["payload_sha256"], baseline["payload_sha256"])
        self.assertEqual(contracts.stage1_version(PROFILE), contracts.STAGE1_EVIDENCE_FIRST)
        self.assertEqual(contracts.stage1_anchor_keys(PROFILE), contracts.EVIDENCE_FIRST_ANCHOR_KEYS)

    def test_host_reconstructs_long_claim_from_selected_spans_and_marks_gap(self):
        row = row_with_spans()
        long_quote = "A" * 360
        source = long_quote + " gap text " + "B" * 80
        row["_source"] = source
        row["target_refs"] = {
            "long-a": {"ref_id": "long-a", "start_char": 0, "end_char": 360,
                       "quote": long_quote, "source_atom_id": "a", "case_id": row["case_id"],
                       "source_hash": row["source_hash"], "role": "target_body"},
            "long-b": {"ref_id": "long-b", "start_char": 370, "end_char": 450,
                       "quote": "B" * 80, "source_atom_id": "b", "case_id": row["case_id"],
                       "source_hash": row["source_hash"], "role": "target_body"},
        }
        job = core.build_stage1(row, IDENTITY)
        normalized = core.validate_stage1(selection(job, ("long-b", "long-a")), job)
        anchor = normalized["anchors"][0]
        self.assertEqual(anchor["target_ref_ids"], ["long-a", "long-b"])
        self.assertEqual(anchor["primary_evidence"][0]["quote"], long_quote)
        self.assertEqual(anchor["primary_evidence"][1]["quote"], "B" * 80)
        self.assertEqual(anchor["primary_claim"], long_quote + "\n[GAP 360:370]\n" + "B" * 80)
        self.assertGreater(len(anchor["primary_claim"]), 300)
        self.assertEqual(anchor["claim_origin"], "host_extracted")
        self.assertEqual(anchor["primary_representation"], "extractive_source_spans_with_explicit_gaps")
        self.assertEqual(anchor["primary_gaps"], [{"start_char": 360, "end_char": 370}])
        self.assertNotIn("[GAP 360:370]", source)

    def test_wire_rejects_generated_claim_foreign_or_context_reference(self):
        row = row_with_spans()
        job = core.build_stage1(row, IDENTITY)
        extra_claim = selection(job)
        extra_claim["anchors"][0]["primary_claim"] = "model-generated paraphrase"
        with self.assertRaises((core.TargetContextError, ValueError)):
            core.validate_stage1(extra_claim, job)
        for ref in ("context-speaker", "foreign-ref"):
            bad = selection(job, (ref,))
            with self.subTest(ref=ref), self.assertRaises((core.TargetContextError, ValueError)):
                core.validate_stage1(bad, job)

    def test_multiple_points_keep_host_order_and_each_anchor_has_its_own_evidence(self):
        row = row_with_spans()
        job = core.build_stage1(row, IDENTITY)
        raw = selection(job, ("target-second", "target-first"))
        raw["anchors"].append({"anchor_id": job["anchor_ids"][1], "kind": "procedural_rule",
                               "target_ref_ids": ["target-extra"], "needs_context": []})
        checked = core.validate_stage1(raw, job)
        self.assertEqual([a["anchor_id"] for a in checked["anchors"]], job["anchor_ids"][:2])
        self.assertEqual(checked["anchors"][0]["target_ref_ids"], ["target-first", "target-second"])
        self.assertEqual(checked["anchors"][1]["primary_claim"], row["target_refs"]["target-extra"]["quote"])
        self.assertEqual(len(checked["anchors"]), 2)
        too_many = copy.deepcopy(raw)
        too_many["anchors"].append({"anchor_id": job["anchor_ids"][2], "kind": "holding",
                                    "target_ref_ids": ["target-first"], "needs_context": []})
        self.assertEqual(len(core.validate_stage1(too_many, job)["anchors"]), 3)
        too_many["anchors"].append(copy.deepcopy(too_many["anchors"][0]))
        with self.assertRaises((core.TargetContextError, ValueError)):
            core.validate_stage1(too_many, job)

    def test_empty_negative_unresolved_and_needs_context_branches_are_consistent(self):
        job = core.build_stage1(row_with_spans(), IDENTITY)
        for decision in ("negative", "needs_context", "unresolved"):
            raw = selection(job, (), decision=decision,
                            needs=("speaker",) if decision == "needs_context" else ())
            checked = core.validate_stage1(raw, job)
            self.assertEqual(checked["anchors"], [])
            self.assertEqual(checked["decision"], decision)
            self.assertEqual(checked["revisit_required"], decision in ("needs_context", "unresolved"))
        bad = selection(job, (), decision="positive")
        with self.assertRaises((core.TargetContextError, ValueError)):
            core.validate_stage1(bad, job)


class EvidenceFirstStage2Tests(unittest.TestCase):
    def _locked(self):
        row = row_with_spans()
        one = core.build_stage1(row, IDENTITY)
        raw = selection(one, ("target-first", "target-second"), anchor_needs=("speaker",))
        normalized = core.validate_stage1(raw, one)
        return row, one, raw, normalized

    def test_stage2_wire_quotes_selected_evidence_once_and_omits_compatibility_claim(self):
        row, _, _, normalized = self._locked()
        two = core.build_stage2(row, normalized, IDENTITY)[0]
        locked = input_data(two)["locked_anchors"][0]
        self.assertNotIn("primary_claim", locked)
        self.assertEqual(locked["primary_representation"], "extractive_source_spans_with_explicit_gaps")
        self.assertEqual(locked["primary_gaps"], normalized["anchors"][0]["primary_gaps"])
        quote_texts = [ref["text"] for ref in locked["primary_evidence"]]
        content = two["payload"]["messages"][0]["content"]
        self.assertEqual(quote_texts, [ref["quote"] for ref in normalized["anchors"][0]["primary_evidence"]])
        for quote in quote_texts:
            self.assertEqual(content.count(quote), 1)

    def test_stage2_revalidates_raw_or_normalized_selection_and_preserves_host_claim(self):
        row, one, raw, normalized = self._locked()
        self.assertEqual(len(core.build_stage2(row, raw, IDENTITY)), 1)
        two = core.build_stage2(row, normalized, IDENTITY)[0]
        checked = core.validate_stage2({
            "version": contracts.STAGE2, "request_id": two["request_id"],
            "target_id": two["target_id"], "decision": "complete",
            "anchors": [{"anchor_id": two["locked_anchors"][0]["anchor_id"], "decision": "keep",
                         "supplements": [], "reason": "none"}], "reason": "none",
        }, two)
        final_anchor = checked["anchors"][0]
        self.assertEqual(final_anchor["primary_claim"], normalized["anchors"][0]["primary_claim"])
        self.assertEqual(final_anchor["primary_gaps"], normalized["anchors"][0]["primary_gaps"])
        self.assertEqual(final_anchor["claim_origin"], "host_extracted")
        tampered = copy.deepcopy(normalized)
        tampered["anchors"][0]["primary_claim"] = "invented claim"
        with self.assertRaises((core.TargetContextError, ValueError)):
            core.build_stage2(row, tampered, IDENTITY)
        # Revalidation must also reject a model-authored claim on the raw EF wire.
        tampered_raw = copy.deepcopy(raw)
        tampered_raw["anchors"][0]["primary_claim"] = "invented claim"
        with self.assertRaises((core.TargetContextError, ValueError)):
            core.build_stage2(row, tampered_raw, IDENTITY)
        self.assertEqual(one["stage"], 1)

    def test_no_selected_anchor_never_creates_stage2_job(self):
        row = row_with_spans()
        one = core.build_stage1(row, IDENTITY)
        for decision, needs in (("negative", ()), ("needs_context", ("speaker",)),
                                ("unresolved", ())):
            checked = core.validate_stage1(selection(one, (), decision=decision, needs=needs), one)
            self.assertEqual(core.build_stage2(row, checked, IDENTITY), [])


class EvidenceFirstMockResumeTests(unittest.TestCase):
    def test_prepare_preflight_mock_and_completed_resume_stay_local(self):
        with tempfile.TemporaryDirectory(prefix="au-evidence-first-") as folder:
            root = Path(folder)
            prepared = root / "prepared"
            workload = core.prepare(prepared, manifest=core.DEFAULT_MANIFEST,
                                    parent=core.DEFAULT_PARENT, cfg=None, prompt_profile=PROFILE)
            self.assertEqual(workload["prompt_profile"], PROFILE)
            checked = core.preflight(prepared / "workload.json", cfg=None)
            self.assertEqual(checked["status"], "pass")
            self.assertEqual(checked["network_requests"], 0)
            target_id = workload["rows"][0]["target_id"]
            output = root / "mock-run"
            first = runner.run(prepared / "workload.json", output_root=output, mock=True,
                               concurrency=1, target_ids=[target_id])
            self.assertEqual(first["mode"], "mock")
            self.assertFalse(first["network_executed"])
            self.assertEqual(first["status"], "complete")
            self.assertEqual(first["protocol_invalid"], 0)
            first_ledger = json.loads((output / "runtime_ledger.json").read_text(encoding="utf-8"))
            # Any attempted transport on a completed resume is a regression.
            with patch.object(runner.MockJobs, "__call__", side_effect=AssertionError("mock transport called on resume")):
                resumed = runner.run(prepared / "workload.json", output_root=output, mock=True,
                                     concurrency=1, target_ids=[target_id])
            self.assertEqual(resumed["logical_requests"], first["logical_requests"])
            resumed_ledger = json.loads((output / "runtime_ledger.json").read_text(encoding="utf-8"))
            self.assertEqual(resumed_ledger["provider_attempts"], first_ledger["provider_attempts"])
            self.assertEqual(resumed_ledger["attempts"], first_ledger["attempts"])
            self.assertEqual(resumed["status"], first["status"])
            self.assertFalse(resumed["network_executed"])


if __name__ == "__main__":
    unittest.main()
