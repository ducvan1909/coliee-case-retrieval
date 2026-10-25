import hashlib
import json
import copy
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError, URLError

from jsonschema import Draft202012Validator

from knowledge_base.pipeline_v1.au_compact.constraint_suite_probe import (
    build_cases,
    constraint_suite_probe,
)
from knowledge_base.pipeline_v1.au_compact.core import (
    COMPACT_SCHEMA,
    COMPACT_TRANSPORT_SCHEMA,
)


def _schema(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


FULL_SCHEMA = _schema(COMPACT_SCHEMA)
TRANSPORT_SCHEMA = _schema(COMPACT_TRANSPORT_SCHEMA)
FULL_VALIDATOR = Draft202012Validator(FULL_SCHEMA)
TRANSPORT_VALIDATOR = Draft202012Validator(TRANSPORT_SCHEMA)
CONSTRAINT_KEYWORDS = {
    "required",
    "type",
    "enum",
    "const",
    "minLength",
    "maxLength",
    "minItems",
    "maxItems",
    "uniqueItems",
    "additionalProperties",
    "allOf",
    "if",
    "then",
    "else",
}


def _constraint_targets(schema):
    """Return (keyword, instance path) pairs reachable in the current schema."""
    found = set()
    visited = set()

    def visit(node, path):
        if not isinstance(node, dict):
            return
        marker = (id(node), tuple(path))
        if marker in visited:
            return
        visited.add(marker)
        for keyword in CONSTRAINT_KEYWORDS.intersection(node):
            found.add((keyword, tuple(path)))
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            visit(schema["$defs"][ref.rsplit("/", 1)[1]], path)
        for name, child in node.get("properties", {}).items():
            visit(child, (*path, name))
        items = node.get("items")
        if isinstance(items, dict):
            visit(items, (*path, 0))
        for keyword in ("allOf", "anyOf", "oneOf"):
            for child in node.get(keyword, []):
                visit(child, path)
        for keyword in ("if", "then", "else", "not"):
            if isinstance(node.get(keyword), dict):
                visit(node[keyword], path)

    visit(schema, ())
    return found


def _enum_targets(schema):
    found = []
    visited = set()

    def visit(node, path):
        if not isinstance(node, dict) or (id(node), tuple(path)) in visited:
            return
        visited.add((id(node), tuple(path)))
        if isinstance(node.get("enum"), list):
            found.append((tuple(path), node["enum"]))
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            visit(schema["$defs"][ref.rsplit("/", 1)[1]], path)
        for name, child in node.get("properties", {}).items():
            visit(child, (*path, name))
        if isinstance(node.get("items"), dict):
            visit(node["items"], (*path, 0))
        for keyword in ("allOf", "anyOf", "oneOf"):
            for child in node.get(keyword, []):
                visit(child, path)
        for keyword in ("if", "then", "else", "not"):
            if isinstance(node.get(keyword), dict):
                visit(node[keyword], path)

    visit(schema, ())
    return found


def _at_path(value, path):
    for component in path:
        value = value[component]
    return value


def _stable(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class FakeHTTP:
    def __init__(self, content, *, finish_reason="stop", usage=None):
        self.body = {
            "choices": [{"finish_reason": finish_reason, "message": {"content": content}}],
            "usage": usage,
        }

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.body).encode("utf-8")


class ConstraintSuiteProbeTests(unittest.TestCase):
    cfg = {
        "url": "https://probe.invalid/v1/chat/completions",
        "token": "probe-secret",
        "model": "test-model",
        "enable_thinking": False,
        "timeout": 1,
        "max_tokens": 128,
    }
    repaired_valid = {
        "request_id": "probe-request",
        "target_id": "probe-target",
        "decision": "positive",
        "coverage_status": "complete",
        "aus": [{
            "kind": "holding",
            "other_kind": None,
            "claim": "A valid repaired authority unit.",
            "evidence_ref_ids": ["sa-target"],
            "speaker": "current_court",
            "attribution_role": "proposition",
            "needs_context": [],
        }],
        "hard_negative_reason": None,
        "unresolved_reason": None,
    }

    @classmethod
    def setUpClass(cls):
        cls.cases = build_cases()
        cls.by_id = {case["case_id"]: case for case in cls.cases}

    def test_catalog_is_deterministic_and_exhaustively_maps_schema_constraints(self):
        self.assertEqual(build_cases(), self.cases)
        self.assertTrue(self.cases)
        self.assertEqual(len(self.by_id), len(self.cases))
        self.assertTrue(all(case["case_id"] and case["mode"] in {"valid", "adversarial"} for case in self.cases))

        # The independent cases must actually satisfy their declared validity,
        # against both the host contract and the exact production transport schema.
        for case in self.cases:
            value = case["requested_value"]
            self.assertEqual(not list(TRANSPORT_VALIDATOR.iter_errors(value)), case["expected_transport_valid"], case["case_id"])
            self.assertEqual(not list(FULL_VALIDATOR.iter_errors(value)), case["expected_full_valid"], case["case_id"])

        catalog_targets = {(case["keyword"], tuple(case["path"])) for case in self.cases}
        required_targets = _constraint_targets(FULL_SCHEMA) | _constraint_targets(TRANSPORT_SCHEMA)
        missing_targets = sorted(required_targets - catalog_targets, key=repr)
        self.assertEqual(missing_targets, [], f"schema constraints without a case: {missing_targets}")

        # Every declared enum member must have a valid control that asks for that
        # value at the exact constrained instance path. Invalid mutations at that
        # path must be outside the enum; a generic valid response cannot stand in.
        enum_contracts = {
            (tuple(path), _stable(value))
            for schema in (FULL_SCHEMA, TRANSPORT_SCHEMA)
            for path, values in _enum_targets(schema)
            for value in values
        }
        valid_enum_values = {
            (tuple(case["path"]), _stable(_at_path(case["requested_value"], case["path"])))
            for case in self.cases
            if case["mode"] == "valid" and case["keyword"] == "enum"
        }
        self.assertFalse(enum_contracts - valid_enum_values, f"enum values without valid controls: {enum_contracts - valid_enum_values}")
        for path, choices in _enum_targets(FULL_SCHEMA) + _enum_targets(TRANSPORT_SCHEMA):
            mutations = [
                case for case in self.cases
                if case["mode"] == "adversarial" and case["keyword"] == "enum" and tuple(case["path"]) == tuple(path)
            ]
            self.assertTrue(mutations, f"enum path has no adversarial value: {path}")
            allowed = {_stable(value) for value in choices}
            self.assertTrue(any(_stable(_at_path(case["requested_value"], path)) not in allowed for case in mutations), path)

        with tempfile.TemporaryDirectory() as folder:
            report = constraint_suite_probe({}, folder, execute=False)
        coverage = report["coverage_manifest"]
        self.assertEqual(report["status"], "planned")
        self.assertEqual(report["case_count"], len(self.cases))
        self.assertEqual(coverage["full_schema_sha256"], hashlib.sha256(Path(COMPACT_SCHEMA).read_bytes()).hexdigest())
        self.assertEqual(coverage["transport_schema_sha256"], hashlib.sha256(Path(COMPACT_TRANSPORT_SCHEMA).read_bytes()).hexdigest())
        self.assertEqual(coverage["uncovered_constraints"], [])
        serialized = json.dumps(coverage, sort_keys=True)
        for case in self.cases:
            self.assertIn(case["case_id"], serialized)

        self.assertTrue(any(c["mode"] == "valid" for c in self.cases))
        self.assertTrue(any(c["mode"] == "adversarial" for c in self.cases))
        self.assertTrue(any(c["scope"] == "host_only" for c in self.cases))
        self.assertTrue(any(c["scope"] == "schema_only" for c in self.cases))
        self.assertTrue(any(c["keyword"] == "required" for c in self.cases))
        self.assertTrue(any(c["keyword"] == "additionalProperties" for c in self.cases))
        self.assertTrue(any(c["keyword"] == "enum" for c in self.cases))
        self.assertTrue(any(c["keyword"] == "uniqueItems" for c in self.cases))
        self.assertTrue(any(c["keyword"] in {"if", "then", "else", "allOf"} for c in self.cases))

        # Schema-valid challenges outside the fixed two-atom catalog are explicitly
        # schema-only; host identity/evidence constraints must not be called decoding guarantees.
        host_only = [c for c in self.cases if c["scope"] == "host_only"]
        self.assertTrue(any(c["keyword"] == "request_id" for c in host_only))
        self.assertTrue(any(c["keyword"] == "target_id" for c in host_only))
        host_ids = {c["case_id"] for c in host_only}
        self.assertTrue({
            "host-request_id",
            "host-target_id",
            "host-evidence-unknown",
            "host-evidence-outside-region",
            "host-evidence-context-only",
        }.issubset(host_ids))
        for case in host_only:
            self.assertTrue(case["expected_transport_valid"], case["case_id"])
            self.assertFalse(case["expected_host_valid"], case["case_id"])
            self.assertTrue(case["expected_full_valid"], case["case_id"])

        # Boundary-valid controls use their own expected identity values; they
        # must stay host-valid even when an ID/evidence string is at schema bounds.
        for case in self.cases:
            if case["mode"] == "valid":
                self.assertTrue(case["expected_transport_valid"], case["case_id"])
                self.assertTrue(case["expected_full_valid"], case["case_id"])
                if case["scope"] != "schema_only":
                    self.assertTrue(case["expected_host_valid"], case["case_id"])

        # At least a valid control and one adversary per enum member ensure a generic
        # schema-valid reply cannot falsely claim the whole enum family was exercised.
        self.assertTrue(any(c["mode"] == "valid" and c["keyword"] == "enum" for c in self.cases))

    def test_offline_plan_writes_report_without_touching_opener_or_exposing_token(self):
        with tempfile.TemporaryDirectory() as folder:
            report = constraint_suite_probe(
                self.cfg,
                folder,
                opener=lambda *_args, **_kwargs: self.fail("offline plan must not call provider"),
            )
            saved = json.loads((Path(folder) / "constraint_suite_probe.json").read_text(encoding="utf-8"))
        self.assertEqual(report, saved)
        self.assertEqual(report["status"], "planned")
        self.assertEqual(report["requests_sent"], 0)
        self.assertEqual(report["case_count"], len(self.cases))
        self.assertNotIn(self.cfg["token"], json.dumps(report))
        self.assertLessEqual(report["budget"]["max_output_tokens"], self.cfg["max_tokens"] * report["case_count"])

    def _echo_opener(self, responses=None, *, calls=None):
        responses = responses or {}
        calls = calls if calls is not None else []

        def opener(request, **_kwargs):
            payload = json.loads(request.data)
            calls.append(payload)
            self.assertEqual(payload["response_format"]["json_schema"]["schema"], TRANSPORT_SCHEMA)
            self.assertTrue(payload["response_format"]["json_schema"]["strict"])
            prompt = "\n".join(m["content"] for m in payload["messages"] if isinstance(m.get("content"), str))
            marker = "Constraint test case "
            case_id = prompt.split(marker, 1)[1].split(".", 1)[0]
            matched = self.by_id.get(case_id)
            self.assertIsNotNone(matched, "prompt must identify the catalog case")
            reply = responses.get(matched["case_id"], matched["requested_value"])
            if isinstance(reply, Exception):
                raise reply
            if isinstance(reply, tuple):
                content, finish_reason = reply
                return FakeHTTP(content, finish_reason=finish_reason, usage={"total_tokens": 7})
            return FakeHTTP(json.dumps(reply), usage={"prompt_tokens": 4, "completion_tokens": 3, "total_tokens": 7})

        return opener, calls

    def _repaired(self, case):
        value = copy.deepcopy(self.repaired_valid)
        requested = case["requested_value"]
        decision = requested.get("decision") if isinstance(requested, dict) else None
        if decision == "hard_negative":
            value.update(decision="hard_negative", aus=[], hard_negative_reason="other")
        elif decision == "unresolved":
            value.update(decision="unresolved", aus=[], unresolved_reason="other")
        elif (decision == "positive" and isinstance(requested.get("aus"), list) and requested["aus"]
              and isinstance(requested["aus"][0], dict)):
            requested_kind = requested["aus"][0].get("kind")
            if isinstance(requested_kind, str) and requested_kind in {"holding", "standard_of_review", "statutory_hook", "procedural_rule", "fact_pattern_rule", "foreign_law", "other", "unresolved_kind"}:
                value["aus"][0]["kind"] = requested_kind
                value["aus"][0]["other_kind"] = "custom" if requested_kind == "other" else None
        return value

    def test_echoing_invalid_fixtures_fails_and_keeps_host_only_diagnostics_separate(self):
        opener, calls = self._echo_opener()
        with tempfile.TemporaryDirectory() as folder:
            report = constraint_suite_probe(self.cfg, folder, execute=True, opener=opener)
            saved = json.loads((Path(folder) / "constraint_suite_probe.json").read_text(encoding="utf-8"))
        self.assertEqual(report, saved)
        self.assertEqual(len(calls), report["requests_sent"])
        self.assertEqual(report["requests_completed"], len(self.cases))
        self.assertEqual(report["status"], "fail")
        rows = {row["case_id"]: row for row in report["results"]}
        for case in self.cases:
            row = rows[case["case_id"]]
            self.assertEqual(row["scope"], case["scope"])
            if case["scope"] == "host_only":
                self.assertEqual(row["status"], "host_violation", case["case_id"])
                self.assertTrue(row["transport_validation"]["valid"])
                self.assertTrue(row["full_validation"]["valid"])
                self.assertFalse(row["host_validation"]["valid"])
                errors = " ".join(row["host_validation"]["errors"])
                if case["case_id"] == "host-evidence-context-only":
                    self.assertIn("evidence has no TARGET intersection", errors)
                elif case["case_id"].startswith("host-evidence-"):
                    self.assertIn("unknown/outside-region evidence", errors)
                elif case["case_id"] == "host-request_id":
                    self.assertIn("request_id mismatch", errors)
                elif case["case_id"] == "host-target_id":
                    self.assertIn("target_id mismatch", errors)
            elif case["scope"] == "full_schema":
                self.assertEqual(row["status"], "full_schema_violation", case["case_id"])
                self.assertTrue(row["transport_validation"]["valid"])
                self.assertFalse(row["full_validation"]["valid"])
            elif case["mode"] == "adversarial" and not case["expected_transport_valid"]:
                expected_status = "non_object" if not isinstance(case["requested_value"], dict) else "transport_schema_violation"
                self.assertEqual(row["status"], expected_status, case["case_id"])
        self.assertNotIn(self.cfg["token"], json.dumps(report))

    def test_corrected_adversarial_outputs_can_pass_without_claiming_decoding_guarantees(self):
        def opener(request, **_kwargs):
            payload = json.loads(request.data)
            prompt = payload["messages"][0]["content"]
            case_id = prompt.split("Constraint test case ", 1)[1].split(".", 1)[0]
            case = self.by_id[case_id]
            response = case["requested_value"] if case["mode"] == "valid" else self._repaired(case)
            return FakeHTTP(json.dumps(response), usage={"prompt_tokens": 4, "completion_tokens": 3, "total_tokens": 7})

        with tempfile.TemporaryDirectory() as folder:
            report = constraint_suite_probe(self.cfg, folder, execute=True, opener=opener)
        self.assertEqual(report["status"], "pass", (report["status_counts"], [r["case_id"] for r in report["results"] if r["status"] != "pass"]))
        for case in self.cases:
            if case["scope"] == "full_schema":
                self.assertTrue(case["expected_transport_valid"])
                self.assertFalse(case["expected_full_valid"])
                self.assertEqual(next(r for r in report["results"] if r["case_id"] == case["case_id"])["status"], "pass")
        self.assertTrue(any("does not prove decoding enforcement" in item for item in report["limitations"]))

    def test_generic_negative_cannot_evade_nested_authority_unit_challenge(self):
        index, case = next(
            (index, c) for index, c in enumerate(self.cases)
            if c["mode"] == "adversarial" and c["path"][:2] == ["aus", 0] and c["keyword"] == "enum"
        )
        generic_negative = {
            "request_id": "probe-request",
            "target_id": "probe-target",
            "decision": "hard_negative",
            "coverage_status": "complete",
            "aus": [],
            "hard_negative_reason": "other",
            "unresolved_reason": None,
        }
        opener, _ = self._echo_opener({case["case_id"]: generic_negative})
        with tempfile.TemporaryDirectory() as folder:
            report = constraint_suite_probe(self.cfg, folder, execute=True, opener=opener, max_requests=index + 1)
        row = next(r for r in report["results"] if r["case_id"] == case["case_id"])
        self.assertEqual(row["status"], "challenge_not_exercised")
        self.assertNotEqual(report["status"], "pass")

    def test_valid_control_returning_other_valid_value_does_not_prove_constraint_coverage(self):
        control_index, control = next(
            (index, case)
            for index, case in enumerate(self.cases)
            if case["mode"] == "valid" and case["scope"] == "transport"
        )
        alternative = copy.deepcopy(control["requested_value"])
        if alternative["decision"] == "positive":
            alternative["aus"][0]["claim"] += " Different valid output."
        elif alternative["decision"] == "hard_negative":
            alternative["hard_negative_reason"] = "fact_only" if alternative["hard_negative_reason"] != "fact_only" else "editorial"
        else:
            alternative["unresolved_reason"] = "ambiguous_kind" if alternative["unresolved_reason"] != "ambiguous_kind" else "other"
        self.assertTrue(list(TRANSPORT_VALIDATOR.iter_errors(alternative)) == [])
        responses = {control["case_id"]: alternative}
        # Earlier catalog entries are echoed correctly; the selected control gets
        # a different but schema-valid output, so that constraint is unexercised.
        opener, _ = self._echo_opener(responses)
        with tempfile.TemporaryDirectory() as folder:
            report = constraint_suite_probe(self.cfg, folder, execute=True, opener=opener, max_requests=control_index + 1)
        row = next(item for item in report["results"] if item["case_id"] == control["case_id"])
        self.assertEqual(row["case_id"], control["case_id"])
        self.assertNotEqual(report["status"], "pass")
        self.assertNotIn(row.get("status"), {"pass", "supported", "constraint_enforced"})

    def test_request_cap_is_incomplete_and_sends_no_hidden_requests(self):
        opener, calls = self._echo_opener()
        with tempfile.TemporaryDirectory() as folder:
            report = constraint_suite_probe(self.cfg, folder, execute=True, opener=opener, max_requests=2)
        self.assertEqual(len(calls), 2)
        self.assertEqual(report["requests_sent"], 2)
        self.assertEqual(report["requests_completed"], 2)
        self.assertEqual(report["status"], "incomplete")

    def test_checkpoint_resume_and_url_model_identity_isolation(self):
        with tempfile.TemporaryDirectory() as folder:
            calls = []
            opener, _ = self._echo_opener(calls=calls)
            first = constraint_suite_probe(self.cfg, folder, execute=True, opener=opener, max_requests=1)
            second = constraint_suite_probe(self.cfg, folder, execute=True, opener=opener, max_requests=2)
            self.assertEqual(len(calls), 3)
            self.assertEqual(first["requests_sent"], 1)
            self.assertEqual(second["requests_sent"], 2)
            self.assertEqual(second["resumed_cases"], 1)

            for changed in ({"url": "https://other.invalid/v1/chat/completions"}, {"model": "other-model"}):
                cfg = {**self.cfg, **changed}
                other_opener, _ = self._echo_opener(calls=calls)
                isolated = constraint_suite_probe(cfg, folder, execute=True, opener=other_opener, max_requests=1)
                self.assertEqual(isolated["requests_sent"], 1)
                self.assertEqual(isolated["resumed_cases"], 0)

    def test_corrupt_checkpoint_is_rejected_and_case_is_requested_again(self):
        calls = []
        opener, _ = self._echo_opener(calls=calls)
        with tempfile.TemporaryDirectory() as folder:
            first = constraint_suite_probe(self.cfg, folder, execute=True, opener=opener, max_requests=1)
            checkpoint = next((Path(folder) / "checkpoints").glob("*/*.json"))
            checkpoint.write_text("{corrupt", encoding="utf-8")
            second = constraint_suite_probe(self.cfg, folder, execute=True, opener=opener, max_requests=1)
        self.assertEqual(first["requests_sent"], 1)
        self.assertEqual(second["requests_sent"], 1)
        self.assertEqual(second["resumed_cases"], 0)
        self.assertEqual(len(calls), 2)

    def test_truncated_malformed_nonobject_http_and_transport_errors_are_distinct(self):
        cases = self.cases
        scenarios = [
            ("truncated", ("{", "length"), "truncated"),
            ("malformed", ("not-json", "stop"), "invalid_json"),
            ("nonobject", ("[]", "stop"), "non_object"),
            ("http", HTTPError(self.cfg["url"], 503, "unavailable", None, None), "http_error"),
            ("transport", URLError("offline"), "transport_error"),
        ]
        for label, response, expected_status in scenarios:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as folder:
                selected = cases[0]
                opener, _ = self._echo_opener({selected["case_id"]: response})
                report = constraint_suite_probe(self.cfg, folder, execute=True, opener=opener, max_requests=1)
                row = report["results"][0]
                self.assertEqual(row["status"], expected_status)
                self.assertNotEqual(report["status"], "pass")
                self.assertNotIn(self.cfg["token"], json.dumps(report))


if __name__ == "__main__":
    unittest.main()
