import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib import error

from knowledge_base import __main__ as cli
from knowledge_base.adjudication import create_adjudication
from knowledge_base.config import api_config, budget_limit, settings
from knowledge_base.endpoint import (BudgetStop, Endpoint, HttpRejected,
                                     ModelProtocolError, ProviderUnavailable, UncertainRequest,
                                     confirm_local_environment_block, decode_model_json,
                                     reconcile_known_noninference)
from knowledge_base.pipeline import (_alias_review_sources, _invalid_verifier_review,
                                     _request_id, _statuses, _verifier_response,
                                     build_case)
from knowledge_base.prompts import (AU_VERIFIER, BRIEF_VERIFIER, FINALIZER,
                                    PROTOCOL_REPAIR, READER, SELECTION_RECOVERY,
                                    VERIFIER_PROTOCOL_REPAIR)
from knowledge_base.source import (load_source, prepare, source_handles,
                                   source_structure, structure_windows)
from knowledge_base.state import (apply_operations, apply_operations_independently,
                                  initial_state)


def config(**changes):
    value = {"url": "https://example.invalid/v1/chat/completions", "reader": "reader",
             "verifier": "verifier", "reserve": 1, "budget": 10, "headers": {},
             "key": "", "tokens": 100, "timeout": 1, "startup_wait": 900,
             "temperature": 0, "top_p": 0.9, "reasoning_effort": "none"}
    value.update(changes)
    return value


def source_fixture(text="Court rules. Party submits."):
    paragraphs, units = source_structure(text, "c" * 64)
    return paragraphs, units, {unit["source_id"]: unit for unit in units}


def ref(source_id, role="primary", attribution="current_court"):
    return {"source_id": source_id, "role": role, "attribution": attribution}


def brief(source_id, kind="facts", attribution="current_court"):
    return {"kind": kind, "source_refs": [ref(source_id, attribution=attribution)]}


def au(authority_id, response_id=None, treatment="unknown"):
    refs = [ref(authority_id, attribution="cited_authority")]
    if response_id:
        refs.append(ref(response_id, "court_response", "current_court"))
    return {"source_refs": refs,
            "treatment": {"value": treatment,
                          "authority_source_ids": [] if treatment == "unknown" else [authority_id],
                          "response_source_ids": [] if treatment == "unknown" else [response_id]}}


def au_outcome(payload, status="none_supported_in_read_source"):
    sources = [paragraph["source_id"] for paragraph in payload.get("opened_sources", [])]
    return {"status": status, "inspected_source_ids": sources[:1],
            "needed_window_ids": []}


def accepted_brief_review(item, evidence_id):
    return {"status": "accepted",
            "selection_check": {"status": "accepted", "reason": "Selection is complete.",
                                "evidence_source_ids": [evidence_id]},
            "kind_check": {"status": "accepted", "reason": "Kind matches the source.",
                           "evidence_source_ids": [evidence_id]},
            "attribution_checks": [{"source_id": ref["source_id"],
                "proposed_attribution": ref["attribution"],
                "observed_attribution": ref["attribution"], "status": "accepted",
                "reason": "Speaker is explicit.", "evidence_source_ids": [evidence_id]}
                for ref in item["source_refs"]], "request_source_ids": []}


def accepted_au_review(item, evidence_id):
    component = {"status": "accepted", "reason": "The selected source supports it.",
                 "evidence_source_ids": [evidence_id]}
    return {"status": "accepted", "selection_check": component,
            "relation_check": component, "treatment_check": component,
            "attribution_checks": [{"source_id": value["source_id"],
                "proposed_attribution": value["attribution"],
                "observed_attribution": value["attribution"], "status": "accepted",
                "reason": "Speaker is explicit.", "evidence_source_ids": [evidence_id]}
                for value in item["source_refs"]], "request_source_ids": []}


class SourceTests(unittest.TestCase):
    def test_sentence_addresses_preserve_repeated_unicode_crlf_crcrlf(self):
        text = "Same … câu.\r\n\r\nSame … câu.\r\nTail."
        paragraphs, units = source_structure(text, "a" * 64)
        sentences = [unit for unit in units if unit["unit_type"] == "sentence"]
        self.assertEqual(len(paragraphs), 2)
        repeated = [unit for unit in sentences if unit["text"] == "Same … câu."]
        self.assertEqual(len(repeated), 2)
        self.assertNotEqual(repeated[0]["source_id"], repeated[1]["source_id"])
        for unit in units:
            self.assertEqual(text[unit["start"]:unit["end"]], unit["text"])
        crcrlf_paragraphs, _ = source_structure("A.\r\r\nB.", "f" * 64)
        self.assertEqual([paragraph["text"] for paragraph in crcrlf_paragraphs],
                         ["A.", "B."])

    def test_single_crlf_does_not_split_a_paragraph_or_sentence(self):
        text = "Was it required under subsection 172(2) of the\r\nRegulations\r\n?"
        paragraphs, units = source_structure(text, "e" * 64)
        sentences = [unit for unit in units if unit["unit_type"] == "sentence"]
        self.assertEqual(len(paragraphs), 1)
        self.assertEqual(len(sentences), 1)
        self.assertEqual(sentences[0]["text"], text)

    def test_abbreviation_decimal_citation_fragment_and_long_sentence(self):
        text = ("Dr. Smith cited [2020] F.C. 4 at para. 3. Value was 1.5. "
                "<FRAGMENT_SUPPRESSED>. " + "x" * 2100)
        _, units = source_structure(text, "b" * 64)
        sentences = [unit for unit in units if unit["unit_type"] == "sentence"]
        self.assertTrue(any("Dr. Smith" in unit["text"] for unit in sentences))
        self.assertTrue(any("1.5" in unit["text"] for unit in sentences))
        self.assertTrue(any("<FRAGMENT_SUPPRESSED>" in unit["text"] for unit in sentences))
        self.assertTrue(all(len(unit["text"]) <= 2000 for unit in sentences))

    def test_fragment_marker_does_not_join_completed_sentence_to_heading(self):
        text = ("The decisions are remitted in accordance with these reasons.  "
                "<FRAGMENT_SUPPRESSED>  ORDER  <FRAGMENT_SUPPRESSED>  "
                "Application allowed.")
        _, units = source_structure(text, "9" * 64)
        sentences = [unit["text"] for unit in units if unit["unit_type"] == "sentence"]
        self.assertEqual(sentences[0], "The decisions are remitted in accordance with these reasons.")
        self.assertTrue(sentences[1].startswith("<FRAGMENT_SUPPRESSED>"))
        self.assertTrue(sentences[1].endswith("Application allowed."))

    def test_window_overlap_reuses_stable_ids(self):
        text = "one.\n\ntwo.\n\nthree.\n\nfour."
        paragraphs, units = source_structure(text, "d" * 64)
        windows = structure_windows(paragraphs, 8)
        self.assertGreater(len(windows), 1)
        self.assertTrue(set(windows[0]["source_ids"]) & set(windows[1]["source_ids"]))
        by_id = {unit["source_id"]: unit for unit in units}
        for window in windows:
            for source_id in window["source_ids"]:
                unit = by_id[source_id]
                self.assertEqual(text[unit["start"]:unit["end"]], unit["text"])

    def test_long_paragraphs_are_bounded_and_handles_are_deterministic(self):
        text = "x" * 4500
        paragraphs, units = source_structure(text, "7" * 64)
        self.assertTrue(all(len(paragraph["text"]) <= 2000 for paragraph in paragraphs))
        stable_to_handle, alias_to_stable = source_handles(units)
        self.assertEqual(len(stable_to_handle), len(units))
        self.assertEqual({alias_to_stable[handle] for handle in stable_to_handle.values()},
                         set(stable_to_handle))
        self.assertEqual(source_handles(units)[0], stable_to_handle)


class StateTests(unittest.TestCase):
    def setUp(self):
        self.paragraphs, self.units, self.source_map = source_fixture()
        self.opened = set(self.source_map)
        self.sentences = [unit["source_id"] for unit in self.units
                          if unit["unit_type"] == "sentence"]

    def test_brief_has_no_treatment_and_disposition_is_valid(self):
        item = brief(self.sentences[0], "disposition")
        state, events = apply_operations(initial_state(),
            [{"op": "add", "collection": "brief", "item": item}], self.opened,
            self.source_map, "c" * 64, "000001")
        self.assertEqual(len(events), 1)
        self.assertNotIn("treatment", state["items"]["000001:brief:000"])
        with self.assertRaisesRegex(ValueError, "unexpected_or_missing_item_fields"):
            apply_operations(initial_state(), [{"op": "add", "collection": "brief",
                "item": item | {"treatment": {"value": "unknown"}}}], self.opened,
                self.source_map, "c" * 64, "000001")

    def test_au_requires_primary_and_grounded_treatment(self):
        first, second = self.sentences[:2]
        state, _ = apply_operations(initial_state(),
            [{"op": "add", "collection": "aus", "item": au(first, second, "applies")}],
            self.opened, self.source_map, "c" * 64, "000001")
        self.assertEqual(state["items"]["000001:aus:000"]["treatment"]["value"], "applies")
        bad = au(first, second, "applies")
        bad["treatment"]["response_source_ids"] = []
        with self.assertRaisesRegex(ValueError, "treatment_requires_authority_and_response"):
            apply_operations(initial_state(), [{"op": "add", "collection": "aus", "item": bad}],
                             self.opened, self.source_map, "c" * 64, "000001")
        no_primary = au(first)
        no_primary["source_refs"][0]["role"] = "context"
        with self.assertRaisesRegex(ValueError, "au_requires_primary"):
            apply_operations(initial_state(), [{"op": "add", "collection": "aus",
                                                "item": no_primary}], self.opened,
                             self.source_map, "c" * 64, "000001")

        current_court_au = {"source_refs": [ref(first, attribution="current_court")],
            "treatment": {"value": "unknown", "authority_source_ids": [],
                          "response_source_ids": []}}
        state, _ = apply_operations(initial_state(),
            [{"op": "add", "collection": "aus", "item": current_court_au}],
            self.opened, self.source_map, "c" * 64, "000001")
        self.assertEqual(state["items"]["000001:aus:000"]["treatment"]["value"],
                         "unknown")

    def test_parent_child_overlap_unknown_unread_and_generated_content_rejected(self):
        paragraph = self.paragraphs[0]["source_id"]
        sentence = self.paragraphs[0]["sentence_ids"][0]
        overlap = {"kind": "facts", "source_refs": [ref(paragraph), ref(sentence)]}
        with self.assertRaisesRegex(ValueError, "parent_child_overlap"):
            apply_operations(initial_state(), [{"op": "add", "collection": "brief",
                                                "item": overlap}], self.opened,
                             self.source_map, "c" * 64, "000001")
        with self.assertRaisesRegex(ValueError, "source_unknown_or_unread"):
            apply_operations(initial_state(), [{"op": "add", "collection": "brief",
                "item": brief(self.sentences[1])}], {self.sentences[0]}, self.source_map,
                "c" * 64, "000001")
        with self.assertRaisesRegex(ValueError, "forbidden_field:claim"):
            apply_operations(initial_state(), [{"op": "add", "collection": "brief",
                "item": brief(sentence) | {"claim": "generated"}}], self.opened,
                self.source_map, "c" * 64, "000001")

    def test_update_remove_revision_and_independent_invalid_analysis(self):
        first, second = self.sentences[:2]
        state, _, rejected = apply_operations_independently(initial_state(), [
            {"op": "add", "collection": "brief", "item": brief(first)},
            {"op": "add", "collection": "brief", "item": brief(second, "analysis")},
        ], self.opened, self.source_map, "c" * 64, "013948")
        self.assertEqual(len(state["items"]), 1)
        self.assertEqual(rejected, [{"index": 1, "error_code": "invalid_brief_kind"}])
        item_id = "013948:brief:000"
        state["items"][item_id]["review"] = {"status": "accepted"}
        state, _ = apply_operations(state, [{"op": "update", "id": item_id,
            "revision": 1, "changes": {"kind": "posture"}}], self.opened,
            self.source_map, "c" * 64, "013948")
        self.assertIsNone(state["items"][item_id]["review"])
        state, _ = apply_operations(state, [{"op": "remove", "id": item_id,
            "revision": 2}], self.opened, self.source_map, "c" * 64, "013948")
        self.assertTrue(state["items"][item_id]["deleted"])

    def test_rejected_add_cannot_redirect_later_update_to_another_add(self):
        first, second = self.sentences[:2]
        operations = [
            {"op": "add", "collection": "brief", "item": brief(first, "analysis")},
            {"op": "add", "collection": "brief", "item": brief(second, "facts")},
            {"op": "update", "id": "013948:brief:000", "revision": 1,
             "changes": {"kind": "posture"}},
        ]
        state, _, rejected = apply_operations_independently(
            initial_state(), operations, self.opened, self.source_map, "c" * 64,
            "013948", allowed_target_ids=set())
        self.assertEqual(state["items"]["013948:brief:000"]["kind"], "facts")
        self.assertEqual([entry["error_code"] for entry in rejected],
                         ["invalid_brief_kind", "target_not_in_request_snapshot"])

    def test_agent_must_use_supplied_handle_but_kind_only_update_keeps_refs(self):
        source_id = self.sentences[0]
        aliases = {"S0000": source_id}
        with self.assertRaisesRegex(ValueError, "source_unknown_or_unread"):
            apply_operations(initial_state(), [{"op": "add", "collection": "brief",
                "item": brief(source_id)}], self.opened, self.source_map, "c" * 64,
                "000001", source_aliases=aliases)
        state, _ = apply_operations(initial_state(), [{"op": "add", "collection": "brief",
            "item": brief("S0000")}], self.opened, self.source_map, "c" * 64,
            "000001", source_aliases=aliases)
        state, _ = apply_operations(state, [{"op": "update", "id": "000001:brief:000",
            "revision": 1, "changes": {"kind": "posture"}}], self.opened,
            self.source_map, "c" * 64, "000001", source_aliases=aliases,
            allowed_target_ids={"000001:brief:000"})
        self.assertEqual(state["items"]["000001:brief:000"]["kind"], "posture")


class ContractAndStatusTests(unittest.TestCase):
    def test_v4_regression_fixtures_are_prompt_independent(self):
        fixture_root = Path(__file__).parent / "fixtures/v4"
        found_empty = [json.loads((fixture_root / name).read_text(encoding="utf-8"))["response"]
                       for name in ("013948_found_empty.json", "045155_found_empty.json")]
        self.assertTrue(all(value["operations"] == [] and
                            value["au_search_outcome"]["status"] == "found"
                            for value in found_empty))
        invalid_control = json.loads((fixture_root /
            "011904_reader_invalid_control.json").read_text(encoding="utf-8"))["response"]
        self.assertEqual(invalid_control["action"], "finalize")
        self.assertTrue(invalid_control["read_window_ids"])
        stable_review = json.loads((fixture_root /
            "013009_verifier_stable_ids.json").read_text(encoding="utf-8"))["response"]
        self.assertTrue(stable_review["selection_check"]["evidence_source_ids"][0].startswith("s-"))

    def test_prompts_are_complete_and_verifiers_are_separate(self):
        for prompt in (READER, FINALIZER):
            self.assertIn("BRIEF_ITEM", prompt)
            self.assertIn("AU_ITEM", prompt)
            self.assertNotIn("same ITEM contract", prompt)
        self.assertIn("current_items may be empty", FINALIZER)
        self.assertIn("no generated\nclaim exists", BRIEF_VERIFIER.lower())
        self.assertIn("kind_check", BRIEF_VERIFIER)
        self.assertNotIn("treatment_check", BRIEF_VERIFIER)
        self.assertIn("treatment_check", AU_VERIFIER)
        self.assertIn("not the physical author", BRIEF_VERIFIER)
        self.assertIn("do not reject it merely", AU_VERIFIER)
        self.assertIn("Translation by the Court", AU_VERIFIER)

    def test_verifier_derives_worst_status_and_requires_evidence_ids(self):
        _, units, source_map = source_fixture()
        source_id = next(unit["source_id"] for unit in units
                         if unit["unit_type"] == "sentence")
        item = {"source_refs": [ref(source_id)], "kind": "issues"}
        check = lambda status, reason: {"status": status, "reason": reason,
                                        "evidence_source_ids": [source_id]}
        response = {"status": "accepted",
                    "selection_check": check("accepted", "Selection is complete."),
                    "kind_check": check("needs_review", "The issue is not explicit."),
                    "attribution_checks": [{"source_id": source_id,
                        "proposed_attribution": "current_court",
                        "observed_attribution": "current_court", "status": "accepted",
                        "reason": "The court states this finding.",
                        "evidence_source_ids": [source_id]}], "request_source_ids": []}
        checked = _verifier_response(response, "brief", source_map, {source_id}, item)
        self.assertEqual(checked["status"], "needs_review")
        self.assertEqual(checked["reported_status"], "accepted")
        downgraded = _invalid_verifier_review(
            "brief", response, "invalid_verifier_evidence", item)
        self.assertEqual(downgraded["status"], "needs_review")
        self.assertFalse(downgraded["protocol_valid"])

        response["attribution_checks"] = []
        with self.assertRaisesRegex(ValueError, "must_cover"):
            _verifier_response(response, "brief", source_map, {source_id}, item)
        response["attribution_checks"] = [{"source_id": source_id,
            "proposed_attribution": "current_court", "observed_attribution": "current_court",
            "status": "accepted", "reason": "Speaker is explicit.",
            "evidence_source_ids": [source_id]}]
        response["selection_check"]["evidence_source_ids"] = []
        with self.assertRaisesRegex(ValueError, "invalid_verifier_evidence"):
            _verifier_response(response, "brief", source_map, {source_id}, item)

    def test_attribution_mismatch_cannot_remain_accepted(self):
        _, units, source_map = source_fixture()
        source_id = next(unit["source_id"] for unit in units
                         if unit["unit_type"] == "sentence")
        item = {"source_refs": [ref(source_id)], "kind": "facts"}
        response = accepted_brief_review(item, source_id)
        response["attribution_checks"][0]["observed_attribution"] = "party"
        checked = _verifier_response(response, "brief", source_map, {source_id}, item)
        self.assertEqual(checked["status"], "needs_review")
        self.assertEqual(checked["attribution_checks"][0]["status"], "needs_review")

    def test_empty_protocol_failure_removed_and_all_rejected_are_distinct(self):
        state = initial_state()
        rejection = [{"status": "unresolved", "original_operation": {"op": "add"}}]
        self.assertEqual(_statuses(state, rejection, "completed"),
                         ("failure", "protocol_failure", "protocol_failure"))
        self.assertEqual(_statuses(state, [], "completed")[1], "empty_output")
        state["history"].append({"op": "add"})
        self.assertEqual(_statuses(state, [], "completed")[1], "all_items_removed")
        state = initial_state()
        state["items"]["x"] = {"deleted": False, "review": {"status": "rejected"}}
        self.assertEqual(_statuses(state, [], "completed")[1], "all_items_rejected")

    def test_request_identity_changes_with_experiment_payload_and_source(self):
        row = {"case_id": "1", "source_hash": "a" * 64}
        first, _ = _request_id("pilot_v3", row, "reader", 0, {"x": 1})
        same, _ = _request_id("pilot_v3", row, "reader", 0, {"x": 1})
        changed, _ = _request_id("other", row, "reader", 0, {"x": 1})
        payload_changed, _ = _request_id("pilot_v3", row, "reader", 0, {"x": 2})
        self.assertEqual(first, same)
        self.assertNotEqual(first, changed)
        self.assertNotEqual(first, payload_changed)


class EndpointTests(unittest.TestCase):
    class Clock:
        def __init__(self): self.now, self.sleeps = 0.0, []
        def monotonic(self): return self.now
        def sleep(self, seconds): self.sleeps.append(seconds); self.now += seconds

    @staticmethod
    def http_error(code):
        return error.HTTPError("https://example.invalid", code, "test", None, None)

    def test_confirmed_local_block_release_is_explicit_and_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "ledger.json"
            ledger.write_text(json.dumps({"schema_version": 2, "budget_usd": None,
                "reserved_usd": 1.0, "calls": [{"request_id": "r", "logical_request_id": "r",
                    "status": "failed_or_uncertain", "error_type": "URLError",
                    "transport_attempts": [], "reserve_usd": 1.0}]}), encoding="utf-8")
            result = confirm_local_environment_block(ledger, "r", "HEAD reached provider")
            self.assertEqual(result["status"], "local_environment_blocked")
            persisted = json.loads(ledger.read_text(encoding="utf-8"))
            self.assertEqual(persisted["reserved_usd"], 0)
            with self.assertRaisesRegex(ValueError, "Only an unattempted"):
                confirm_local_environment_block(ledger, "r", "duplicate")

    def test_environment_and_unlimited_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("KB_READER_MODEL=from_file\n", encoding="utf-8")
            with patch.dict("os.environ", {"KB_READER_MODEL": "from_process"}):
                self.assertEqual(settings(path)["KB_READER_MODEL"], "from_process")
            with self.assertRaises(ValueError): api_config({})
        self.assertIsNone(budget_limit({"KB_BUDGET_USD": "unlimited"}))

    def test_reconciliation_idempotent(self):
        ledger = {"reserved_usd": 1.5, "calls": [
            {"request_id": "r1", "status": "failed_or_uncertain", "http_status": 503,
             "reserve_usd": .25},
            {"request_id": "r2", "status": "local_environment_blocked", "reserve_usd": .25},
            {"request_id": "r3", "status": "failed_or_uncertain", "reserve_usd": 1.0}]}
        self.assertEqual(reconcile_known_noninference(ledger), 2)
        self.assertEqual(reconcile_known_noninference(ledger), 0)
        self.assertEqual(ledger["reserved_usd"], 1.0)

    def test_malformed_json_is_not_rewritten_by_regex(self):
        malformed = ('{"operations":[{"op":"add","collection":"brief",'
                     '"item":{"kind":"facts","source_refs":[]}},"op":"remove",'
                     '"id":"x","revision":1}],"open_questions":[]}')
        with self.assertRaises(ModelProtocolError):
            decode_model_json(malformed)

    def test_cache_budget_timeout_and_uncertain_retry(self):
        response = {"choices": [{"finish_reason": "stop", "message": {"content": '{"ok":true}'}}],
                    "usage": {"total_tokens": 10}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = Endpoint(config(), root / "shared.json")
            cache = root / "response.json"
            with patch.object(client.opener, "open", return_value=io.BytesIO(json.dumps(response).encode())):
                self.assertEqual(client.complete("reader", "system", {}, request_id="r1",
                    metadata={}, cache_path=cache), {"ok": True})
            self.assertEqual(client.complete("reader", "system", {}, request_id="r1",
                metadata={}, cache_path=cache), {"ok": True})
            envelope = json.loads(cache.read_text(encoding="utf-8"))
            envelope["identity"]["model"] = "tampered"
            cache.write_text(json.dumps(envelope), encoding="utf-8")
            with self.assertRaises(UncertainRequest):
                client.complete("reader", "system", {}, request_id="r1",
                                metadata={}, cache_path=cache)
            envelope["identity"]["model"] = "reader"
            envelope["response"]["ok"] = False
            cache.write_text(json.dumps(envelope), encoding="utf-8")
            with self.assertRaises(UncertainRequest):
                client.complete("reader", "system", {}, request_id="r1",
                                metadata={}, cache_path=cache)
            cache.unlink()
            with self.assertRaises(UncertainRequest):
                client.complete("reader", "system", {}, request_id="r1", metadata={},
                                cache_path=cache)
            with patch.object(client.opener, "open", side_effect=TimeoutError):
                with self.assertRaises(RuntimeError):
                    client.complete("reader", "system", {}, request_id="r2", metadata={},
                                    cache_path=root / "r2.json")
            self.assertEqual(client.ledger["reserved_usd"], 2)

    def test_503_backoff_deadline_explicit_retry_and_http_rejection(self):
        response = {"choices": [{"finish_reason": "stop", "message": {"content": '{"ok":true}'}}]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            clock = self.Clock()
            client = Endpoint(config(), root / "shared.json", sleep_fn=clock.sleep,
                              clock_fn=clock.monotonic)
            with patch.object(client.opener, "open", side_effect=[self.http_error(503),
                    self.http_error(503), io.BytesIO(json.dumps(response).encode())]):
                client.complete("reader", "system", {}, request_id="r1", metadata={},
                                cache_path=root / "one.json")
            self.assertEqual(clock.sleeps, [2.0, 4.0])
            clock = self.Clock()
            unavailable = Endpoint(config(startup_wait=3), root / "second.json",
                                   sleep_fn=clock.sleep, clock_fn=clock.monotonic)
            with patch.object(unavailable.opener, "open", side_effect=[self.http_error(503)] * 3):
                with self.assertRaises(ProviderUnavailable):
                    unavailable.complete("reader", "system", {}, request_id="r2", metadata={},
                                         cache_path=root / "two.json")
            self.assertEqual(unavailable.ledger["reserved_usd"], 0)
            blocked = Endpoint(config(startup_wait=3), root / "second.json")
            with self.assertRaises(UncertainRequest):
                blocked.complete("reader", "system", {}, request_id="r2", metadata={},
                                 cache_path=root / "two.json")
            retry = Endpoint(config(startup_wait=3), root / "second.json", allow_provider_retry=True)
            with patch.object(retry.opener, "open", return_value=io.BytesIO(json.dumps(response).encode())):
                retry.complete("reader", "system", {}, request_id="r2", metadata={},
                               cache_path=root / "two.json")
            rejected = Endpoint(config(), root / "third.json")
            with patch.object(rejected.opener, "open", side_effect=self.http_error(401)) as opened:
                with self.assertRaises(HttpRejected):
                    rejected.complete("reader", "system", {}, request_id="r3", metadata={},
                                      cache_path=root / "three.json")
            self.assertEqual(opened.call_count, 1)


class PipelineTests(unittest.TestCase):
    def test_reader_processes_newly_opened_last_window_before_finalizer(self):
        reader_calls = 0
        class Fake:
            def complete(self, model, system, payload, **kwargs):
                nonlocal reader_calls
                if system == FINALIZER:
                    return {"operations": [], "open_questions": [],
                            "au_search_outcome": au_outcome(payload)}
                reader_calls += 1
                if reader_calls == 1:
                    return {"action": "read", "reason": "open remaining",
                            "read_window_ids": payload["unread_window_ids"][:1],
                            "operations": [], "open_questions": []}
                return {"action": "finalize", "reason": "processed new source",
                        "read_window_ids": [], "operations": [], "open_questions": []}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / "source.txt"
            source.write_text("one.\n\ntwo.\n\nthree.", encoding="utf-8")
            row = {"case_id": "013009", "source": str(source),
                   "source_hash": load_source(source)[1]}
            result = build_case(row, Fake(), {"reader": "r", "verifier": "v"},
                                5, 2, root / "pilot_v5/calibration/013009")
            self.assertEqual(reader_calls, 2)
            self.assertEqual(result["execution_status"], "completed")

    def test_found_without_au_gets_exactly_one_selection_recovery(self):
        calls = []
        class Fake:
            def complete(self, model, system, payload, **kwargs):
                calls.append(system)
                if system == FINALIZER:
                    return {"operations": [], "open_questions": [],
                            "au_search_outcome": au_outcome(payload, "found")}
                if system == SELECTION_RECOVERY:
                    sentence = payload["opened_sources"][0]["sentences"][0]
                    return {"operations": [{"op": "add", "collection": "aus",
                        "item": au(sentence["source_id"])}], "open_questions": [],
                        "au_search_outcome": au_outcome(payload, "found")}
                if system == AU_VERIFIER:
                    source_id = payload["item"]["source_refs"][0]["source_id"]
                    return accepted_au_review(payload["item"], source_id)
                return {"action": "finalize", "reason": "ready", "read_window_ids": [],
                        "operations": [], "open_questions": []}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / "source.txt"
            source.write_text("Court applies the rule.", encoding="utf-8")
            row = {"case_id": "013948", "source": str(source),
                   "source_hash": load_source(source)[1]}
            result = build_case(row, Fake(), {"reader": "r", "verifier": "v"},
                                100, 1, root / "pilot_v5/calibration/013948")
            self.assertEqual(calls.count(SELECTION_RECOVERY), 1)
            self.assertTrue(result["selection_recovery_attempted"])
            self.assertEqual(len(result["aus"]), 1)
            self.assertEqual(result["execution_status"], "completed")

    def test_found_without_au_remaining_inconsistent_stops(self):
        calls = []
        class Fake:
            def complete(self, model, system, payload, **kwargs):
                calls.append(system)
                if system in {FINALIZER, SELECTION_RECOVERY}:
                    return {"operations": [], "open_questions": [],
                            "au_search_outcome": au_outcome(payload, "found")}
                return {"action": "finalize", "reason": "ready", "read_window_ids": [],
                        "operations": [], "open_questions": []}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / "source.txt"
            source.write_text("One.", encoding="utf-8")
            row = {"case_id": "045155", "source": str(source),
                   "source_hash": load_source(source)[1]}
            result = build_case(row, Fake(), {"reader": "r", "verifier": "v"},
                                100, 1, root / "pilot_v5/calibration/045155")
            self.assertEqual(calls.count(SELECTION_RECOVERY), 1)
            self.assertEqual(result["execution_status"], "incomplete")
            self.assertEqual(result["semantic_status"], "inconsistent_output")
            self.assertNotEqual(result["verification_status"], "empty_output")

    def test_existing_au_and_found_does_not_duplicate_or_recover(self):
        calls = []
        class Fake:
            def complete(self, model, system, payload, **kwargs):
                calls.append(system)
                if system == FINALIZER:
                    return {"operations": [], "open_questions": [],
                            "au_search_outcome": au_outcome(payload, "found")}
                if system == AU_VERIFIER:
                    source_id = payload["item"]["source_refs"][0]["source_id"]
                    return accepted_au_review(payload["item"], source_id)
                sentence = payload["opened_sources"][0]["sentences"][0]
                return {"action": "finalize", "reason": "saved", "read_window_ids": [],
                    "operations": [{"op": "add", "collection": "aus",
                                    "item": au(sentence["source_id"])}],
                    "open_questions": []}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / "source.txt"
            source.write_text("One.", encoding="utf-8")
            row = {"case_id": "099980", "source": str(source),
                   "source_hash": load_source(source)[1]}
            result = build_case(row, Fake(), {"reader": "r", "verifier": "v"},
                                100, 1, root / "pilot_v5/calibration/099980")
            self.assertNotIn(SELECTION_RECOVERY, calls)
            self.assertEqual(len(result["aus"]), 1)

    def test_previous_review_addresses_are_converted_to_handles(self):
        _, units, _ = source_fixture()
        stable_to_handle, _ = source_handles(units)
        sentence_ids = [unit["source_id"] for unit in units if unit["unit_type"] == "sentence"]
        item = {"source_refs": [ref(sentence_ids[0])]}
        review = accepted_brief_review(item, sentence_ids[0])
        aliased = _alias_review_sources(review, stable_to_handle)
        self.assertEqual(aliased["selection_check"]["evidence_source_ids"],
                         [stable_to_handle[sentence_ids[0]]])
        self.assertEqual(aliased["attribution_checks"][0]["source_id"],
                         stable_to_handle[sentence_ids[0]])

    def test_finalize_envelope_repair_preserves_operations_and_opens_no_source(self):
        original_operations = []
        class Fake:
            def complete(self, model, system, payload, **kwargs):
                if system == PROTOCOL_REPAIR:
                    assert payload["invalid_response"]["operations"] == original_operations
                    return {"control_patch": {"read_window_ids": []}, "repairs": [
                            {"rejection_id": "envelope", "operation": {}}],
                            "recovered_operations": []}
                if system == FINALIZER:
                    return {"operations": [], "open_questions": [],
                            "au_search_outcome": au_outcome(payload)}
                return {"action": "finalize", "reason": "bad envelope",
                        "operations": original_operations, "open_questions": []}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / "source.txt"
            source.write_text("One.", encoding="utf-8")
            row = {"case_id": "099980", "source": str(source),
                   "source_hash": load_source(source)[1]}
            result = build_case(row, Fake(), {"reader": "r", "verifier": "v"},
                                100, 1, root / "pilot_v4/calibration/099980")
            self.assertEqual(result["counts"]["protocol_repairs"], 1)
            self.assertEqual(result["verification_status"], "empty_output")

    def test_empty_finalizer_full_contract_and_two_stagnant_reads(self):
        prompts = []
        class Fake:
            def complete(self, model, system, payload, **kwargs):
                prompts.append(system)
                if system == FINALIZER:
                    self.assert_empty = payload["current_items"] == []
                    return {"operations": [], "open_questions": [],
                            "au_search_outcome": au_outcome(payload)}
                return {"action": "read", "reason": "no progress", "read_window_ids": [],
                        "operations": [], "open_questions": []}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / "source.txt"
            source.write_text("one.\n\ntwo.\n\nthree.", encoding="utf-8")
            row = {"case_id": "045155", "source": str(source),
                   "source_hash": load_source(source)[1]}
            result = build_case(row, Fake(), {"reader": "reader", "verifier": "verifier"},
                                4, 6, root / "pilot_v4/calibration/045155")
            self.assertEqual(prompts.count(FINALIZER), 1)
            self.assertEqual(result["verification_status"], "empty_output")

    def test_protocol_repair_resolves_analysis_without_losing_valid_item(self):
        class Fake:
            def complete(self, model, system, payload, **kwargs):
                if system == PROTOCOL_REPAIR:
                    rejected = payload["rejected_operations"][0]
                    source_id = payload["opened_sources"][0]["source_id"]
                    return {"control_patch": {},
                            "repairs": [{"rejection_id": rejected["rejection_id"],
                        "operation": {"op": "add", "collection": "brief",
                                      "item": brief(source_id, "issues")}}],
                            "recovered_operations": []}
                if system == FINALIZER:
                    return {"operations": [], "open_questions": [],
                            "au_search_outcome": au_outcome(payload)}
                if system == BRIEF_VERIFIER:
                    source_id = payload["item"]["source_refs"][0]["source_id"]
                    return accepted_brief_review(payload["item"], source_id)
                sentences = [sentence for paragraph in payload["opened_sources"]
                             for sentence in paragraph["sentences"]]
                return {"action": "finalize", "reason": "enough", "read_window_ids": [],
                    "operations": [
                        {"op": "add", "collection": "brief", "item": brief(sentences[0]["source_id"])},
                        {"op": "add", "collection": "brief", "item": brief(sentences[-1]["source_id"], "analysis")}],
                    "open_questions": []}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / "source.txt"
            source.write_text("Fact one. Issue two.", encoding="utf-8")
            row = {"case_id": "013948", "source": str(source),
                   "source_hash": load_source(source)[1]}
            result = build_case(row, Fake(), {"reader": "reader", "verifier": "verifier"},
                                100, 1, root / "pilot_v4/calibration/013948")
            self.assertEqual(len(result["brief"]), 2)
            self.assertEqual(result["counts"]["protocol_rejected_resolved"], 1)
            self.assertEqual(result["protocol_status"], "valid")

    def test_valid_operations_are_checkpointed_before_protocol_repair_and_resume(self):
        class Fake:
            def __init__(self): self.repair_calls = 0
            def complete(self, model, system, payload, **kwargs):
                if system == PROTOCOL_REPAIR:
                    self.repair_calls += 1
                    if self.repair_calls == 1:
                        raise BudgetStop("stop before repair response")
                    rejected = payload["rejected_operations"][0]
                    source_id = payload["opened_sources"][0]["source_id"]
                    return {"control_patch": {}, "repairs": [{
                                "rejection_id": rejected["rejection_id"],
                                "operation": {"op": "add", "collection": "brief",
                                              "item": brief(source_id, "issues")}}],
                            "recovered_operations": []}
                if system == FINALIZER:
                    return {"operations": [], "open_questions": [],
                            "au_search_outcome": au_outcome(payload)}
                if system == BRIEF_VERIFIER:
                    source_id = payload["item"]["source_refs"][0]["source_id"]
                    return accepted_brief_review(payload["item"], source_id)
                sentences = [sentence for paragraph in payload["opened_sources"]
                             for sentence in paragraph["sentences"]]
                return {"action": "finalize", "reason": "enough", "read_window_ids": [],
                    "operations": [
                        {"op": "add", "collection": "brief", "item": brief(sentences[0]["source_id"])},
                        {"op": "add", "collection": "brief",
                         "item": brief(sentences[-1]["source_id"], "analysis")}],
                    "open_questions": []}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / "source.txt"
            source.write_text("Fact one. Issue two.", encoding="utf-8")
            row = {"case_id": "013948", "source": str(source),
                   "source_hash": load_source(source)[1]}
            output = root / "pilot_v4/calibration/013948"
            fake = Fake()
            first = build_case(row, fake, {"reader": "r", "verifier": "v"},
                               100, 1, output)
            self.assertEqual(first["execution_status"], "incomplete_budget")
            checkpoint = json.loads((output / "checkpoint.json").read_text(encoding="utf-8"))
            self.assertEqual(len(checkpoint["state"]["items"]), 1)
            self.assertIsNotNone(checkpoint["protocol_repair_pending"])
            second = build_case(row, fake, {"reader": "r", "verifier": "v"},
                                100, 1, output)
            self.assertEqual(second["execution_status"], "completed")
            self.assertEqual(len(second["brief"]), 2)
            self.assertEqual(sum(event["op"] == "add" for event in second["history"]), 2)

    def test_verifier_protocol_repair_is_recorded_and_resolved(self):
        class Fake:
            def complete(self, model, system, payload, **kwargs):
                if system == FINALIZER:
                    return {"operations": [], "open_questions": [],
                            "au_search_outcome": au_outcome(payload)}
                if system == BRIEF_VERIFIER:
                    return {"status": "accepted", "reason": "old aggregate shape"}
                if system == VERIFIER_PROTOCOL_REPAIR:
                    source_id = payload["item"]["source_refs"][0]["source_id"]
                    return {"review": accepted_brief_review(payload["item"], source_id)}
                sentence = payload["opened_sources"][0]["sentences"][0]
                return {"action": "finalize", "reason": "enough", "read_window_ids": [],
                        "operations": [{"op": "add", "collection": "brief",
                                        "item": brief(sentence["source_id"])}],
                        "open_questions": []}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / "source.txt"
            source.write_text("One.", encoding="utf-8")
            row = {"case_id": "099980", "source": str(source),
                   "source_hash": load_source(source)[1]}
            result = build_case(row, Fake(), {"reader": "r", "verifier": "v"},
                                100, 1, root / "pilot_v4/calibration/099980")
            self.assertEqual(result["verification_status"], "accepted")
            self.assertEqual(result["counts"]["verifier_protocol_errors"], 1)
            self.assertEqual(result["counts"]["verifier_protocol_errors_unresolved"], 0)

    def test_unresolved_malformed_add_is_protocol_failure_not_empty(self):
        class Fake:
            def complete(self, model, system, payload, **kwargs):
                if system == PROTOCOL_REPAIR:
                    return {"control_patch": {},
                            "repairs": [], "recovered_operations": []}
                if system == FINALIZER:
                    source_id = payload["opened_sources"][0]["source_id"]
                    return {"operations": [{"op": "add", "collection": "brief",
                        "item": {"kind": "facts", "source_refs": [source_id],
                                 "attribution": "source", "treatment": "extractive"}}],
                        "open_questions": [], "au_search_outcome": au_outcome(payload)}
                return {"action": "finalize", "reason": "done", "read_window_ids": [],
                        "operations": [], "open_questions": []}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / "source.txt"
            source.write_text("One.", encoding="utf-8")
            row = {"case_id": "011904", "source": str(source),
                   "source_hash": load_source(source)[1]}
            result = build_case(row, Fake(), {"reader": "reader", "verifier": "verifier"},
                                100, 1, root / "pilot_v4/calibration/011904")
            self.assertEqual(result["execution_status"], "incomplete")
            self.assertEqual(result["semantic_status"], "incomplete")
            self.assertEqual(result["counts"]["protocol_rejected_unresolved"], 1)

    def test_budget_stop_preserves_incomplete_draft(self):
        class Fake:
            def complete(self, model, system, payload, **kwargs):
                if system == BRIEF_VERIFIER: raise BudgetStop("limit")
                if system == FINALIZER:
                    return {"operations": [], "open_questions": [],
                            "au_search_outcome": au_outcome(payload)}
                sentence = payload["opened_sources"][0]["sentences"][0]
                return {"action": "finalize", "reason": "enough", "read_window_ids": [],
                        "operations": [{"op": "add", "collection": "brief",
                                        "item": brief(sentence["source_id"])}],
                        "open_questions": []}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / "source.txt"
            source.write_text("One.", encoding="utf-8")
            row = {"case_id": "1", "source": str(source), "source_hash": load_source(source)[1]}
            result = build_case(row, Fake(), {"reader": "r", "verifier": "v"}, 100, 1,
                                root / "pilot_v4/calibration/1")
            self.assertEqual(result["execution_status"], "incomplete_budget")
            self.assertEqual(result["counts"]["draft"], 1)


class CliAndSelectionTests(unittest.TestCase):
    def test_case_id_filter_preserves_requested_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"cases": [{"case_id": "1"}, {"case_id": "2"}],
                "splits": {"calibration": ["1", "2"], "evaluation": []}}), encoding="utf-8")
            experiment = root / "experiment"
            argv = ["knowledge_base", "run", "--manifest", str(manifest), "--split",
                    "calibration", "--experiment", str(experiment), "--execute",
                    "--reading-policy", "v10", "--case-id", "2", "--case-id", "1"]
            completed = {"execution_status": "completed", "semantic_status": "accepted"}
            with (patch("sys.argv", argv), patch.object(cli, "settings", return_value={}),
                  patch.object(cli, "api_config", return_value=config()),
                  patch.object(cli, "Endpoint", return_value=object()),
                  patch.object(cli, "SHARED_LEDGER", root / "shared.json"),
                  patch.object(cli, "SHARED_LEDGER_LOCK", root / "shared.lock"),
                  patch.object(cli, "LEGACY_LEDGER", root / "legacy.json"),
                  patch("knowledge_base.capability_v10.probe"),
                  patch.object(cli, "build_case", return_value=completed) as build):
                cli.main()
            self.assertEqual([call.args[0]["case_id"] for call in build.call_args_list],
                             ["2", "1"])

    def test_first_case_error_stops_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"cases": [{"case_id": "1"}, {"case_id": "2"}],
                "splits": {"calibration": ["1", "2"], "evaluation": []}}), encoding="utf-8")
            experiment = root / "experiment"
            argv = ["knowledge_base", "run", "--manifest", str(manifest), "--split",
                    "calibration", "--experiment", str(experiment), "--execute",
                    "--reading-policy", "v10"]
            with (patch("sys.argv", argv), patch.object(cli, "settings", return_value={}),
                  patch.object(cli, "api_config", return_value=config()),
                  patch.object(cli, "Endpoint", return_value=object()),
                  patch.object(cli, "SHARED_LEDGER", root / "shared.json"),
                  patch.object(cli, "SHARED_LEDGER_LOCK", root / "shared.lock"),
                  patch.object(cli, "LEGACY_LEDGER", root / "legacy.json"),
                  patch("knowledge_base.capability_v10.probe"),
                  patch.object(cli, "build_case", side_effect=RuntimeError("stop")) as build):
                with self.assertRaises(SystemExit): cli.main()
            self.assertEqual(build.call_count, 1)
            self.assertFalse((experiment / "calibration/2").exists())

    def test_incomplete_case_stops_batch_with_failure_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"cases": [{"case_id": "1"}, {"case_id": "2"}],
                "splits": {"calibration": ["1", "2"], "evaluation": []}}), encoding="utf-8")
            experiment = root / "experiment"
            argv = ["knowledge_base", "run", "--manifest", str(manifest), "--split",
                    "calibration", "--experiment", str(experiment), "--execute",
                    "--reading-policy", "v10"]
            incomplete = {"execution_status": "incomplete", "output_status": "incomplete"}
            with (patch("sys.argv", argv), patch.object(cli, "settings", return_value={}),
                  patch.object(cli, "api_config", return_value=config()),
                  patch.object(cli, "Endpoint", return_value=object()),
                  patch.object(cli, "SHARED_LEDGER", root / "shared.json"),
                  patch.object(cli, "SHARED_LEDGER_LOCK", root / "shared.lock"),
                  patch.object(cli, "LEGACY_LEDGER", root / "legacy.json"),
                  patch("knowledge_base.capability_v10.probe"),
                  patch.object(cli, "build_case", return_value=incomplete) as build):
                with self.assertRaises(SystemExit) as raised:
                    cli.main()
            self.assertEqual(raised.exception.code, 2)
            self.assertEqual(build.call_count, 1)
            self.assertFalse((experiment / "calibration/2").exists())

    def test_selection_disjoint_and_reproducible(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / "kos/cases").mkdir(parents=True)
            (root / "sources").mkdir()
            for number in range(30):
                (root / f"kos/cases/{number:06d}").mkdir()
                (root / f"sources/{number:06d}.txt").write_text("x" * (number + 1))
            first = prepare(root / "kos", root / "sources", root / "a.json")
            second = prepare(root / "kos", root / "sources", root / "b.json")
            self.assertEqual(first, second)
            self.assertEqual(len(first["splits"]["evaluation"]), 20)
            self.assertFalse(set(first["splits"]["calibration"]) &
                             set(first["splits"]["evaluation"]))

    def test_adjudication_export_is_pending_not_gold(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); case_dir = root / "pilot_v3/calibration/1"
            case_dir.mkdir(parents=True)
            case = {"case_id": "1", "source": "source.txt", "source_hash": "a" * 64,
                "brief": [{"id": "1:brief:000", "revision": 1,
                    "collection": "brief", "kind": "facts",
                    "source_refs": [ref("s-stable")]}], "aus": []}
            (case_dir / "case.json").write_text(json.dumps(case), encoding="utf-8")
            destination = root / "worksheet.json"
            create_adjudication(root / "pilot_v3", destination)
            worksheet = json.loads(destination.read_text(encoding="utf-8"))
            self.assertEqual(worksheet["status"], "pending_adjudication")
            self.assertEqual(worksheet["cases"][0]["items"][0]["components"][0]
                             ["adjudication"], "pending")


if __name__ == "__main__":
    unittest.main()
