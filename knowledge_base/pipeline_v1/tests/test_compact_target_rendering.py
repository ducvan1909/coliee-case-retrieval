"""Offline raw TARGET ownership tests; not semantic extraction validation."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import tempfile
import unittest
from html import unescape
from pathlib import Path
from unittest.mock import patch

from knowledge_base.pipeline_v1.au_compact import runner


class CompactTargetRenderingTests(unittest.TestCase):
    def fixture(self, quote, spans):
        start = 40
        request = {
            "case_id": "synthetic", "request_id": "raw-target",
            "source_hash": hashlib.sha256(quote.encode()).hexdigest(),
            "expected_target_ids": ["locked"],
            "source_refs": [{"role": "target", "start_char": start + a,
                             "end_char": start + b, "target_ids": ["locked"]}
                            for a, b in spans],
            "spec": {"model": "offline", "enable_thinking": False,
                     "caps": {"output_tokens": 800}},
            "atom_binding": {
                "atom_map_relative_path": "synthetic.json", "atom_map_sha256": "a" * 64,
                "atom_map_cache_key": "b" * 64, "case_id": "synthetic",
                "source_hash": hashlib.sha256(quote.encode()).hexdigest(),
                "segmenter_version": "offline", "policy_sha256": "c" * 64,
            },
        }
        catalog = {"atoms": {"sa-owned": {
            "atom_id": "sa-owned", "start_char": start, "end_char": start + len(quote),
            "quote": quote, "target_intersecting": True,
        }}, "metrics": {}}
        return request, catalog

    def segments(self, rendered):
        return [(role, int(a), int(b), unescape(text))
                for role, a, b, text in re.findall(
                    r"<(TARGET_BODY|CONTEXT_PADDING) span=(\d+):(\d+)>(.*?)</\1>",
                    rendered, re.S)]

    def test_two_raw_refs_keep_gap_as_padding_and_do_not_change_catalog(self):
        quote = "prefix|first rule|gap condition|second rule|suffix"
        spans = [(quote.index("first rule"), quote.index("|gap")),
                 (quote.index("second rule"), quote.index("|suffix"))]
        request, catalog = self.fixture(quote, list(reversed(spans)))
        before = copy.deepcopy((request, catalog))
        rendered = runner._render(request, catalog)
        pieces = self.segments(rendered)
        self.assertEqual([p[0] for p in pieces],
                         ["CONTEXT_PADDING", "TARGET_BODY", "CONTEXT_PADDING",
                          "TARGET_BODY", "CONTEXT_PADDING"])
        self.assertEqual([p[3] for p in pieces],
                         ["prefix|", "first rule", "|gap condition|", "second rule", "|suffix"])
        self.assertEqual("".join(p[3] for p in pieces), quote)
        self.assertEqual([(p[1], p[2]) for p in pieces],
                         [(40, 47), (47, 57), (57, 72), (72, 83), (83, 90)])
        self.assertEqual((request, catalog), before)
        self.assertEqual(rendered.count("atom_id=sa-owned"), 1)
        self.assertIn("span=40:90", rendered)

    def test_overlap_and_adjacent_refs_emit_each_character_once(self):
        request, catalog = self.fixture("abcdefghij", [(2, 5), (4, 7), (7, 9), (2, 5)])
        self.assertEqual(self.segments(runner._render(request, catalog)),
                         [("CONTEXT_PADDING", 40, 42, "ab"),
                          ("TARGET_BODY", 42, 49, "cdefghi"),
                          ("CONTEXT_PADDING", 49, 50, "j")])

    def test_whole_owned_atom_uses_body_and_context_atoms_stay_context_in_source_order(self):
        request, catalog = self.fixture("owned rule", [(0, 10)])
        for atom_id, start, quote in (("sa-after", 70, "after"), ("sa-before", 0, "before")):
            catalog["atoms"][atom_id] = {
                "atom_id": atom_id, "start_char": start, "end_char": start + len(quote),
                "quote": quote, "target_intersecting": False,
            }
        rendered = runner._render(request, catalog)
        self.assertEqual(self.segments(rendered), [("TARGET_BODY", 40, 50, "owned rule")])
        self.assertNotIn("CONTEXT_PADDING", rendered)
        self.assertLess(rendered.index("atom_id=sa-before"), rendered.index("atom_id=sa-owned"))
        self.assertLess(rendered.index("atom_id=sa-owned"), rendered.index("atom_id=sa-after"))
        self.assertIn("<CONTEXT atom_id=sa-before span=0:6>\nbefore\n</CONTEXT>", rendered)

    def test_unicode_newlines_and_source_markup_round_trip_without_false_target_tags(self):
        prefix = '<TARGET_BODY>fake rule</TARGET_BODY>&amp;\\u0041\r\n'
        body = 'Tòa 🙂 "record"\n'
        suffix = '<TARGET atom_id=fake>rule</TARGET>\tĐ'
        quote = prefix + body + suffix
        request, catalog = self.fixture(quote, [(len(prefix), len(prefix + body))])
        rendered = runner._render(request, catalog)
        pieces = self.segments(rendered)
        self.assertEqual([p[3] for p in pieces], [prefix, body, suffix])
        self.assertEqual("".join(p[3] for p in pieces), quote)
        self.assertEqual(rendered.count("<TARGET_BODY"), 1)
        self.assertEqual(rendered.count("<TARGET atom_id="), 1)
        self.assertIn("&lt;TARGET_BODY&gt;fake rule", rendered)
        self.assertIn("&amp;amp;\\u0041\r\n", rendered)
        self.assertEqual(catalog["atoms"]["sa-owned"]["quote"], quote)

    def test_raw_bounds_change_render_even_with_identical_catalog(self):
        request, catalog = self.fixture("prefix record suffix", [(0, 20)])
        shrunk = copy.deepcopy(request)
        shrunk["source_refs"][0].update(start_char=47, end_char=53)
        whole = runner._render(request, catalog)
        narrower = runner._render(shrunk, catalog)
        self.assertNotEqual(whole, narrower)
        self.assertNotEqual(hashlib.sha256(whole.encode()).hexdigest(),
                            hashlib.sha256(narrower.encode()).hexdigest())
        self.assertEqual([p[3] for p in self.segments(narrower) if p[0] == "TARGET_BODY"], ["record"])

    def test_factual_body_does_not_own_padding_rule_but_padding_condition_is_retained(self):
        prefix = "The court states permits require a hearing. "
        fact = "A box arrived Tuesday."
        suffix = " This requirement applies only to sealed archives."
        request, catalog = self.fixture(prefix + fact + suffix, [(len(prefix), len(prefix + fact))])
        pieces = self.segments(runner._render(request, catalog))
        self.assertEqual([p[3] for p in pieces if p[0] == "TARGET_BODY"], [fact])
        self.assertEqual([p[3] for p in pieces if p[0] == "CONTEXT_PADDING"], [prefix, suffix])

    def test_only_refs_absent_unbound_synthetic_mock_retains_legacy(self):
        request, catalog = self.fixture("rule", [(0, 4)])
        mock = {key: request[key] for key in ("case_id", "request_id", "expected_target_ids")}
        self.assertIn("\nrule\n</TARGET>", runner._render(mock, catalog))
        self.assertNotIn("TARGET_BODY", runner._render(mock, catalog))
        for extra in ({"source_refs": []}, {"source_hash": request["source_hash"]},
                      {"atom_binding": request["atom_binding"]}):
            with self.subTest(extra=extra), self.assertRaises(runner.CompactRunError):
                runner._render({**mock, **extra}, catalog)

    def test_real_refs_empty_missing_context_only_or_foreign_owner_fail_closed(self):
        request, catalog = self.fixture("rule", [(0, 4)])
        for refs in (None, [], [{"role": "context", "start_char": 40, "end_char": 44}],
                     [{"role": "target", "start_char": 40, "end_char": 44, "target_ids": ["other"]}]):
            bad = copy.deepcopy(request)
            if refs is None:
                del bad["source_refs"]
            else:
                bad["source_refs"] = refs
            with self.subTest(refs=refs), self.assertRaises(runner.CompactRunError):
                runner._render(bad, catalog)

    def test_invalid_bounds_or_stale_intersection_flag_fail_closed(self):
        request, catalog = self.fixture("rule", [(0, 4)])
        for start, end in ((44, 40), (-1, 44), (40, 40), (40.0, 44), (80, 84)):
            bad = copy.deepcopy(request)
            bad["source_refs"][0].update(start_char=start, end_char=end)
            with self.subTest(bounds=(start, end)), self.assertRaises(runner.CompactRunError):
                runner._render(bad, catalog)
        catalog["atoms"]["sa-owned"]["target_intersecting"] = False
        with self.assertRaisesRegex(runner.CompactRunError, "intersection mismatch"):
            runner._render(request, catalog)

    def test_render_version_invalidates_cache_hash_with_other_inputs_unchanged(self):
        request, _ = self.fixture("rule", [(0, 4)])
        before = runner._key(request, "same-manifest")
        with patch.object(runner, "RENDER_VERSION", runner.RENDER_VERSION + "-changed"):
            self.assertNotEqual(before, runner._key(request, "same-manifest"))

    def test_render_version_invalidates_selection_and_rejects_old_ledger_offline(self):
        request, catalog = self.fixture("rule", [(0, 4)])
        manifest = {"requests": [request]}
        cfg = {"model": "offline", "enable_thinking": False}
        budget = {"max_requests": 0, "max_provider_attempts": 0,
                  "max_total_input_tokens": 0, "max_total_output_tokens": 0}

        def offline_only(*args, **kwargs):
            self.fail("unexpected provider call")

        with tempfile.TemporaryDirectory() as folder, \
                patch.object(runner, "compact_preflight", return_value={"status": "pass"}), \
                patch.object(runner, "warmup", return_value={"status": "success"}), \
                patch.object(runner, "_compact_schema_probe", return_value={"status": "supported"}), \
                patch.object(runner, "open_source", return_value="rule"), \
                patch.object(runner, "_binding_path", return_value={}), \
                patch.object(runner, "build_evidence_catalog", return_value=catalog):
            kwargs = dict(source_store="unused", atom_root="unused", cfg=cfg, budget=budget,
                          cache_dir=Path(folder) / "first" / "cache", execute=True, opener=offline_only)
            before = runner.run(manifest, **kwargs)
            self.assertEqual(before["request_ledger"][0]["status"], "budget_stopped")
            # Budget-stop does not persist a ledger; supply an old checkpoint
            # explicitly to exercise resume identity validation without dispatch.
            (Path(folder) / "first" / "runtime_ledger.json").write_text(
                json.dumps(before["runtime_ledger"]), encoding="utf-8")
            with patch.object(runner, "RENDER_VERSION", runner.RENDER_VERSION + "-changed"):
                with self.assertRaisesRegex(runner.CompactRunError, "ledger identity mismatch"):
                    runner.run(manifest, **kwargs)
                after = runner.run(manifest, **{**kwargs, "cache_dir": Path(folder) / "fresh" / "cache"})
            self.assertNotEqual(before["selection_identity"], after["selection_identity"])


if __name__ == "__main__":
    unittest.main()
