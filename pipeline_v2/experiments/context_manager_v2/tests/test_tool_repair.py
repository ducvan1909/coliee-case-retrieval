"""CM4 tool contracts reject unsafe choices and allow one bounded correction."""
from copy import deepcopy
from hashlib import sha256
from json import loads
from tempfile import TemporaryDirectory
import unittest

from jsonschema import Draft202012Validator

from pipeline_v2.experiments.context_manager_v2.tests.view_helpers import canonical_ref, host_payload
from pipeline_v2.experiments.context_manager_v2.cli import quote_for_paragraph

from pipeline_v2.agent_harness import ModelReply, SourceExcerpt
from pipeline_v2.agent_harness.assessment import AssessmentStateError
from pipeline_v2.agent_harness import RunIdentity
from pipeline_v2.experiments.context_manager_v2.engine import Engine
from pipeline_v2.experiments.context_manager_v2.live import run_loop
from pipeline_v2.experiments.context_manager_v2.tests.test_offline_terminal import Trace, count_tokens
from pipeline_v2.tests.test_m6_adaptive import Tools


def branches(schema, action):
    return [row for row in schema["anyOf"] if row["properties"]["action"]["const"] == action]


def make_action(payload, schema, name, *, overrides=None):
    candidates = []
    for branch in branches(schema, name):
        properties = branch["properties"]["args"]["properties"]
        args = {}
        for key in branch["properties"]["args"].get("required", []):
            spec = properties[key]
            if key in (overrides or {}):
                args[key] = overrides[key]
            elif "enum" in spec:
                args[key] = spec["enum"][0]
            elif key in ("issue", "focus"):
                args[key] = "procedural fairness"
            elif key == "source_proposition":
                args[key] = "The query raises a notice requirement."
            elif key == "anchor_quote":
                args[key] = quote_for_paragraph(payload)
            elif key == "reason":
                args[key] = "Assess the relation using the displayed excerpts."
            else:
                args[key] = "The displayed excerpts leave this question unresolved."
        args.update(overrides or {})
        candidate = {"action": name, "args": args}
        candidates.append(candidate)
        if Draft202012Validator(schema).is_valid(candidate):
            return candidate
    return candidates[0]


def make_engine(directory, tools=None):
    tools = tools or Tools()
    identity = RunIdentity("tool-repair", "A", tools.a.source_hash,
        "fixture-candidates", "fixture-index", "fixture-profile", "fixture-model",
        "fixture-prompt", tools.fingerprint, "synthetic-counter")
    sources = {row.case_id: row for row in (tools.a, tools.b)}
    return Engine(directory, identity=identity, tools=tools, count_tokens=count_tokens,
        raw_reader=lambda case_id: sources[case_id].text.encode("utf-8"), execution_mode="offline")


def make_live_engine(directory):
    tools = Tools()
    identity = RunIdentity("tool-repair-live", "A", tools.a.source_hash,
        "fixture-candidates", "fixture-index", "fixture-profile", "fixture-model",
        "fixture-prompt", tools.fingerprint, "synthetic-counter")
    sources = {row.case_id: row for row in (tools.a, tools.b)}
    return Engine(directory, identity=identity, tools=tools, count_tokens=count_tokens,
        raw_reader=lambda case_id: sources[case_id].text.encode("utf-8"), execution_mode="live")


def excerpt(case_id, source_hash, text, start, end, components):
    raw = text.encode("utf-8")
    piece = raw[start:end].decode("utf-8")
    return SourceExcerpt(case_id, source_hash, (start, end), piece,
                         sha256(piece.encode("utf-8")).hexdigest(),
                         {"components": components}).to_record()


class ToolRepairTests(unittest.TestCase):
    def make_reading_engine(self, directory, tools=None):
        engine = make_engine(directory, tools)
        engine.step(lambda p: make_action(p["payload"], p["manifest"]["schema"], "search_cases_by_issue"))
        engine.step(lambda p: make_action(p["payload"], p["manifest"]["schema"], "read_case_passages"))
        return engine

    def test_no_valid_quote_chain_keeps_unknown_assessment_and_read_paths(self):
        with TemporaryDirectory() as directory:
            engine = self.make_reading_engine(directory)
            prepared = engine.prepare(admit=False)
            payload, schema = prepared["payload"], prepared["manifest"]["schema"]
            pair_ref = next(iter(payload["m6"]["pair_refs"]))
            options = payload["m6"].get("assessment_attribution_options", {}).get(pair_ref, [])

            self.assertFalse(any(row["role"] == "court" and row.get("type") == "adopted_reasoning"
                                 for row in options))
            self.assertFalse(any(row["role"] == "quoted_source" for row in options))
            self.assertTrue(any(row["role"] == "unknown" for row in options))
            self.assertTrue(branches(schema, "assess_case_link"))
            self.assertTrue(branches(schema, "record_missing_evidence"))

            action = make_action(payload, schema, "assess_case_link", overrides={
                "pair_ref": pair_ref, "case_relation": "unknown", "passage_location": "bounded",
                "speaker": {"role": "unknown"},
            })
            Draft202012Validator(schema).validate(action)

    def test_quote_container_enum_only_allows_its_matching_attribution(self):
        from pipeline_v2.experiments.uncapped_probe import policy

        with TemporaryDirectory() as directory:
            tools = Tools()
            text = "The court adopts the rule. X holding: ‘notice’. Y holding: ‘hearing’."
            raw = text.encode("utf-8")
            tools.b = SourceExcerpt("B", sha256(raw).hexdigest(), (0, len(raw)), text,
                                   sha256(raw).hexdigest())
            engine = self.make_reading_engine(directory, tools)
            prepared = engine.prepare(admit=False)
            payload = host_payload(prepared)
            a_ref = next(row["ref"] for row in payload["excerpts"] if row["case_id"] == "A")
            b_ref = next(row["ref"] for row in payload["excerpts"] if row["case_id"] == "B")

            def span(value):
                start = raw.index(value.encode("utf-8"))
                return start, start + len(value.encode("utf-8"))

            speaker_span = span("The court adopts the rule.")
            lead_x = span("X holding:")
            quote_x = span("‘notice’")
            lead_y = span("Y holding:")
            quote_y = span("‘hearing’")
            b_rows = [
                excerpt("B", tools.b.source_hash, text, *speaker_span, [{
                    "unit_id": "speaker", "span_bytes": list(speaker_span),
                    "unit_kind": "paragraph", "paragraph_role": "current_case",
                }]),
                excerpt("B", tools.b.source_hash, text, *lead_x, [{
                    "unit_id": "source_x", "span_bytes": list(lead_x),
                    "unit_kind": "paragraph", "paragraph_role": "current_case",
                }]),
                excerpt("B", tools.b.source_hash, text, *quote_x, [{
                    "unit_id": "quote_x", "span_bytes": list(quote_x),
                    "unit_kind": "paragraph", "paragraph_role": "quoted",
                    "attribution_unit_id": "source_x",
                    "role_evidence_refs": [{"span_bytes": list(lead_x)}],
                }]),
                excerpt("B", tools.b.source_hash, text, *lead_y, [{
                    "unit_id": "source_y", "span_bytes": list(lead_y),
                    "unit_kind": "paragraph", "paragraph_role": "current_case",
                }]),
                excerpt("B", tools.b.source_hash, text, *quote_y, [{
                    "unit_id": "quote_y", "span_bytes": list(quote_y),
                    "unit_kind": "paragraph", "paragraph_role": "quoted",
                    "attribution_unit_id": "source_y",
                    "role_evidence_refs": [{"span_bytes": list(lead_y)}],
                }]),
            ]
            payload["excerpts"] = [row for row in payload["excerpts"] if row["ref"] != b_ref] + b_rows
            payload["current_payload_source_refs"] = [a_ref, *(row["ref"] for row in b_rows)]
            base_tools, base_schema, _, pairs = policy.catalog(payload)
            branches_out = Engine._bind_assessment_sides(
                payload, deepcopy(base_tools), base_schema["anyOf"], pairs)
            schema = {"type": "object", "anyOf": branches_out}
            pair_ref = next(iter(pairs))
            options = payload["m6"]["assessment_attribution_options"][pair_ref]
            options_by_container = {option["container_refs"][0]: option for option in options
                                    if option["role"] == "court" and option.get("type") == "adopted_reasoning"
                                    and option.get("quote_chain_refs")}

            option_x = options_by_container[next(row["ref"] for row in b_rows
                                                 if row["provenance"]["components"][0].get("unit_id") == "quote_x")]
            option_y = options_by_container[next(row["ref"] for row in b_rows
                                                 if row["provenance"]["components"][0].get("unit_id") == "quote_y")]
            self.assertEqual(option_x["quote_chain_refs"], [b_rows[1]["ref"]])
            self.assertEqual(option_y["quote_chain_refs"], [b_rows[3]["ref"]])
            unknown_x = next(option for option in options if option["role"] == "unknown"
                             and option["container_refs"] == option_x["container_refs"]
                             and option.get("quote_chain_refs"))
            self.assertEqual(unknown_x["quote_chain_refs"], option_x["quote_chain_refs"])

            def assessment(option, chain):
                args = {"pair_ref": pair_ref, "case_relation": "unknown", "passage_location": "bounded",
                        "reason": "The displayed passage supports this attribution choice.",
                        "speaker": {"role": option["role"], "type": option["type"], "side": option["side"]},
                        "speaker_evidence_refs": option["speaker_refs"],
                        "container_refs": option["container_refs"], "quote_chain_refs": chain}
                return {"action": "assess_case_link", "args": args}

            valid_x = assessment(option_x, option_x["quote_chain_refs"])
            crossed_x = assessment(option_x, option_y["quote_chain_refs"])
            self.assertTrue(Draft202012Validator(schema).is_valid(valid_x))
            self.assertFalse(Draft202012Validator(schema).is_valid(crossed_x))

    def test_blank_reason_can_be_corrected_once_on_same_raw(self):
        with TemporaryDirectory() as directory:
            engine = self.make_reading_engine(directory)
            first = engine.prepare()
            payload = first["payload"]
            refs = {row["case_id"]: row["ref"] for row in payload["excerpts"]}
            pair_ref = next(iter(payload["m6"]["pair_refs"]))
            invalid = make_action(payload, first["manifest"]["schema"], "assess_case_link", overrides={
                "pair_ref": pair_ref, "case_relation": "unknown", "passage_location": "bounded",
                "reason": "    ",
            })
            Draft202012Validator(first["manifest"]["schema"]).validate(invalid)
            engine.reply(first["request_id"], invalid)

            state = engine.state()
            self.assertEqual(state.last_receipt["status"], "malformed")
            self.assertFalse(state.pending_action)
            self.assertFalse(state.active_assessments)
            self.assertEqual(state.usage()["requests"], 3)

            correction = engine.prepare()
            self.assertEqual(correction["status"], "ready")
            repair = correction["payload"]["last_action_feedback"].get("tool_repair")
            self.assertEqual(repair["code"], "blank_reason")
            self.assertEqual(repair["fields"], ["reason"])
            self.assertEqual([row["ref"] for row in correction["payload"]["excerpts"]],
                             [row["ref"] for row in payload["excerpts"]])
            self.assertEqual(correction["manifest"]["context"]["candidate_id"],
                             first["manifest"]["context"]["candidate_id"])

            repaired = deepcopy(invalid)
            repaired["args"].update(reason="The query case has relevant contextual evidence.",
                                    identity_support_choice="query case")
            Draft202012Validator(correction["manifest"]["schema"]).validate(repaired)
            engine.reply(correction["request_id"], repaired)
            engine.execute_pending()
            self.assertEqual(len(engine.state().active_assessments), 1)
            self.assertEqual(next(iter(engine.state().assessments.values()))["identity_support_refs"], [canonical_ref(first, refs["A"])])
            self.assertIsNone(engine.state().final)
            self.assertEqual(engine.state().usage()["requests"], 4)

    def test_repeated_same_invalid_value_stops_before_assessment_side_effect(self):
        with TemporaryDirectory() as directory:
            engine = self.make_reading_engine(directory)
            first = engine.prepare()
            pair_ref = next(iter(first["payload"]["m6"]["pair_refs"]))
            invalid = make_action(first["payload"], first["manifest"]["schema"], "assess_case_link", overrides={
                "pair_ref": pair_ref, "reason": "    ",
            })
            Draft202012Validator(first["manifest"]["schema"]).validate(invalid)
            engine.reply(first["request_id"], invalid)
            retry = engine.prepare()
            repeated = deepcopy(invalid)
            engine.reply(retry["request_id"], repeated)

            state = engine.state()
            self.assertEqual(state.final["stop_reason"], "no_progress")
            self.assertEqual(state.final["stop_detail"], "repeated_tool_input_rejection")
            self.assertFalse(state.pending_action)
            self.assertFalse(state.active_assessments)
            self.assertEqual(state.usage()["requests"], 4)

    def test_live_loop_uses_repair_feedback_then_completes(self):
        class RepairTransport:
            def __init__(self):
                self.calls = []
                self.receipts = []

            def send_structured(self, body, request_id, schema):
                payload = loads(body)
                available = {row['name'] for row in payload['available_tools']}
                feedback = payload['last_action_feedback']
                context = payload['m6']['cm_context']
                if context['stage'] == 'ready' and 'search_cases_by_issue' in available:
                    action = make_action(payload, schema, 'search_cases_by_issue')
                elif context['mode'] in ('results', 'pool') and 'open_retrieved_passage' in available:
                    action = make_action(payload, schema, 'open_retrieved_passage')
                elif 'tool_repair' in feedback:
                    pair_ref = next(iter(payload['m6']['pair_refs']))
                    action = make_action(payload, schema, 'assess_case_link', overrides={
                        'pair_ref': pair_ref, 'case_relation': 'unknown', 'passage_location': 'bounded',
                        'speaker': {'role': 'unknown'},
                    })
                elif 'assess_case_link' in available:
                    pair_ref = next(iter(payload['m6']['pair_refs']))
                    action = make_action(payload, schema, 'assess_case_link', overrides={
                        'pair_ref': pair_ref, 'case_relation': 'unknown', 'passage_location': 'bounded',
                        'reason': '    ',
                    })
                else:
                    action = make_action(payload, schema, 'finish_case_review',
                                         overrides={'reason': 'complete_policy'})
                Draft202012Validator(schema).validate(action)
                self.calls.append(action)
                self.receipts.append({'request_id': request_id, 'submission_attempted': True,
                                      'receipt': 'fake_transport'})
                return ModelReply(action=action, input_tokens=count_tokens(body), output_tokens=1,
                                  latency_ms=1.0)

        with TemporaryDirectory() as directory:
            engine = make_live_engine(directory)
            transport = RepairTransport()
            result = run_loop(engine, transport, Trace(), max_turns=8)
            state = engine.state()
            statuses = [row['status'] for row in engine.events() if row['kind'] == 'request_result']
            self.assertEqual(result['state']['stop_reason'], 'complete')
            self.assertEqual([row['action'] for row in transport.calls], [
                'search_cases_by_issue', 'open_retrieved_passage', 'assess_case_link',
                'assess_case_link', 'finish_case_review'])
            self.assertEqual(statuses, ['success', 'success', 'malformed', 'success', 'success'])
            self.assertEqual(len(state.active_assessments), 1)
            self.assertFalse(state.pending_action)
            self.assertFalse(state.in_flight)

    def test_validator_repair_is_retryable_without_refetching_or_losing_scope(self):
        """Exercise the execution-time provenance fallback while keeping refs current."""
        from unittest.mock import patch
        import pipeline_v2.agent_harness.harness as harness_module

        with TemporaryDirectory() as directory:
            tools = Tools()
            text = 'The court applies its own rule. In Case X it said: "notice is required."'
            raw = text.encode('utf-8')
            digest = sha256(raw).hexdigest()
            start_quote = raw.index(b'"')
            end_quote = len(raw)
            lead_start = raw.index(b'In Case X')
            tools.b = SourceExcerpt('B', digest, (0, len(raw)), text, digest, {'components': [
                {'unit_id': 'own-reasoning', 'span_bytes': [0, raw.index(b'.') + 1],
                 'unit_kind': 'paragraph', 'paragraph_role': 'current_case'},
                {'unit_id': 'source-x', 'span_bytes': [lead_start, start_quote],
                 'unit_kind': 'paragraph', 'paragraph_role': 'current_case'},
                {'unit_id': 'quote-x', 'span_bytes': [start_quote, end_quote],
                 'unit_kind': 'paragraph', 'paragraph_role': 'quoted', 'attribution_unit_id': 'source-x',
                 'role_evidence_refs': [{'span_bytes': [lead_start, start_quote]}]},
            ]})
            engine = self.make_reading_engine(directory, tools)
            first = engine.prepare()
            payload = first["payload"]
            pair_ref = next(iter(payload["m6"]["pair_refs"]))
            option = next(row for row in payload['m6']['assessment_attribution_options'][pair_ref]
                          if row['role'] == 'court' and row.get('type') == 'adopted_reasoning'
                          and row.get('quote_chain_refs'))
            bad = make_action(payload, first["manifest"]["schema"], "assess_case_link", overrides={
                "pair_ref": pair_ref, "case_relation": "unknown", "passage_location": "bounded",
                "speaker": {"role": option['role'], "type": option['type'], "side": option['side']},
                "speaker_evidence_refs": option['speaker_refs'],
                "container_refs": option['container_refs'],
                "quote_chain_refs": option['quote_chain_refs'],
            })
            Draft202012Validator(first["manifest"]["schema"]).validate(bad)
            engine.reply(first["request_id"], bad)

            original = harness_module.validate_assessment_state
            calls = 0

            def reject_once(*args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise AssessmentStateError("container_ref_lacks_matching_provenance")
                return original(*args, **kwargs)

            with patch.object(harness_module, "validate_assessment_state", side_effect=reject_once):
                engine.execute_pending()
                after_reject = engine.state()
                event = engine.events()[-1]
                self.assertEqual(event["kind"], "action_result")
                self.assertIn("cm_tool_repair", event)
                self.assertFalse(after_reject.active_assessments)

                retry = engine.prepare()
                self.assertEqual([row["ref"] for row in retry["payload"]["excerpts"]],
                                 [row["ref"] for row in payload["excerpts"]])
                self.assertEqual(retry["payload"]["last_action_feedback"]["tool_repair"]["code"],
                                 "container_ref_lacks_matching_provenance")
                fixed = make_action(retry["payload"], retry["manifest"]["schema"], "assess_case_link", overrides={
                    "pair_ref": pair_ref, "case_relation": "unknown", "passage_location": "bounded",
                    "speaker": {"role": "unknown"},
                })
                engine.reply(retry["request_id"], fixed)
                engine.execute_pending()
            self.assertEqual(len(engine.state().active_assessments), 1)
            self.assertIsNone(engine.state().final)


if __name__ == "__main__":
    unittest.main()
