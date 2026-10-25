"""Independent finite-scope and host-boundary regression tests for stage 2.

No provider, network, deployment, or semantic-quality claim is involved.
"""
from __future__ import annotations

import itertools
import unittest

from knowledge_base.pipeline_v1.au_target_context import TargetContextError, contracts
from knowledge_base.pipeline_v1.au_target_context.core import validate_stage2
from knowledge_base.pipeline_v1.au_target_context.grammar import build_grammar


def stage2_job(*, context=True):
    refs = {
        "context-ref-a": {"ref_id": "context-ref-a", "quote": "Context A"},
        "context-ref-b": {"ref_id": "context-ref-b", "quote": "Context B"},
    } if context else {}
    return {
        "stage": 2,
        "request_id": "scope-gate-request",
        "target_id": "scope-gate-target",
        "locked_anchors": [{
            "anchor_id": "locked-anchor",
            "primary_claim": "The court applied Rule A.",
            "kind": "holding",
            "target_ref_ids": ["target-ref"],
            "primary_evidence": [{"ref_id": "target-ref", "quote": "Rule A"}],
        }],
        "catalog": {"target_refs": {"target-ref": {"ref_id": "target-ref"}},
                    "context_refs": refs},
    }


def response(job, supplements):
    return {
        "version": contracts.STAGE2,
        "request_id": job["request_id"],
        "target_id": job["target_id"],
        "decision": "complete",
        "anchors": [{"anchor_id": "locked-anchor", "decision": "keep",
                     "supplements": supplements, "reason": "none"}],
        "reason": "none",
    }


def supplement(slot, refs=("context-ref-a",)):
    return {"slot": slot, "text": f"Synthetic {slot} guidance.",
            "context_ref_ids": list(refs)}


def grammar_slot_subsets(grammar):
    """Expand the finite array alternatives from the emitted grammar production."""
    line = next(line for line in grammar.splitlines() if line.startswith("supplements ::= "))
    alternatives = line.split(" ::= ", 1)[1].split(" | ")
    expanded = []
    for alternative in alternatives:
        if alternative == '"[]"':
            expanded.append(())
            continue
        if not (alternative.startswith('"[" ') and alternative.endswith(' "]"')):
            raise AssertionError(f"unrecognized supplements production: {alternative}")
        body = alternative[4:-4]
        expanded.append(tuple(part.removeprefix("supplement-") for part in body.split(' "," ')))
    return expanded


class FiniteScopeGateTests(unittest.TestCase):
    def test_context_grammar_enumerates_all_sixteen_ordered_subsets(self):
        grammar = build_grammar(stage2_job())
        expected = [subset for size in range(len(contracts.SLOTS) + 1)
                    for subset in itertools.combinations(contracts.SLOTS, size)]
        self.assertEqual(grammar_slot_subsets(grammar), expected)
        self.assertEqual(len(set(grammar_slot_subsets(grammar))), 16)

    def test_host_accepts_every_allowed_subset_in_slot_order(self):
        job = stage2_job()
        for size in range(len(contracts.SLOTS) + 1):
            for slots in itertools.combinations(contracts.SLOTS, size):
                with self.subTest(slots=slots):
                    checked = validate_stage2(response(job, [supplement(slot) for slot in slots]), job)
                    actual = tuple(item["slot"] for item in checked["anchors"][0]["supplements"])
                    self.assertEqual(actual, slots)

    def test_repeated_slot_is_rejected_but_two_refs_on_one_scope_are_allowed(self):
        job = stage2_job()
        duplicate = response(job, [supplement("scope"), supplement("scope", ("context-ref-b",))])
        with self.assertRaises((TargetContextError, ValueError, TypeError)):
            validate_stage2(duplicate, job)

        multiple_refs = response(job, [supplement("scope", ("context-ref-a", "context-ref-b"))])
        checked = validate_stage2(multiple_refs, job)
        self.assertEqual(checked["anchors"][0]["supplements"][0]["context_ref_ids"],
                         ["context-ref-a", "context-ref-b"])

    def test_four_distinct_slots_empty_list_and_other_repeated_slot_failures(self):
        job = stage2_job()
        four = response(job, [supplement(slot) for slot in contracts.SLOTS])
        self.assertEqual(len(validate_stage2(four, job)["anchors"][0]["supplements"]), 4)

        self.assertEqual(validate_stage2(response(job, []), job)["anchors"][0]["supplements"], [])
        for slots in (("condition", "condition"), ("exception", "exception"),
                      ("speaker", "speaker")):
            with self.subTest(duplicate_slots=slots), self.assertRaises(
                    (TargetContextError, ValueError, TypeError)):
                validate_stage2(response(job, [supplement(slot) for slot in slots]), job)

    def test_foreign_slot_and_foreign_context_reference_are_rejected(self):
        job = stage2_job()
        with self.assertRaises((TargetContextError, ValueError, TypeError)):
            validate_stage2(response(job, [supplement("party")]), job)
        with self.assertRaises((TargetContextError, ValueError, TypeError)):
            validate_stage2(response(job, [supplement("scope", ("foreign-ref",))]), job)

    def test_no_context_catalog_means_grammar_and_host_allow_only_empty_supplements(self):
        job = stage2_job(context=False)
        grammar = build_grammar(job)
        self.assertEqual(grammar_slot_subsets(grammar), [()])
        self.assertIn('supplements ::= "[]"', grammar)
        self.assertEqual(validate_stage2(response(job, []), job)["anchors"][0]["supplements"], [])
        with self.assertRaises((TargetContextError, ValueError, TypeError)):
            validate_stage2(response(job, [supplement("scope")]), job)

    def test_primary_claim_remains_immutable_when_scope_is_added(self):
        job = stage2_job()
        checked = validate_stage2(response(job, [supplement("scope")]), job)
        self.assertEqual(checked["anchors"][0]["primary_claim"],
                         job["locked_anchors"][0]["primary_claim"])
        self.assertEqual(checked["anchors"][0]["supplements"][0]["slot"], "scope")
        self.assertFalse(checked["semantic_quality"] == "verified")


if __name__ == "__main__":
    unittest.main()
