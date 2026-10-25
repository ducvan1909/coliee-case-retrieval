"""Offline Plan 11 ContextHint pairing and prompt-transport regressions."""
from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from knowledge_base.pipeline_v1.au_compact import hints
from knowledge_base.pipeline_v1.au_compact.core import build_evidence_catalog
from knowledge_base.pipeline_v1.au_compact.manifest import _binding_path
from knowledge_base.pipeline_v1.au_compact.prompting import (
    FEW_SHOTS,
    INSTRUCTIONS,
    _REQUEST_TEMPLATE,
    build_prompt,
)
from knowledge_base.pipeline_v1.au_compact.runner import _key, _render
from knowledge_base.pipeline_v1.context_hint_experiment.core import build_pairs


ROOT = Path(__file__).resolve().parents[3]
PIPELINE = ROOT / "knowledge_base" / "pipeline_v1"
READINESS = PIPELINE / "outputs" / "plan11_context_hint_readiness_20261011" / "readiness.json"
SOURCE_STORE = PIPELINE / "outputs" / "source_store_v1"
ATOM_ROOT = PIPELINE / "outputs" / "plan04_sentence_atoms_v1"


class ContextHintPairsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = build_pairs(READINESS, SOURCE_STORE, ATOM_ROOT)
        cls.manifest = cls.result["manifest"]
        cls.pairing = cls.result["pairing"]
        cls.requests = {row["request_id"]: row for row in cls.manifest["requests"]}

    def test_real_four_pairs_keep_the_locked_base_and_vary_only_hint_treatment(self):
        self.assertEqual(self.manifest["artifact_type"], "AUCompactLockedManifest")
        self.assertEqual(len(self.manifest["requests"]), 8)
        self.assertEqual(self.pairing["pair_count"], 4)
        self.assertEqual(self.pairing["request_count"], 8)
        self.assertFalse(self.pairing["semantic_gold"])
        self.assertFalse(self.pairing["semantic_quality_claim"])

        for pair in self.pairing["pairs"]:
            with self.subTest(pair_id=pair["pair_id"]):
                p2a = self.requests[pair["request_ids"]["P2a"]]
                p2b = self.requests[pair["request_ids"]["P2b"]]
                self.assertEqual(p2a["case_id"], p2b["case_id"])
                self.assertEqual(p2a["source_hash"], p2b["source_hash"])
                self.assertEqual(p2a["expected_target_ids"], p2b["expected_target_ids"])
                self.assertEqual(p2a["source_refs"], p2b["source_refs"])
                self.assertEqual(p2a["spec"], p2b["spec"])
                self.assertEqual(p2a["atom_binding"], p2b["atom_binding"])
                self.assertEqual(p2a["context_hint_experiment"], "metadata-only-v1")
                self.assertEqual(p2b["context_hint_experiment"], "metadata-only-v1")
                self.assertEqual(p2a["hint_payload"]["version"], "resolved-context-hints-v1")
                self.assertEqual(p2b["hint_payload"]["version"], "resolved-context-hints-v1")
                self.assertEqual(p2a["hint_payload"]["hints"], [])
                self.assertEqual(len(p2b["hint_payload"]["hints"]), 1)
                self.assertTrue(pair["hint_transmitted"])

                # Arm and request identity are expected to differ. All other
                # request fields, including model/schema/caps/base context,
                # must be identical except for the resolved hint payload and
                # its content-dependent accounting.
                left, right = copy.deepcopy(p2a), copy.deepcopy(p2b)
                for request in (left, right):
                    request.pop("request_id")
                    request.pop("arm")
                    request.pop("hint_payload")
                    request.pop("input_tokens")
                self.assertEqual(left, right)

    def test_resolved_hint_content_reaches_prompt_and_changes_request_cache_key(self):
        for pair in self.pairing["pairs"]:
            with self.subTest(pair_id=pair["pair_id"]):
                p2a = self.requests[pair["request_ids"]["P2a"]]
                p2b = self.requests[pair["request_ids"]["P2b"]]
                source = _open_source(SOURCE_STORE, p2a["case_id"], p2a["source_hash"])
                binding_path = _binding_path(p2a["atom_binding"], ATOM_ROOT)
                catalog = build_evidence_catalog(p2a, binding_path, source)
                prompt_a = build_prompt(p2a, _render(p2a, catalog))
                prompt_b = build_prompt(p2b, _render(p2b, catalog))
                content = p2b["hint_payload"]["hints"][0]["content"]

                self.assertIn("CONTEXT_HINT_PAYLOAD=", prompt_a)
                self.assertIn('"hints":[]', prompt_a)
                self.assertIn(hints.HINT_INSTRUCTIONS, prompt_a)
                self.assertIn("CONTEXT_HINT_PAYLOAD=", prompt_b)
                self.assertIn(hints.HINT_INSTRUCTIONS, prompt_b)
                self.assertIn(content["hint_id"], prompt_b)
                self.assertIn(content["hint_type"], prompt_b)
                self.assertTrue(content["cue_spans"])
                self.assertTrue(content["target_atom_ids"])
                self.assertNotEqual(prompt_a, prompt_b)
                self.assertNotEqual(_key(p2a, "same-locked-manifest"),
                                    _key(p2b, "same-locked-manifest"))

    def test_pair_prompt_byte_accounting_reconciles_without_claiming_provider_tokens(self):
        for pair in self.pairing["pairs"]:
            with self.subTest(pair_id=pair["pair_id"]):
                measured = {}
                for arm, request_id in pair["request_ids"].items():
                    request = self.requests[request_id]
                    source = _open_source(SOURCE_STORE, request["case_id"], request["source_hash"])
                    catalog = build_evidence_catalog(
                        request, _binding_path(request["atom_binding"], ATOM_ROOT), source
                    )
                    prompt = build_prompt(request, _render(request, catalog))
                    byte_count = len(prompt.encode("utf-8"))
                    measured[arm] = byte_count
                    self.assertEqual(request["input_tokens"], byte_count)
                self.assertEqual(pair["estimated_prompt_bytes"], measured)
        self.assertEqual(
            self.pairing["reserved_prompt_bytes_estimate"],
            sum(request["input_tokens"] for request in self.manifest["requests"]),
        )
        # These are deterministic byte estimates. No provider call occurred,
        # so the pairing must not claim measured provider token usage.
        self.assertNotIn("provider_usage", self.pairing)
        self.assertNotIn("actual_input_tokens", self.pairing)

    def test_legacy_request_without_experiment_keeps_the_old_prompt_body(self):
        request = {"request_id": "legacy-request", "expected_target_ids": ["target-1"]}
        rendered = "<TARGET atom_id=atom-1>legacy source</TARGET>\n"
        expected = INSTRUCTIONS + FEW_SHOTS + _REQUEST_TEMPLATE.format(
            request_id=request["request_id"],
            target_id=request["expected_target_ids"][0],
            rendered=rendered,
        )
        self.assertEqual(build_prompt(request, rendered), expected)


class ContextHintPayloadValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.hint_root = self.root / "hint_maps"
        self.hint_root.mkdir()
        self.case_id = "test-case"
        self.source_hash = "a" * 64
        self.record = {
            "hint_id": "ch-test-1",
            "hint_type": "dependent_lead_in",
            "status": "candidate",
            "direction": "previous",
            "evidence_spans": [{"start_char": 3, "end_char": 7}],
            "related_spans": [{"start_char": 12, "end_char": 18}],
            "target_span": {"start_char": 0, "end_char": 10},
            "producer": "deterministic_local_rule",
            "rule_version": "test-v1",
        }
        self.catalog = {
            "atoms": {
                "sa-target": {"atom_id": "sa-target", "case_id": self.case_id,
                              "source_hash": self.source_hash, "start_char": 0,
                              "end_char": 10, "quote": "A cue here", "target_intersecting": True},
                "sa-context": {"atom_id": "sa-context", "case_id": self.case_id,
                               "source_hash": self.source_hash, "start_char": 10,
                               "end_char": 20, "quote": "context text", "target_intersecting": False},
            }
        }
        self.request = {
            "case_id": self.case_id,
            "source_hash": self.source_hash,
            "context_hint_experiment": "metadata-only-v1",
            "atom_binding": {"atom_map_cache_key": "b" * 64},
        }
        self.map_path = self.hint_root / "map.json"
        self.map_value = {
            "case_id": self.case_id,
            "source_hash": self.source_hash,
            "sentence_atom_cache_key": "b" * 64,
            "hints": [self.record],
        }
        self._write_map()
        self.payload = self._payload()
        self.request["hint_payload"] = self.payload

    def _write_map(self):
        self.raw_map = json.dumps(self.map_value, ensure_ascii=False, sort_keys=True,
                                  separators=(",", ":")).encode("utf-8")
        self.map_path.write_bytes(self.raw_map)

    def _payload(self):
        content = hints.resolve_hint(self.record, self.catalog)
        return {
            "version": "resolved-context-hints-v1",
            "case_id": self.case_id,
            "source_hash": self.source_hash,
            "hints": [{
                "content": content,
                "provenance": {
                    "map_relative_path": "map.json",
                    "map_sha256": hashlib.sha256(self.raw_map).hexdigest(),
                    "record_sha256": hints.digest(self.record),
                },
            }],
        }

    def _validate(self, request=None):
        with patch.object(hints, "HINT_ROOT", self.hint_root):
            return hints.validate_payload(request or self.request, self.catalog)

    def test_resolved_payload_is_source_bound_and_uses_region_atom_ids(self):
        self.assertEqual(self._validate(), self.payload)
        content = self.payload["hints"][0]["content"]
        self.assertEqual(content["target_atom_ids"], ["sa-target"])
        self.assertEqual(content["related_atom_ids"], ["sa-context"])
        self.assertEqual(content["cue_spans"][0]["atom_id"], "sa-target")
        self.assertEqual(content["cue_spans"][0]["quote"], "ue h")

    def test_foreign_source_payload_and_dependency_are_rejected(self):
        foreign = copy.deepcopy(self.request)
        foreign["hint_payload"]["source_hash"] = "c" * 64
        with self.assertRaisesRegex(ValueError, "source identity"):
            self._validate(foreign)

        foreign_map = copy.deepcopy(self.map_value)
        foreign_map["source_hash"] = "c" * 64
        self.map_value = foreign_map
        self._write_map()
        self.request["hint_payload"] = self._payload()
        with self.assertRaisesRegex(ValueError, "dependency mismatch"):
            self._validate()

    def test_stale_hint_map_hash_is_rejected(self):
        self.map_path.write_bytes(self.raw_map + b" ")
        with self.assertRaisesRegex(ValueError, "stale hint map"):
            self._validate()

    def test_mutated_cue_content_and_unsafe_atom_ids_are_rejected(self):
        bad_cue = copy.deepcopy(self.request)
        bad_cue["hint_payload"]["hints"][0]["content"]["cue_spans"][0]["quote"] = "invented"
        with self.assertRaisesRegex(ValueError, "resolved hint content mismatch"):
            self._validate(bad_cue)

        bad_id = copy.deepcopy(self.request)
        bad_id["hint_payload"]["hints"][0]["content"]["target_atom_ids"] = ["foreign-atom"]
        with self.assertRaisesRegex(ValueError, "resolved hint content mismatch"):
            self._validate(bad_id)

    def test_hint_map_path_traversal_is_rejected(self):
        traversal = copy.deepcopy(self.request)
        traversal["hint_payload"]["hints"][0]["provenance"]["map_relative_path"] = "../outside.json"
        with self.assertRaisesRegex(ValueError, "escapes root"):
            self._validate(traversal)

    def test_renderer_revalidates_hint_payload_before_emitting_region(self):
        bad = copy.deepcopy(self.request)
        bad["hint_payload"]["source_hash"] = "c" * 64
        with patch.object(hints, "HINT_ROOT", self.hint_root):
            with self.assertRaisesRegex(ValueError, "source identity"):
                _render(bad, self.catalog)


def _open_source(source_store, case_id, source_hash):
    from knowledge_base.pipeline_v1.source_contract import open_source

    return open_source(source_store, case_id, source_hash)


if __name__ == "__main__":
    unittest.main()
