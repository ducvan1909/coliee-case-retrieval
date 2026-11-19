"""End-to-end offline acceptance for CM4's terminal review path.

Uses the real Engine and live.run_loop with a local scripted transport. The
token counter is deliberately deterministic and synthetic; no provider or
Modal endpoint is called.
"""
from contextlib import contextmanager
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from pipeline_v2.experiments.context_manager_v2.cli import quote_for_paragraph

from pipeline_v2.agent_harness import RunIdentity, SourceExcerpt, ToolResult
from pipeline_v2.agent_harness.contracts import ModelReply
from pipeline_v2.experiments.context_manager_v2.engine import Engine
from pipeline_v2.experiments.context_manager_v2.live import run_loop


def count_tokens(body):
    return len(body) // 6 + 100


def source(case_id, text):
    raw = text.encode("utf-8")
    digest = sha256(raw).hexdigest()
    return SourceExcerpt(case_id, digest, (0, len(raw)), text, digest)


class TwoCandidateTools:
    fingerprint = "offline-terminal-fixture-v1"

    def __init__(self):
        self.a = source("A", "2012 SCC 12: procedural fairness requires notice and an opportunity to respond.")
        self.b = source("B", "A decision maker must provide notice and a meaningful opportunity to respond.")
        self.c = source("C", "The tribunal must give each party notice before deciding the application.")
        self.query_paragraphs = ({"handle": "p000001", "span_bytes": self.a.span_bytes},)

    def query_start(self):
        return ToolResult({"kind": "query_map", "items": []}, (self.a,)), self.a

    def open_query(self, args):
        return ToolResult({}, (self.a,))

    def verify_source(self, case_id, digest):
        return any(row.case_id == case_id and row.source_hash == digest for row in (self.a, self.b, self.c))

    def search_corpus(self, args):
        hits = []
        for rank, row in enumerate((self.b, self.c), start=1):
            hits.append({"case_id": row.case_id, "rank": rank,
                         "open_ref": {"case_id": row.case_id, "source_hash": row.source_hash,
                                      "passage_ids": [row.case_id + "-1"]}})
        return ToolResult({"hits": hits}, candidates=("B", "C"))

    def open_source(self, args):
        row = {"B": self.b, "C": self.c}[args["case_id"]]
        return ToolResult({"case_id": row.case_id}, (row,), (row.case_id,))

    def expand_source(self, args):
        return self.open_source(args)


class Trace:
    def __init__(self):
        self.rows = []

    def emit(self, name, **fields):
        self.rows.append((name, fields))

    @contextmanager
    def stage(self, name, **fields):
        self.emit(name, **fields)
        yield


class ScriptedTransport:
    """Choose valid actions from the actual per-turn schema and visible payload."""

    def __init__(self):
        self.calls = []
        self.receipts = []
        self.last_call_id = None
        self.repaired_b = False
        self.assessed = set()
        self.saw_paged_candidate = False
        self.saw_pending = False
        self.actions = []

    @staticmethod
    def _branch(schema, name):
        return next(row for row in schema["anyOf"]
                    if row["properties"]["action"]["const"] == name)

    def _action(self, name, args, schema):
        branch = self._branch(schema, name)
        props = branch["properties"]["args"]["properties"]
        required = branch["properties"]["args"].get("required", [])
        result = {}
        for key in required:
            spec = props[key]
            if key in args:
                result[key] = args[key]
            elif "enum" in spec:
                result[key] = spec["enum"][0]
            elif key in ("issue", "focus"):
                result[key] = "procedural fairness and notice"
            elif key == "source_proposition":
                result[key] = "The query concerns notice before a decision."
            elif key in ("reason", "claim"):
                result[key] = "The available excerpt supports the current review step."
            else:
                result[key] = "The current source evidence supports review."
        # Optional fields used to force a real pending assessment on B once.
        if name == "assess_case_link" and args.get("missing_evidence"):
            result["missing_evidence"] = args["missing_evidence"]
        return {"action": name, "args": result}

    def _select(self, body, schema):
        m6 = body["m6"]
        available = {row["name"] for row in body["available_tools"]}
        context = m6["cm_context"]
        if context["stage"] == "ready" and "search_cases_by_issue" in available:
            return self._action("search_cases_by_issue", {"anchor_quote": quote_for_paragraph(body)}, schema)
        if context["mode"] in ("results", "pool") and "open_retrieved_passage" in available:
            branch = self._branch(schema, "open_retrieved_passage")
            refs = branch["properties"]["args"]["properties"]["lead_ref"]["enum"]
            passages = m6["retrieved_passages"]
            unread_refs = [ref for ref in refs if passages[ref]["description"]["case_id"] not in self.assessed]
            if unread_refs:
                lead_ref = unread_refs[0]
                case_id = passages[lead_ref]["description"]["case_id"]
                if case_id == "C":
                    self.saw_paged_candidate = True
                return self._action("open_retrieved_passage", {"lead_ref": lead_ref}, schema)
        if "assess_case_link" in available:
            pairs = m6["pair_refs"]
            pair_ref = next(iter(pairs))
            case_id = pairs[pair_ref]["candidate_id"]
            if case_id == "B" and not self.repaired_b:
                self.saw_pending = True
                self.repaired_b = True
                return self._action("assess_case_link", {"pair_ref": pair_ref,
                    "missing_evidence": ["Need the surrounding attribution context before accepting this pair."]}, schema)
            self.assessed.add(case_id)
            return self._action("assess_case_link", {"pair_ref": pair_ref,
                "case_relation": "unknown", "passage_location": "bounded"}, schema)
        if context["stage"] == "missing_evidence" and context["candidate_id"] == "B":
            # The next pass is the repair assessment, with the explicit gap removed.
            self.assessed.add("B")
            pair_ref = next(iter(m6["pair_refs"]))
            return self._action("assess_case_link", {"pair_ref": pair_ref,
                "case_relation": "unknown", "passage_location": "bounded"}, schema)
        if context["stage"] == "assessed" and context["mode"] != "results":
            controls = m6["cm_page"]["controls"]
            return self._action("show_context_page", {"page_ref": controls["results"]}, schema)
        if context["mode"] == "results" and m6["cm_page"]["offset"] == 0:
            controls = m6["cm_page"]["controls"]
            return self._action("show_context_page", {"page_ref": controls["next"]}, schema)
        if "finish_case_review" in available:
            return self._action("finish_case_review", {"reason": "complete_policy"}, schema)
        raise AssertionError(f"No scripted route for context={context}, tools={sorted(available)}")

    def send_structured(self, body, request_id, schema):
        payload = json.loads(body)
        self.calls.append(payload)
        self.last_call_id = f"offline-call-{len(self.calls)}"
        self.receipts.append({"request_id": request_id, "call_id": self.last_call_id,
                              "submission_attempted": True})
        action = self._select(payload, schema)
        self.actions.append(action["action"])
        return ModelReply(action=json.dumps(action), input_tokens=count_tokens(body),
                          output_tokens=17, latency_ms=1.0)


class OfflineTerminalAcceptanceTests(unittest.TestCase):
    def make_engine(self, directory):
        tools = TwoCandidateTools()
        identity = RunIdentity("cm4-offline-terminal", "A", tools.a.source_hash,
            "fixture-candidates", "fixture-index", "fixture-profile", "fixture-model",
            "fixture-prompt", tools.fingerprint, "synthetic-counter")
        sources = {row.case_id: row for row in (tools.a, tools.b, tools.c)}
        return Engine(Path(directory) / "session", identity=identity, tools=tools,
            count_tokens=count_tokens, raw_reader=lambda case_id: sources[case_id].text.encode("utf-8"),
            execution_mode="live", run_binding={"fixture": "local only; no provider"}, page_size=1)

    def test_full_review_repairs_pending_pair_pages_to_second_candidate_and_completes(self):
        with TemporaryDirectory() as directory:
            engine = self.make_engine(directory)
            transport, trace = ScriptedTransport(), Trace()
            result = run_loop(engine, transport, trace, max_turns=12)
            state = engine.state()

            self.assertEqual(result["state"]["stop_reason"], "complete")
            self.assertTrue(transport.saw_pending)
            self.assertTrue(transport.saw_paged_candidate)
            self.assertEqual(transport.assessed, {"B", "C"})
            self.assertIn("show_context_page", transport.actions)
            self.assertIn("finish_case_review", transport.actions)
            self.assertEqual(set(state.candidates), {"B", "C"})
            self.assertEqual({row["candidate_id"] for row in state.assessments.values()}, {"B", "C"})
            self.assertFalse(state.pending_assessments)
            self.assertFalse(state.in_flight)
            self.assertIsNone(state.pending_action)
            self.assertIsNone(state.active_action)
            self.assertEqual(state.last_receipt["status"], "success")
            self.assertTrue(all(event.get("status") in ("success", "pending_evidence") for event in engine.events()
                                if event["kind"] == "action_result"))
            self.assertEqual(len([event for event in engine.events() if event["kind"] == "action_started"]),
                             len([event for event in engine.events() if event["kind"] == "action_result"]))
            self.assertEqual(state.final["stop_reason"], "complete")
            self.assertEqual(len(transport.calls), len([event for event in engine.events()
                             if event["kind"] == "request_result"]))
            self.assertTrue(all(event["status"] == "success" for event in engine.events()
                                if event["kind"] == "request_result"))

    def test_explicit_failure_finishes_cleanly_without_dangling_request_or_action(self):
        with TemporaryDirectory() as directory:
            engine = self.make_engine(directory)
            # An explicit controller failure remains a supported terminal path.
            class ControllerFailure(ScriptedTransport):
                def _select(self, body, schema):
                    return self._action("finish_case_review", {"reason": "failure"}, schema)

            transport, trace = ControllerFailure(), Trace()
            result = run_loop(engine, transport, trace, max_turns=2)
            state = engine.state()
            self.assertEqual(result["state"]["stop_reason"], "failure")
            self.assertEqual(len(transport.calls), 1)
            self.assertFalse(state.in_flight)
            self.assertIsNone(state.pending_action)
            self.assertIsNone(state.active_action)
            self.assertEqual(state.last_receipt["status"], "success")
            self.assertEqual(state.final["stop_detail"], "controller_stop")


if __name__ == "__main__":
    unittest.main()
