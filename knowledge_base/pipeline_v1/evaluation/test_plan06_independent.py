from __future__ import annotations

import copy
import hashlib
import json
import shutil
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

from knowledge_base.pipeline_v1.context_hints import ContextHintAPI, ContextHintError, load_and_validate_context_hint_build


P = Path(__file__).resolve().parents[1]


class Plan06IndependentEvaluation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = json.loads((P / "reports/plan06_context_hint_validation.latest.json").read_text(encoding="utf-8"))
        cls.root = Path(cls.report["outputs"]["output_root"])
        cls.store = Path(cls.report["inputs"]["source_store"])
        cls.rows = []
        for case in cls.report["cases"]:
            value = json.loads((cls.root / case["artifact_ref"]).read_text(encoding="utf-8"))
            text = (cls.store / "cases" / case["case_id"] / "versions" / case["source_hash"] / "source.txt").read_bytes().decode("utf-8")
            cls.rows.append((case, value, text))

    def build_fixture(self):
        temp = tempfile.TemporaryDirectory(); root = Path(temp.name)
        manifest = json.loads(Path(self.report["outputs"]["build_manifest"]).read_text(encoding="utf-8"))
        for row in manifest["cases"]:
            dst = root / row["artifact_ref"]; dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.root / row["artifact_ref"], dst)
        manifest_path = root / "context_hint_build_manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        cap = root / "cap_dedup_ledger.jsonl"; events = root / "rule_event_ledger.jsonl"
        shutil.copy2(self.report["outputs"]["cap_dedup_ledger"], cap); shutil.copy2(self.report["outputs"]["rule_event_ledger"], events)
        kwargs = {"manifest_path": manifest_path, "cap_ledger_path": cap, "rule_event_ledger_path": events,
                  "source_store": self.report["inputs"]["source_store"], "plan03_report": self.report["inputs"]["plan03_report"],
                  "plan04_report": self.report["inputs"]["plan04_report"], "plan05_report": self.report["inputs"]["plan05_report"],
                  "sourceblock_policy": P / "policies/sourceblock_policy.v1.json", "sentence_policy": P / "policies/sentence_atom_policy.v1.json",
                  "sidecar_policy": P / "policies/sidecar_policy.v1.json", "policy_path": self.report["inputs"]["policy"]}
        return temp, manifest, kwargs

    def test_recompute_kos5_counts_metrics_and_exact_source_spans(self):
        hints = [h for _, value, _ in self.rows for h in value["hints"]]
        self.assertEqual(len(hints), 28)
        self.assertEqual(len({h["target_block_id"] for h in hints}), 25)
        self.assertEqual(Counter(h["hint_type"] for h in hints), Counter({
            "open_quote": 10, "quote_continuation": 10, "dependent_lead_in": 5,
            "reference_to_previous": 2, "speaker_continuity_candidate": 1,
        }))
        self.assertEqual(Counter(h["status"] for h in hints), Counter({"accepted_by_contract": 20, "candidate": 8}))
        refs = [(h["case_id"], r["start_char"], r["end_char"]) for h in hints for r in h["related_spans"]]
        merged = []
        for cid, start, end in sorted(set(refs)):
            if not merged or cid != merged[-1][0] or start > merged[-1][2]:
                merged.append([cid, start, end])
            else:
                merged[-1][2] = max(merged[-1][2], end)
        proposed = sum(end - start for _, start, end in refs)
        unique = sum(end - start for _, start, end in merged)
        self.assertEqual((unique, proposed, proposed - unique), (9632, 10610, 978))
        for case, value, text in self.rows:
            self.assertEqual(hashlib.sha256(text.encode()).hexdigest(), case["source_hash"])
            for hint in value["hints"]:
                for ref in [hint["target_span"], *hint["related_spans"], *hint["evidence_spans"]]:
                    self.assertEqual((ref["case_id"], ref["source_hash"]), (case["case_id"], case["source_hash"]))
                    self.assertTrue(0 <= ref["start_char"] <= ref["end_char"] <= len(text))

    def test_primary_inventory_is_exactly_preserved_and_hints_do_not_materialize_text(self):
        plan03 = json.loads((P / "reports/plan03_structural_validation.latest.json").read_text(encoding="utf-8"))
        block_root = Path(plan03["outputs"]["output_root"])
        cases03 = {row["case_id"]: row for row in plan03["cases"]}
        total = 0
        for case, value, _ in self.rows:
            blocks = json.loads((block_root / cases03[case["case_id"]]["artifact_ref"]).read_text(encoding="utf-8"))
            expected = [b["block_id"] for b in blocks["blocks"]]
            self.assertEqual(value["target_block_ids"], expected)
            total += len(expected)
            def keys(node):
                if isinstance(node, dict):
                    return set(node) | set().union(*(keys(v) for v in node.values()), set())
                if isinstance(node, list):
                    return set().union(*(keys(v) for v in node), set())
                return set()
            self.assertFalse({"text", "source_text", "related_text", "target_text"} & keys(value["hints"]))
        self.assertEqual(total, 431)

    def test_direction_order_no_self_duplicate_and_reverse_pairs_are_auditable(self):
        reverse_pairs = 0
        for _, value, _ in self.rows:
            seen = set()
            order = {bid: i for i, bid in enumerate(value["target_block_ids"])}
            edges = set()
            for hint in value["hints"]:
                key = (hint["target_block_id"], hint["hint_type"], hint["direction"], tuple(hint["related_block_ids"]))
                self.assertNotIn(key, seen); seen.add(key)
                self.assertNotIn(hint["target_block_id"], hint["related_block_ids"])
                for related in hint["related_block_ids"]:
                    self.assertLess(order[related], order[hint["target_block_id"]]) if hint["direction"] == "previous" else self.assertGreater(order[related], order[hint["target_block_id"]])
                    edges.add((hint["target_block_id"], related, hint["hint_type"]))
            reverse_pairs += sum((b, a, "quote_continuation") in edges for a, b, kind in edges if kind == "open_quote")
        self.assertEqual(reverse_pairs, 10)

    def test_api_exact_half_open_filters_and_union_estimate(self):
        case, value, text = next(row for row in self.rows if row[1]["hints"])
        api = ContextHintAPI(text, value)
        hint = value["hints"][0]; start = hint["target_span"]["start_char"]; end = hint["target_span"]["end_char"]
        self.assertEqual(api.query_hints(start_char=start, end_char=start), [])
        self.assertEqual(api.query_hints(start_char=end, end_char=end), [])
        self.assertEqual(api.query_hints(start_char=0, end_char=start), [])
        selected = api.query_hints(case_id=case["case_id"], source_hash=case["source_hash"], start_char=start, end_char=start + 1,
                                   target_block_id=hint["target_block_id"], hint_type=hint["hint_type"], direction=hint["direction"], status=hint["status"])
        self.assertIn(hint, selected)
        estimate = api.estimate_additions()
        self.assertEqual(estimate["proposed_related_chars"] - estimate["unique_related_chars"], estimate["repeated_proposed_chars"])

    def test_stored_build_manifest_case_totals_and_refs_are_not_contract_validated(self):
        schema = json.loads((P / "contracts/context_hint_build_manifest.v1.json").read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema)
        manifest = json.loads(Path(self.report["outputs"]["build_manifest"]).read_text(encoding="utf-8"))
        corrupt = copy.deepcopy(manifest)
        corrupt["cases"][0]["target_count"] = -999
        corrupt["cases"][0]["hint_count"] = 999999
        corrupt["cases"][0]["artifact_ref"] = "missing/context_hint_map.json"
        with self.assertRaises(ValidationError):
            validator.validate(corrupt)

    def test_reader_recomputes_every_manifest_metric_family_and_safe_refs(self):
        temp, manifest, kwargs = self.build_fixture()
        try:
            _, checks = load_and_validate_context_hint_build(**kwargs)
            self.assertEqual((checks["totals"]["hint_count"], checks["totals"]["target_count"], checks["totals"]["unique_related_chars"], checks["totals"]["repeated_proposed_chars"]), (28, 431, 9632, 978))
            mutations = [
                ("case", "target_count"), ("case", "hint_count"), ("case", "pre_policy_count"), ("case", "post_policy_count"),
                ("case", "policy_ledger_count"), ("case", "kept_count"), ("case", "dropped_count"),
                ("case", "hint_type_counts"), ("case", "hint_status_counts"), ("case", "hint_direction_counts"),
                ("case_metrics", "unique_related_chars"), ("case_metrics", "repeated_proposed_chars"),
                ("global", "target_count"), ("global", "hint_count"), ("global", "pre_policy_count"), ("global", "post_policy_count"),
                ("global", "hint_type_counts"), ("global", "hint_status_counts"), ("global", "hint_direction_counts"),
                ("global", "unique_related_chars"), ("global", "repeated_proposed_chars"),
            ]
            for scope, field in mutations:
                bad = copy.deepcopy(manifest)
                obj = bad["cases"][0]["metrics"] if scope == "case_metrics" else bad["cases"][0] if scope == "case" else bad["summary"]
                if isinstance(obj[field], int): obj[field] += 1
                else: obj[field]["independent_fault"] = 1
                kwargs["manifest_path"].write_text(json.dumps(bad), encoding="utf-8")
                with self.subTest(scope=scope, field=field), self.assertRaises(ContextHintError):
                    load_and_validate_context_hint_build(**kwargs)
            for ref in ("../escape/context_hint_map.json", "missing/context_hint_map.json"):
                bad = copy.deepcopy(manifest); bad["cases"][0]["artifact_ref"] = ref
                kwargs["manifest_path"].write_text(json.dumps(bad), encoding="utf-8")
                with self.subTest(ref=ref), self.assertRaises(ContextHintError): load_and_validate_context_hint_build(**kwargs)
        finally:
            temp.cleanup()

    def test_reader_reconciles_ledger_identity_provenance_and_reason(self):
        temp, manifest, kwargs = self.build_fixture()
        try:
            cap_path = kwargs["cap_ledger_path"]; original = cap_path.read_text(encoding="utf-8"); row = json.loads(original.splitlines()[0])
            for field in ("ledger_event_id", "case_id", "source_hash", "proposal_id", "target_block_id", "hint_type", "action", "reason"):
                bad = dict(row); bad[field] = ("0" * 64 if field == "source_hash" else "fault")
                cap_path.write_text(json.dumps(bad) + "\n" + "\n".join(original.splitlines()[1:]) + "\n", encoding="utf-8")
                with self.subTest(field=field), self.assertRaises(ContextHintError): load_and_validate_context_hint_build(**kwargs)
            for payload in ("{\"truncated\":\n", "", original + original.splitlines()[0] + "\n"):
                cap_path.write_text(payload, encoding="utf-8")
                with self.assertRaises(ContextHintError): load_and_validate_context_hint_build(**kwargs)
        finally:
            temp.cleanup()


if __name__ == "__main__":
    unittest.main()
