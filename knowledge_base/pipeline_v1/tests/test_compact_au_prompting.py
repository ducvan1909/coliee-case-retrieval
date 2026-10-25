"""Independent tests for compact AU prompts and offline semantic review packets.

These tests cover prompt/protocol boundaries. They do not establish that an AU
is legally or semantically correct.
"""
from __future__ import annotations

import hashlib
from html import unescape
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator

from knowledge_base.pipeline_v1.au_compact import prompting, review_packet, runner
from knowledge_base.pipeline_v1.au_compact.core import COMPACT_SCHEMA, CompactAUError


def _identity_value(value):
    """Normalize a public identity value for comparisons without prescribing shape."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


class CompactPromptingTests(unittest.TestCase):
    request = {
        "case_id": "013948",
        "request_id": "pair-013948-target-1",
        "expected_target_ids": ["at-target-1"],
        "spec": {"model": "local-test-model", "enable_thinking": False,
                 "caps": {"output_tokens": 800}},
    }
    rendered = (
        "<AU_COMPACT_REGION case=013948 request=pair-013948-target-1>\n"
        "<TARGET atom_id=sa-target span=0:24>\nThe court held the rule applies.\n</TARGET>\n"
        "<CONTEXT atom_id=sa-context span=25:54>\nThe record contains a related fact.\n</CONTEXT>\n"
        "</AU_COMPACT_REGION>\n"
    )

    @classmethod
    def setUpClass(cls):
        schema_path = Path(COMPACT_SCHEMA)
        cls.schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(cls.schema)
        cls.validator = Draft202012Validator(cls.schema)

    def _few_shot_outputs(self):
        """Read synthetic examples from the prompting module's public data."""
        examples = getattr(prompting, "FEW_SHOTS", None)
        if examples is None:
            examples = getattr(prompting, "EXAMPLES", None)
        self.assertIsNotNone(examples, "prompting must expose its synthetic few-shot examples")
        if isinstance(examples, dict):
            examples = list(examples.values())
        elif isinstance(examples, str):
            examples = [examples]
        outputs = []
        for example in examples:
            if isinstance(example, dict):
                output = example.get("output", example.get("response", example))
                if isinstance(output, str):
                    output = json.loads(output)
                outputs.append(output)
            elif isinstance(example, str):
                decoder = json.JSONDecoder()
                offset = 0
                while offset < len(example):
                    start = example.find("{", offset)
                    if start < 0:
                        break
                    try:
                        output, end = decoder.raw_decode(example, start)
                    except json.JSONDecodeError:
                        offset = start + 1
                        continue
                    if isinstance(output, dict) and {
                        "request_id", "target_id", "decision", "coverage_status", "aus",
                        "hard_negative_reason", "unresolved_reason",
                    }.issubset(output):
                        outputs.append(output)
                    offset = end
        self.assertTrue(outputs, "few-shot examples must expose machine-checkable JSON outputs")
        return outputs

    def _parsed_synthetic_examples(self):
        """Pair every JSON demonstration with its own request, target, and exact atoms."""
        text = prompting.FEW_SHOTS
        examples = []
        headers = list(re.finditer(r"(?m)^(?:\d+\.\s*)?Input request=(\S+) target=(\S+)\s*$", text))
        decoder = json.JSONDecoder()
        for index, header in enumerate(headers):
            end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
            section = text[header.end():end]
            output_marker = re.search(r"(?m)^Output:\s*$", section)
            self.assertIsNotNone(output_marker, f"synthetic example {header.group(1)} has no Output block")
            output_text = section[output_marker.end():]
            start = output_text.find("{")
            self.assertGreaterEqual(start, 0, f"synthetic example {header.group(1)} has no JSON output")
            output, _ = decoder.raw_decode(output_text, start)
            atom_text = section[:output_marker.start()].strip()
            atoms = {}
            for role, atom_id, start_char, end_char, body in re.findall(
                r"(?s)<(TARGET|CONTEXT)\s+atom_id=([^\s>]+) span=(\d+):(\d+)>\n(.*?)\n</\1>", atom_text
            ):
                parts = [(tag, int(start), int(end), unescape(quote))
                         for tag, start, end, quote in re.findall(
                             r"(?s)<(TARGET_BODY|CONTEXT_PADDING) span=(\d+):(\d+)>(.*?)</\1>", body)]
                atoms[atom_id] = {"role": role, "start_char": int(start_char), "end_char": int(end_char),
                                  "quote": "".join(part[3] for part in parts) if parts else unescape(body),
                                  "parts": parts}
            examples.append({"request_id": header.group(1), "target_id": header.group(2),
                             "atoms": atoms, "atom_text": atom_text, "output": output})
        return examples

    def test_v6_prompt_is_compact_and_synthetic_examples_are_supported_by_exact_atoms(self):
        prompt = prompting.build_prompt(self.request, self.rendered)
        examples = self._parsed_synthetic_examples()
        self.assertEqual(len(examples), 4, "v6 retains two positives and restores two negatives")
        self.assertEqual(prompting.PROMPT_VERSION, "au-compact-semantic-v6")
        fixed_prompt = prompting.INSTRUCTIONS + prompting.FEW_SHOTS + prompting._REQUEST_TEMPLATE
        self.assertLessEqual(len(fixed_prompt.encode("utf-8")), 6800, "fixed prompt budget excludes optional hint suffix and source")
        examples_text = prompting.FEW_SHOTS.casefold()
        self.assertNotIn("kos", examples_text)
        self.assertNotIn("gold", examples_text)
        actual_identifiers_and_source = (
            self.request["case_id"], self.request["request_id"], *self.request["expected_target_ids"],
            "sa-target", "sa-context", "The court held the rule applies.", "The record contains a related fact.",
        )
        for value in actual_identifiers_and_source:
            self.assertNotIn(value.casefold(), examples_text, f"real request/source leaked into examples: {value}")

        self.assertEqual(len({example["request_id"] for example in examples}), 4)
        self.assertEqual([example["output"]["decision"] for example in examples],
                         ["positive", "positive", "hard_negative", "hard_negative"])
        self.assertTrue(all(example["request_id"].startswith("syn-") for example in examples))
        self.assertTrue(all(example["target_id"].startswith("syn-") for example in examples))
        for example in examples:
            output = example["output"]
            with self.subTest(example=example["request_id"]):
                self.assertEqual(list(self.validator.iter_errors(output)), [])
                self.assertEqual(output["request_id"], example["request_id"])
                self.assertEqual(output["target_id"], example["target_id"])
                self.assertTrue(example["atoms"], "each example must include parseable target/context atoms")
                self.assertEqual(sum(atom["role"] == "TARGET" for atom in example["atoms"].values()), 1)
                self.assertTrue(all(atom_id.startswith("syn-") for atom_id in example["atoms"]))
                serialized = json.dumps(output, ensure_ascii=False).casefold()
                self.assertNotIn("kos", serialized)
                self.assertNotIn("gold", serialized)
                for au in output["aus"]:
                    self.assertTrue(set(au["evidence_ref_ids"]).issubset(example["atoms"]))
                    selected_quotes = " ".join(example["atoms"][atom_id]["quote"] for atom_id in au["evidence_ref_ids"])
                    self.assertTrue(selected_quotes.strip())
                self.assertIn(json.dumps(output, ensure_ascii=False, separators=(",", ":")), prompt)

        for example in examples:
            for au in example["output"]["aus"]:
                self.assertLessEqual(len(au["claim"]), 300)
                self.assertTrue(1 <= len(au["evidence_ref_ids"]) <= 3)
                self.assertTrue(any(example["atoms"][ref]["role"] == "TARGET"
                                    for ref in au["evidence_ref_ids"]))
        for forbidden in ("section 97", "113", "prra", "013948", "099980", "fortin"):
            self.assertNotIn(forbidden, examples_text)

    def test_v6_examples_preserve_scoped_exemption_and_primary_target_ownership(self):
        airfield, archive = self._parsed_synthetic_examples()[:2]
        exemption, refusal = airfield["output"]["aus"]
        self.assertEqual(airfield["output"]["decision"], "positive")
        self.assertEqual(exemption["speaker"], "statute")
        self.assertEqual(refusal["speaker"], "statute")
        self.assertEqual(exemption["evidence_ref_ids"], ["syn-a", "syn-b"])
        self.assertEqual(exemption["claim"],
                         "For cargo drones using quiet rotors at rural pads, no acoustic certificate for night landings is required.")
        self.assertEqual(refusal["evidence_ref_ids"], ["syn-a"])
        self.assertEqual(refusal["claim"],
                         "Under the Airfield Act, a night permit is refused if the inspector finds from beacon test results that the beacon fails inspection.")
        self.assertIn("if the inspector finds from beacon test results", airfield["atoms"]["syn-a"]["quote"])
        self.assertEqual(len(archive["output"]["aus"]), 1)
        holding = archive["output"]["aus"][0]
        self.assertEqual(holding["kind"], "holding")
        self.assertEqual(holding["speaker"], "current_court")
        self.assertEqual(holding["evidence_ref_ids"], ["syn-c"])
        self.assertEqual(holding["claim"],
                         "This archive's access suspension is unlawful because the member received no prior hearing.")
        self.assertIn("appoint custodians", archive["atoms"]["syn-d"]["quote"])
        self.assertNotIn("custodians", json.dumps(archive["output"]))

    def test_v6_examples_match_real_renderer_target_and_padding_spans(self):
        for example in self._parsed_synthetic_examples():
            with self.subTest(example=example["request_id"]):
                catalog = {"atoms": {atom_id: {"atom_id": atom_id, "start_char": atom["start_char"],
                           "end_char": atom["end_char"], "quote": atom["quote"],
                           "target_intersecting": atom["role"] == "TARGET"}
                           for atom_id, atom in example["atoms"].items()}}
                refs = []
                ordered = sorted(example["atoms"].values(), key=lambda atom: atom["start_char"])
                for left, right in zip(ordered, ordered[1:]):
                    self.assertLessEqual(left["end_char"], right["start_char"])
                for atom in example["atoms"].values():
                    self.assertEqual(len(atom["quote"]), atom["end_char"] - atom["start_char"])
                    if atom["role"] == "TARGET":
                        self.assertTrue(atom["parts"], "no bare legacy TARGET demonstrations")
                        cursor = atom["start_char"]
                        for tag, start, end, quote in atom["parts"]:
                            self.assertEqual(start, cursor)
                            self.assertEqual(end - start, len(quote))
                            cursor = end
                            if tag == "TARGET_BODY":
                                refs.append({"role": "target", "start_char": start, "end_char": end,
                                             "target_ids": [example["target_id"]]})
                        self.assertEqual(cursor, atom["end_char"])
                request = {"case_id": "synthetic", "request_id": example["request_id"],
                           "expected_target_ids": [example["target_id"]], "source_refs": refs}
                rendered = runner._render(request, catalog)
                self.assertIn(example["atom_text"], rendered)

    def test_v6_negative_examples_do_not_promote_context_or_force_semantic_minimum(self):
        party, citations = self._parsed_synthetic_examples()[2:]
        for example, reason in ((party, "party_argument_only"), (citations, "citation_without_proposition")):
            with self.subTest(reason=reason):
                self.assertEqual(example["output"]["aus"], [])
                self.assertEqual(example["output"]["hard_negative_reason"], reason)
                self.assertEqual(example["output"]["coverage_status"], "complete")
                self.assertIsNone(example["output"]["unresolved_reason"])
                self.assertTrue(any(atom["role"] == "CONTEXT" for atom in example["atoms"].values()))
        self.assertEqual(party["atoms"]["syn-e"]["parts"][0][3], "The tenant argues the fee is unlawful.")
        self.assertIn("The court requires notice", party["atoms"]["syn-f"]["quote"])
        self.assertEqual(citations["atoms"]["syn-g"]["parts"][0][3], "Cases cited: Elm v Oak, para. 8.")
        self.assertEqual(citations["atoms"]["syn-g"]["parts"][1][0], "CONTEXT_PADDING")
        self.assertIn("The court requires notice", citations["atoms"]["syn-g"]["parts"][1][3])
        self.assertIn("requires written consent", citations["atoms"]["syn-h"]["quote"])
        self.assertIn("Return only supported AUs, no duplicate paraphrases or forced count", prompting.INSTRUCTIONS)
        self.assertNotRegex(prompting.INSTRUCTIONS.casefold(), r"(?:at least|minimum|exactly)\s+[1-9]\s+(?:aus|authority units)")

    def test_v6_instructions_keep_ownership_qualification_and_attribution_guards(self):
        instructions = prompting.INSTRUCTIONS
        for guard in (
            "primary legal proposition must be in raw TARGET",
            "Only TARGET_BODY owns primary propositions",
            "CONTEXT_PADDING is context even inside TARGET",
            "never supply a new primary proposition",
            "shared topic, consequence or TARGET evidence ID does not establish ownership",
            "assessment type/purpose/scope",
            "exemption for a specified requirement is not exemption from all requirements",
            "Do not invert prerequisites",
            "rather than broaden",
            "Quoted statute uses speaker=statute",
            "court commentary uses current_court, not statute",
            "mere quotation does not prove court endorsement",
            "Use 1-3 necessary evidence IDs per AU",
            "no duplicate paraphrases or forced count",
            "Stay within 800 output tokens",
        ):
            with self.subTest(guard=guard):
                self.assertIn(guard, instructions)

    def test_prompt_preserves_target_context_roles_and_does_not_force_case_facts_to_negative(self):
        prompt = prompting.build_prompt(self.request, self.rendered)
        self.assertIn("<TARGET atom_id=sa-target", prompt)
        self.assertIn("<CONTEXT atom_id=sa-context", prompt)
        instructions = prompting.INSTRUCTIONS.casefold()
        self.assertRegex(instructions, r"target.{0,180}(legal proposition|legal rule|authority)")
        self.assertRegex(instructions, r"context.{0,220}(dependenc|condition|exception|limit|attribution)")
        self.assertTrue(re.search(r"(?:never|do not|must not).{0,100}(?:context.only|context).{0,80}(?:au|authority unit)", instructions))
        self.assertIn("The court held the rule applies.", prompt)
        self.assertIn("The record contains a related fact.", prompt)
        self.assertIn("do not reject a legitimate holding merely because it is case-specific", prompt.casefold())
        self.assertIn("a factual observation alone is not a holding", prompt.casefold())
        normalized = " ".join(prompt.casefold().split())
        forced_negative = (
            "always classify case facts as hard_negative",
            "all factual target atoms must be hard_negative",
            "never extract an au from a target that contains facts",
            "case facts can never support an authority unit",
        )
        for instruction in forced_negative:
            self.assertNotIn(instruction, normalized)

    def test_prompt_identity_tracks_instruction_and_few_shot_content(self):
        self.assertTrue(getattr(prompting, "PROMPT_VERSION", None))
        identity = prompting.prompt_identity()
        self.assertNotEqual(_identity_value(identity), "null")
        mutable_content = []
        for name in dir(prompting):
            upper = name.upper()
            value = getattr(prompting, name)
            if ("INSTRUCTION" in upper or "FEW_SHOT" in upper or "EXAMPLE" in upper) and isinstance(value, (str, list, tuple, dict)):
                mutable_content.append((name, value))
        instruction_names = [name for name, _ in mutable_content if "INSTRUCTION" in name.upper()]
        example_names = [name for name, _ in mutable_content if "FEW_SHOT" in name.upper() or "EXAMPLE" in name.upper()]
        self.assertTrue(instruction_names, "instruction content must be identifiable for identity regression")
        self.assertTrue(example_names, "few-shot content must be identifiable for identity regression")
        for name in (instruction_names[0], example_names[0]):
            original = getattr(prompting, name)
            changed = original + " identity-test" if isinstance(original, str) else [*original, "identity-test"] if isinstance(original, (list, tuple)) else {**original, "identity-test": True}
            with self.subTest(content=name), patch.object(prompting, name, changed):
                self.assertNotEqual(_identity_value(prompting.prompt_identity()), _identity_value(identity))

    def test_prompt_version_change_invalidates_identity_and_cache_key(self):
        request = {**self.request, "atom_binding": {"atom_map_relative_path": "atoms.json", "atom_map_sha256": "a" * 64,
                    "atom_map_cache_key": "b" * 64, "case_id": "013948", "source_hash": "c" * 64,
                    "segmenter_version": "test", "policy_sha256": "d" * 64}}
        cfg = {"url": "local", "model": "local-test-model", "enable_thinking": False}
        identity = prompting.prompt_identity()
        key = runner._key(request, "manifest-hash", cfg)
        with patch.object(prompting, "PROMPT_VERSION", prompting.PROMPT_VERSION + ".identity-test"):
            self.assertNotEqual(_identity_value(prompting.prompt_identity()), _identity_value(identity))
            self.assertNotEqual(key, runner._key(request, "manifest-hash", cfg))

    def test_prompt_identity_excludes_request_source_text(self):
        identity = prompting.prompt_identity()
        private_source = "CONFIDENTIAL SOURCE TEXT MUST NOT ENTER PROMPT IDENTITY"
        prompting.build_prompt(self.request, private_source)
        self.assertEqual(_identity_value(prompting.prompt_identity()), _identity_value(identity))
        self.assertNotIn(private_source, _identity_value(identity))

    def test_call_sends_prompt_without_changing_locked_protocol_fields(self):
        seen = []

        class Response:
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def read(self):
                return json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": "{}"}}], "usage": {}}).encode()

        def opener(req, **_kwargs):
            seen.append(json.loads(req.data))
            return Response()

        catalog = {"atoms": {
            "sa-target": {"target_intersecting": True},
            "sa-context": {"target_intersecting": False},
        }}
        grammar = "ROOT ::= unchanged-ebnf-contract"
        with patch.object(runner, "build_decoding", return_value={"ebnf": grammar}) as decode:
            runner._call({"url": "https://local.invalid", "token": "test-only", "model": "local-test-model",
                          "enable_thinking": False}, self.request, self.rendered, opener, catalog)
        payload = seen[0]
        self.assertEqual(payload["messages"][0]["content"], prompting.build_prompt(self.request, self.rendered))
        self.assertIn("<TARGET atom_id=sa-target", payload["messages"][0]["content"])
        self.assertIn("<CONTEXT atom_id=sa-context", payload["messages"][0]["content"])
        self.assertIn(self.request["request_id"], payload["messages"][0]["content"])
        self.assertIn(self.request["expected_target_ids"][0], payload["messages"][0]["content"])
        self.assertEqual(payload["model"], "local-test-model")
        self.assertEqual(payload["chat_template_kwargs"], {"enable_thinking": False})
        self.assertEqual(payload["ebnf"], grammar)
        self.assertEqual(payload["max_tokens"], 800)
        decode.assert_called_once_with(self.request["request_id"], self.request["expected_target_ids"][0],
                                       ["sa-target", "sa-context"], ["sa-target"], string_mode="bounded")

    def test_cache_key_changes_when_prompt_content_identity_changes(self):
        request = {**self.request, "atom_binding": {"atom_map_relative_path": "atoms.json", "atom_map_sha256": "a" * 64,
                    "atom_map_cache_key": "b" * 64, "case_id": "013948", "source_hash": "c" * 64,
                    "segmenter_version": "test", "policy_sha256": "d" * 64}}
        cfg = {"url": "local", "model": "local-test-model", "enable_thinking": False}
        before = runner._key(request, "manifest-hash", cfg)
        for name in ("INSTRUCTIONS", "FEW_SHOTS"):
            original = getattr(prompting, name)
            with self.subTest(content=name), patch.object(prompting, name, original + " cache identity change"):
                self.assertNotEqual(before, runner._key(request, "manifest-hash", cfg))


class CompactReviewPacketTests(unittest.TestCase):
    def setUp(self):
        self.source = "Target rule text. Context facts here."
        self.source_hash = hashlib.sha256(self.source.encode()).hexdigest()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.atom_root = Path(self.temp.name) / "atoms"
        relative = "cases/013948/atoms.json"
        atom_map = {
            "case_id": "013948", "source_hash": self.source_hash, "cache_key": "c" * 64,
            "segmenter_version": "s1", "policy_sha256": "p" * 64,
            "atoms": [
                {"atom_id": "sa-target", "case_id": "013948", "source_hash": self.source_hash,
                 "span": {"start_char": 0, "end_char": 17}},
                {"atom_id": "sa-context", "case_id": "013948", "source_hash": self.source_hash,
                 "span": {"start_char": 18, "end_char": len(self.source)}},
            ],
        }
        path = self.atom_root / relative
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(atom_map), encoding="utf-8")
        self.request = {
            "case_id": "013948", "source_hash": self.source_hash, "request_id": "review-r1",
            "expected_target_ids": ["at-target"],
            "source_refs": [{"role": "target", "start_char": 0, "end_char": 17, "target_ids": ["at-target"]},
                            {"role": "context", "start_char": 18, "end_char": len(self.source), "target_ids": []}],
            "atom_binding": {"atom_map_relative_path": relative, "atom_map_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                             "atom_map_cache_key": atom_map["cache_key"], "case_id": "013948", "source_hash": self.source_hash,
                             "segmenter_version": "s1", "policy_sha256": "p" * 64},
        }
        self.row = {
            "request": self.request, "status": "protocol_verified",
            "compact_response": {"request_id": "review-r1", "target_id": "at-target", "decision": "positive",
                                  "coverage_status": "complete", "aus": [{"kind": "holding", "claim": "A rule.",
                                  "evidence_ref_ids": ["sa-target", "missing-id"]}]},
        }

    def test_source_hash_mismatch_fails_closed(self):
        request = {**self.request, "source_hash": "0" * 64}
        row = {**self.row, "request": request}
        with patch.object(review_packet, "open_source", return_value=self.source):
            with self.assertRaisesRegex(CompactAUError, "source hash mismatch"):
                review_packet.build_packet({"request_ledger": [row]}, "unused", self.atom_root)

    def test_packet_preserves_exact_atoms_and_missing_refs_as_pending_review(self):
        with patch.object(review_packet, "open_source", return_value=self.source):
            packet = review_packet.build_packet({"request_ledger": [self.row]}, "unused", self.atom_root)
        row = packet["rows"][0]
        self.assertEqual(packet["review_status"], "pending")
        self.assertFalse(packet["semantic_gold"])
        self.assertFalse(packet["semantic_quality_claim"])
        self.assertEqual(row["protocol_status"], "protocol_verified")
        self.assertEqual(row["model_decision"], "positive")
        self.assertEqual(row["target_omission_review"], "pending")
        self.assertEqual(row["region_atoms"], [
            {"atom_id": "sa-target", "start_char": 0, "end_char": 17, "quote": self.source[0:17], "target_intersecting": True},
            {"atom_id": "sa-context", "start_char": 18, "end_char": len(self.source), "quote": self.source[18:], "target_intersecting": False},
        ])
        proposal = row["proposals"][0]
        self.assertEqual(proposal["selected_evidence"], [row["region_atoms"][0]])
        self.assertEqual(proposal["unknown_evidence_ids"], ["missing-id"])
        self.assertEqual(proposal["review_status"], "pending")
        self.assertIsNone(proposal["semantic_verdict"])


if __name__ == "__main__":
    unittest.main()
