from __future__ import annotations

import copy
import json
import tempfile
import unittest
from collections import Counter, defaultdict
from pathlib import Path

from knowledge_base.pipeline_v1.sentence_atoms import load_and_validate_sentence_atom_map
from knowledge_base.pipeline_v1.sidecars import (
    SidecarAPI,
    SidecarError,
    SidecarQueryError,
    build_sidecars,
    load_and_validate_sidecar_map,
    validate_sidecar_map,
)
from knowledge_base.pipeline_v1.sidecars.workers import FORMAL_HEADING_RE, run_sidecar_workers
from knowledge_base.pipeline_v1.sentence_atoms.segmenter import canonical_hash
from knowledge_base.pipeline_v1.source_contract import open_source
from knowledge_base.pipeline_v1.structural_prepass import load_and_validate_block_map


PIPELINE_DIR = Path(__file__).resolve().parents[1]
REPORT = PIPELINE_DIR / "reports/plan05_sidecar_validation.latest.json"
PLAN03 = PIPELINE_DIR / "reports/plan03_structural_validation.latest.json"
PLAN04 = PIPELINE_DIR / "reports/plan04_sentence_atom_validation.latest.json"
SC_POLICY = PIPELINE_DIR / "policies/sidecar_policy.v1.json"
SA_POLICY = PIPELINE_DIR / "policies/sentence_atom_policy.v1.json"


class Plan05IndependentEvaluation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = json.loads(REPORT.read_text(encoding="utf-8"))
        cls.plan03 = json.loads(PLAN03.read_text(encoding="utf-8"))
        cls.plan04 = json.loads(PLAN04.read_text(encoding="utf-8"))
        cls.policy = json.loads(SC_POLICY.read_text(encoding="utf-8"))
        cls.sentence_policy = json.loads(SA_POLICY.read_text(encoding="utf-8"))
        cls.store = Path(cls.report["inputs"]["source_store"])
        cls.output = Path(cls.report["outputs"]["output_root"])

    def _cases(self):
        block_rows = {row["case_id"]: row for row in self.plan03["cases"]}
        atom_rows = {row["case_id"]: row for row in self.plan04["cases"]}
        for row in self.report["cases"]:
            case_id, source_hash = row["case_id"], row["source_hash"]
            text = open_source(self.store, case_id, source_hash)
            block_path = Path(self.plan03["outputs"]["output_root"]) / block_rows[case_id]["artifact_ref"]
            blocks, _ = load_and_validate_block_map(block_path, text, self.store)
            atom_path = Path(self.plan04["outputs"]["output_root"]) / atom_rows[case_id]["artifact_ref"]
            atoms, _ = load_and_validate_sentence_atom_map(atom_path, text, blocks, self.sentence_policy)
            sidecar_path = self.output / row["artifact_ref"]
            sidecars, _ = load_and_validate_sidecar_map(sidecar_path, text, blocks, atoms, self.policy, self.sentence_policy)
            yield row, text, blocks, atoms, sidecar_path, sidecars

    def test_black_box_recomputed_counts_and_exact_record_spans(self):
        annotations = Counter(); statuses = Counter(); relations = Counter(); relation_status = Counter()
        total_annotations = total_relations = 0
        for _, text, blocks, atoms, path, sidecars in self._cases():
            self.assertTrue(all(validate_sidecar_map(sidecars, text, blocks, atoms, self.policy, self.sentence_policy, artifact_path=path).values()))
            api = SidecarAPI(text, blocks, atoms, sidecars)
            for item in sidecars["annotations"]:
                opened = api.open_annotation(item["annotation_id"])
                ref = item["span"]
                self.assertEqual(opened["exact_source"], text[ref["start_char"]:ref["end_char"]])
                self.assertTrue(item["atom_refs"])
                annotations[item["worker_type"]] += 1; statuses[item["status"]] += 1
            total_annotations += len(sidecars["annotations"])
            total_relations += len(sidecars["relations"])
            relations.update(item["relation_type"] for item in sidecars["relations"])
            relation_status.update(item["status"] for item in sidecars["relations"])
        self.assertEqual(total_annotations, 1036)
        self.assertEqual(total_relations, 419)
        self.assertEqual(relations, Counter({"containment": 209, "governed_by_heading": 200, "continuation": 10}))
        self.assertEqual(relation_status, Counter({"candidate": 210, "observed": 209}))
        self.assertEqual(statuses, Counter({"observed": 904, "candidate": 112, "review": 20}))

    def test_api_filters_and_adjacency_are_exact_half_open(self):
        _, text, blocks, atoms, _, sidecars = next(self._cases())
        api = SidecarAPI(text, blocks, atoms, sidecars)
        annotation = sidecars["annotations"][0]
        ref = annotation["span"]
        self.assertIn(annotation, api.query_annotations(case_id=sidecars["case_id"], start_char=ref["start_char"], end_char=ref["end_char"], block_id=annotation["block_id"], atom_id=annotation["atom_refs"][0], worker_type=annotation["worker_type"], status=annotation["status"]))
        self.assertEqual(api.query_annotations(start_char=ref["end_char"], end_char=ref["end_char"] + 1, block_id=annotation["block_id"]), [])
        interior = ref["start_char"] + max(1, (ref["end_char"] - ref["start_char"]) // 2)
        self.assertLess(interior, ref["end_char"])
        self.assertEqual(api.query_annotations(start_char=interior, end_char=interior), [])
        self.assertEqual(api.query_annotations(start_char=0, end_char=0), [])
        self.assertEqual(api.query_annotations(start_char=len(text), end_char=len(text)), [])
        derived = api.query_relations(relation_type="adjacency")
        self.assertEqual(len(derived), 2 * (len(blocks["blocks"]) - 1))
        self.assertFalse(any(item["relation_type"] == "adjacency" for item in sidecars["relations"]))
        for index in range(len(blocks["blocks"]) - 1):
            current, following = blocks["blocks"][index:index + 2]
            self.assertTrue(any(item["relation_subtype"] == "next" and item["source_ref"] == current["block_id"] and item["target_ref"] == following["block_id"] for item in derived))
        persisted = sidecars["relations"][0]
        evidence = persisted["evidence_spans"][0]
        evidence_mid = evidence["start_char"] + max(1, (evidence["end_char"] - evidence["start_char"]) // 2)
        self.assertIn(persisted, api.query_relations(start_char=evidence_mid, end_char=min(evidence_mid + 1, evidence["end_char"]), relation_type=persisted["relation_type"]))
        self.assertEqual(api.query_relations(start_char=evidence_mid, end_char=evidence_mid, relation_type=persisted["relation_type"]), [])
        self.assertEqual(api.query_relations(start_char=evidence["end_char"], end_char=min(evidence["end_char"] + 1, len(text)), relation_type=persisted["relation_type"]), [])
        adjacency = derived[0]
        adjacency_span = adjacency["evidence_spans"][0]
        adjacency_mid = adjacency_span["start_char"] + max(1, (adjacency_span["end_char"] - adjacency_span["start_char"]) // 2)
        self.assertTrue(api.query_relations(start_char=adjacency_mid, end_char=min(adjacency_mid + 1, adjacency_span["end_char"]), relation_type="adjacency"))
        self.assertEqual(api.query_relations(start_char=adjacency_mid, end_char=adjacency_mid, relation_type="adjacency"), [])
        for kwargs in (
            {"start_char": 1}, {"end_char": 1}, {"start_char": -1, "end_char": 0},
            {"start_char": 2, "end_char": 1}, {"start_char": 0, "end_char": len(text) + 1},
            {"start_char": True, "end_char": 1}, {"case_id": "999999"}, {"source_hash": "0" * 64},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(SidecarQueryError): api.query_annotations(**kwargs)
                with self.assertRaises(SidecarQueryError): api.query_relations(**kwargs)

    def test_governance_200_edges_follow_contiguous_formal_heading_ranges(self):
        total = 0; false_positive_samples = []
        for _, text, blocks, _, _, sidecars in self._cases():
            block_by_id = {block["block_id"]: block for block in blocks["blocks"]}
            edges = [item for item in sidecars["relations"] if item["relation_type"] == "governed_by_heading"]
            total += len(edges)
            pairs = set()
            for edge in edges:
                self.assertEqual(edge["status"], "candidate")
                self.assertNotEqual(edge["source_ref"], edge["target_ref"])
                self.assertNotIn((edge["source_ref"], edge["target_ref"]), pairs); pairs.add((edge["source_ref"], edge["target_ref"]))
                source, heading = block_by_id[edge["source_ref"]], block_by_id[edge["target_ref"]]
                self.assertLess(heading["order"], source["order"])
                heading_text = text[heading["content_span"]["start_char"]:heading["content_span"]["end_char"]].strip()
                self.assertIsNotNone(FORMAL_HEADING_RE.fullmatch(heading_text))
                self.assertEqual(edge["evidence_spans"], [heading["content_span"]])
                intervening = blocks["blocks"][heading["order"] + 1:source["order"] + 1]
                self.assertFalse(any(block["block_type"] == "heading_candidate" and FORMAL_HEADING_RE.fullmatch(text[block["content_span"]["start_char"]:block["content_span"]["end_char"]].strip()) for block in intervening))
            for block in blocks["blocks"]:
                if block["block_type"] == "heading_candidate":
                    value = text[block["content_span"]["start_char"]:block["content_span"]["end_char"]].strip()
                    if FORMAL_HEADING_RE.fullmatch(value) is None:
                        false_positive_samples.append(value[:80])
                        self.assertFalse(any(edge["target_ref"] == block["block_id"] for edge in edges))
        self.assertEqual(total, 200)
        self.assertTrue(false_positive_samples)

    def test_containment_and_continuation_have_no_self_duplicate_or_cross_parent_edges(self):
        totals = Counter()
        for _, _, blocks, _, _, sidecars in self._cases():
            block_ids = {block["block_id"] for block in blocks["blocks"]}
            annotations = {item["annotation_id"]: item for item in sidecars["annotations"]}
            seen = set()
            for relation in sidecars["relations"]:
                key = (relation["relation_type"], relation["source_ref"], relation["target_ref"], relation["relation_subtype"])
                self.assertNotIn(key, seen); seen.add(key)
                self.assertNotEqual(relation["source_ref"], relation["target_ref"])
                totals[relation["relation_type"]] += 1
                if relation["relation_type"] == "containment":
                    self.assertIn(relation["source_ref"], annotations)
                    self.assertEqual(annotations[relation["source_ref"]]["block_id"], relation["target_ref"])
                elif relation["relation_type"] == "continuation":
                    self.assertIn(relation["source_ref"], block_ids); self.assertIn(relation["target_ref"], block_ids)
        self.assertEqual(totals["containment"], 209); self.assertEqual(totals["continuation"], 10)

    def test_semantic_boundaries_and_forbidden_assertions(self):
        forbidden_terms = ("speaker_identity", "attribution", "authority_identity", "treatment", "noticed_case", "relevance", "qualifies", "responds_to", "condition_for", "same_legal_point", "AuthorityUnit", "NoticeNeed", "retrieval", "LLM")
        for _, text, _, _, _, sidecars in self._cases():
            serialized = json.dumps(sidecars, ensure_ascii=False)
            for term in forbidden_terms: self.assertNotIn(term, serialized)
            for item in sidecars["annotations"]:
                excerpt = text[item["span"]["start_char"]:item["span"]["end_char"]]
                if item["annotation_type"] == "paragraph_marker": self.assertRegex(excerpt, r"^\s*\[\d{1,3}\]")
                if item["annotation_type"] == "citation_year": self.assertRegex(excerpt, r"^\[(?:18|19|20)\d{2}\]$")
                if item["annotation_type"] == "speaker_cue": self.assertEqual(item["status"], "candidate")
            self.assertFalse(any(item["relation_type"] in {"qualifies", "responds_to", "condition_for", "same_legal_point"} for item in sidecars["relations"]))

    def test_each_annotation_relation_and_map_mutation_is_rejected(self):
        _, text, blocks, atoms, path, original = next(self._cases())
        annotation_mutations = {
            "id": lambda x: x.update(annotation_id="an-" + "0" * 24), "case": lambda x: x.update(case_id="999999"),
            "source": lambda x: x.update(source_hash="0" * 64), "span": lambda x: x["span"].update(end_char=x["span"]["end_char"] + 1),
            "block": lambda x: x.update(block_id="sb-" + "0" * 24), "atoms": lambda x: x.update(atom_refs=[]),
            "worker": lambda x: x.update(worker_type="speaker_cue_rule"), "value": lambda x: x.update(value_code="tampered"),
            "status": lambda x: x.update(status="error"), "producer": lambda x: x.update(producer_version="tampered"),
            "evidence": lambda x: x.update(evidence_refs=["tampered"]), "dependencies": lambda x: x["dependencies"].update(sidecar_policy_sha256="0" * 64),
        }
        relation = original["relations"][0]
        relation_mutations = {
            "id": lambda x: x.update(relation_id="sr-" + "0" * 24), "source": lambda x: x.update(source_ref="tampered"),
            "target": lambda x: x.update(target_ref="tampered"), "type": lambda x: x.update(relation_type="continuation"),
            "status": lambda x: x.update(status="error"), "evidence": lambda x: x.update(evidence_refs=["tampered"]),
            "span": lambda x: x["evidence_spans"][0].update(end_char=x["evidence_spans"][0]["end_char"] + 1),
        }
        for name, mutate in annotation_mutations.items():
            with self.subTest(record="annotation", field=name):
                changed = copy.deepcopy(original); mutate(changed["annotations"][0])
                with self.assertRaises(SidecarError): validate_sidecar_map(changed, text, blocks, atoms, self.policy, self.sentence_policy, artifact_path=path)
        for name, mutate in relation_mutations.items():
            with self.subTest(record="relation", field=name):
                changed = copy.deepcopy(original); mutate(changed["relations"][0])
                with self.assertRaises(SidecarError): validate_sidecar_map(changed, text, blocks, atoms, self.policy, self.sentence_policy, artifact_path=path)
        for name, mutate in {
            "cache": lambda x: x.update(cache_key="0" * 64), "policy": lambda x: x.update(policy_sha256="0" * 64),
            "sourceblock": lambda x: x.update(sourceblock_cache_key="0" * 64), "atoms": lambda x: x.update(sentence_atom_cache_key="0" * 64),
            "bundle": lambda x: x.update(worker_bundle_version="tampered"), "missing": lambda x: x.pop("annotations"),
            "extra": lambda x: x.update(extra=True),
        }.items():
            with self.subTest(record="map", field=name):
                changed = copy.deepcopy(original); mutate(changed)
                with self.assertRaises(SidecarError): validate_sidecar_map(changed, text, blocks, atoms, self.policy, self.sentence_policy, artifact_path=path)

    def test_worker_failure_isolation_and_partial_namespace(self):
        _, text, blocks, atoms, _, complete = next(self._cases())
        policy_hash = canonical_hash(self.policy)
        partial = run_sidecar_workers(text, blocks, atoms, self.policy, policy_hash, {"marker_rule"})
        self.assertEqual(partial["run_status"], "partial"); self.assertEqual(partial["failed_workers"], ["marker_rule"])
        self.assertTrue(any(run["worker_type"] == "marker_rule" and run["status"] == "failed" for run in partial["worker_runs"]))
        self.assertTrue(any(item["worker_type"] != "marker_rule" for item in partial["annotations"]))
        self.assertTrue(partial["worker_events"] and partial["worker_events"][0]["severity"] == "error")
        self.assertEqual(partial["cache_key"], complete["cache_key"])
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "out"
            report = build_sidecars(source_store=self.store, plan03_report=PLAN03, plan04_report=PLAN04, plan04_independent_report=PIPELINE_DIR / "evaluation/plan04_independent_evaluation.md", sourceblock_policy=PIPELINE_DIR / "policies/sourceblock_policy.v1.json", sentence_policy=SA_POLICY, policy_path=SC_POLICY, output_root=output, fault_workers={"marker_rule"})
            self.assertEqual(report["status"], "fail")
            self.assertTrue(all("partial-" in row["artifact_ref"] for row in report["cases"]))
            self.assertTrue(all(row["artifact_action"] == "created" for row in report["cases"]))


if __name__ == "__main__": unittest.main()
