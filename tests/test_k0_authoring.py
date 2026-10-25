"""Independent local contract tests for the K0 case-level authoring pilot.

These tests exercise only the public ``k0_authoring`` API and the immutable A
stage-1 inputs. They intentionally make no semantic-quality or gold claim.
"""

from __future__ import annotations

import copy
import importlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "knowledge_base.pipeline_v1.k0_authoring"
EXPECTED_CASE_COUNT = 3
EXPECTED_SCOPE_COUNT = 16
EXPECTED_EVIDENCE_REF_COUNT = 58
ORIGINAL_A = ROOT / "knowledge_base/pipeline_v1/outputs/au_claim_a_local_ready_20261020"
UNSENT_045155_CONTEXT_ID = "c-50266f87b7ef0ea51d49bbd4"


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _mapping(value):
    """Accept mapping-style workspaces and simple dataclass wrappers."""
    if isinstance(value, dict):
        return value
    if hasattr(value, "__dict__"):
        return vars(value)
    raise AssertionError(f"expected mapping-like object, got {type(value).__name__}")


def _rows(workload):
    data = _mapping(workload)
    for key in ("cases", "rows", "items"):
        value = data.get(key)
        if isinstance(value, list):
            return value
    raise AssertionError("prepared workload does not expose its case rows")


def _case_id(case):
    row = _mapping(case)
    for key in ("case_id", "case", "id"):
        if key in row:
            return str(row[key])
    raise AssertionError("case row has no case identifier")


def _scope_ids(case):
    """Read actual delivered scope IDs from the prepared case/catalog payload."""
    row = _mapping(case)
    for key in ("scopes", "read_scopes", "delivered_scopes", "catalog"):
        value = row.get(key)
        if isinstance(value, list):
            return [str(_mapping(item).get("scope_id", _mapping(item).get("ref_id"))) for item in value]
        if isinstance(value, dict):
            for nested_key in ("delivered", "scopes", "source_refs", "catalog"):
                nested = value.get(nested_key)
                if isinstance(nested, list):
                    return [str(_mapping(item).get("scope_id", _mapping(item).get("ref_id"))) for item in nested]
    return []


def _original_a_delivery_oracle():
    """Derive K0's source union from original A's *submitted* stage-1 jobs.

    The old workload's context_refs describe availability. Only catalog refs
    present in the exact stage-1 request job are counted as delivered.
    """
    workload = _load_json(ORIGINAL_A / "input/workload.json")
    ledger = _load_json(ORIGINAL_A / "live/runtime_ledger.json")
    row_by_id = {row["target_id"]: row for row in workload["rows"]}
    delivered_by_case = {}
    evidence_by_case = {}
    for entry in ledger["jobs"].values():
        job = entry["job"]
        if job.get("stage") != 1:
            continue
        row = row_by_id[job["target_id"]]
        submitted = job["catalog"].get("target_refs", {})
        expected = row.get("target_refs", {})
        submitted_by_id = {value["ref_id"]: value for value in submitted.values()}
        if submitted_by_id != expected:
            raise AssertionError(f"original A stage-1 payload/catalog mismatch for {job['target_id']}")
        sent_body = json.loads(job["payload"]["messages"][0]["content"].split("\nINPUT:\n", 1)[1])
        sent_target = sent_body.get("TARGET", [])
        if sent_target != [{"id": key, "text": value["quote"]} for key, value in submitted.items()]:
            raise AssertionError(f"original A stage-1 payload text mismatch for {job['target_id']}")
        case_id = str(job["case_id"])
        spans = sorted(
            ({k: ref[k] for k in ("case_id", "source_hash", "start_char", "end_char", "quote")}
             for ref in submitted.values()),
            key=lambda span: (span["start_char"], span["end_char"]),
        )
        delivered_by_case.setdefault(case_id, []).append({"historical_id": job["target_id"], "spans": spans})
        evidence_by_case.setdefault(case_id, {}).update(
            (value["ref_id"], {k: value[k] for k in ("case_id", "source_hash", "start_char", "end_char", "quote")})
            for value in submitted.values()
        )
    for scopes in delivered_by_case.values():
        scopes.sort(key=lambda scope: (scope["spans"][0]["start_char"], scope["spans"][0]["end_char"]))
    return workload, delivered_by_case, evidence_by_case


class K0AuthoringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = importlib.import_module(PACKAGE)
        cls.core = importlib.import_module(PACKAGE + ".core")
        cls.tools = importlib.import_module(PACKAGE + ".tools")
        cls.runner = importlib.import_module(PACKAGE + ".runner")
        cls.token_budget = importlib.import_module(PACKAGE + ".token_budget")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="k0-authoring-tests-")
        self.output_root = Path(self.temp.name) / "workspace"
        self.workload = self.core.prepare(self.output_root, parent_root=ORIGINAL_A)
        self.cfg = self.core.runtime_config(self.workload["identity"])

    def tearDown(self):
        self.temp.cleanup()

    def _case(self, wanted=None):
        rows = _rows(self.workload)
        if wanted is None:
            return rows[0]
        for row in rows:
            if _case_id(row) == wanted:
                return row
        raise AssertionError(f"prepared workload missing case {wanted}")

    def _job(self, case=None, state=None):
        case = case or self._case()
        state = state if state is not None else self.tools.initial_state(case)
        return self.core.build_job(self.workload, case, state, self.cfg)

    def _validate(self, value, job):
        try:
            return self.core.validate_response(value, job)
        except (ValueError, TypeError, KeyError) as exc:
            return {"error": str(exc)}

    def _accounting_dispatch_fixture(self, *, attempts=None, reserved_input=0,
                                     reserved_output=0):
        """Build one locally reserved POST without any usable network opener."""
        from types import SimpleNamespace

        job = self._job(self._case("045155"))
        payload = copy.deepcopy(job["payload"])
        job_id = self.runner.payload_digest(payload)
        job["payload_sha256"] = job_id
        fixture_index = getattr(self, "_accounting_fixture_count", 0)
        self._accounting_fixture_count = fixture_index + 1
        root = Path(self.temp.name) / f"accounting-{fixture_index}"
        root.mkdir(parents=True, exist_ok=True)
        (root / "attempt_receipts").mkdir()
        opener_calls = []
        opener = lambda *args, **kwargs: opener_calls.append((args, kwargs))
        ledger = {
            "jobs": {job["request_id"]: {"job": {
                "payload": payload,
                "payload_sha256": job_id,
                "input_reservation": job["input_reservation"],
            }, "status": "reserved"}},
            "attempts": list(attempts or []),
            "provider_attempts": len(attempts or []),
            "reserved_input_tokens": reserved_input,
            "reserved_output_tokens": reserved_output,
            "job_recovery": {},
            "observed_jobs": {},
        }
        accounting = self.runner.K0Accounting(
            root, ledger, {"max_requests": self.runner.MAX_ATTEMPTS}, opener
        )
        accounting.mock = False
        accounting.invocation_start = 0
        accounting.max_new_requests = None
        accounting.readiness = SimpleNamespace(check=lambda: None)
        url = "http://127.0.0.1:8765/v1/chat/completions"
        request = self.runner.urlrequest.Request(
            url,
            data=json.dumps({"payload": payload, "job_id": job_id}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        proof = {
            "job_id": job_id,
            "gateway_url": url,
            "backoff_seconds": 1.0,
            "observations": [
                {"http_status": 404, "detail": "Unknown job", "health": {"ready": True},
                 "job_url": url + "/" + job_id, "observed_monotonic": 1.0},
                {"http_status": 404, "detail": "Unknown job", "health": {"ready": True},
                 "job_url": url + "/" + job_id, "observed_monotonic": 2.0},
            ],
        }
        return accounting, request, proof, opener_calls

    def test_fixture_is_exact_delivered_union_and_excludes_unsent_context(self):
        """The test oracle is the A stage-1 delivery ledger, never all available context."""
        rows = _rows(self.workload)
        self.assertEqual(len(rows), EXPECTED_CASE_COUNT)
        original, scopes_by_case, evidence_by_case = _original_a_delivery_oracle()
        self.assertEqual(len(original["rows"]), EXPECTED_SCOPE_COUNT)
        self.assertEqual(sum(len(refs) for refs in evidence_by_case.values()), EXPECTED_EVIDENCE_REF_COUNT)
        expected_scopes = {
            case: [[(span["case_id"], span["source_hash"], span["start_char"], span["end_char"], span["quote"])
                    for span in scope["spans"]] for scope in scopes]
            for case, scopes in scopes_by_case.items()
        }
        actual_scopes = {}
        actual_evidence = {}
        for row in rows:
            cid = _case_id(row)
            actual_scopes[cid] = [
                [(span["case_id"], span["source_hash"], span["start_char"], span["end_char"], span["quote"])
                 for span in (row["evidence_catalog"][eid] for eid in scope["evidence_ids"])]
                for scope in row["scopes"]
            ]
            actual_evidence[cid] = row["evidence_catalog"]
        self.assertEqual(actual_scopes, expected_scopes)
        self.assertEqual(set(actual_scopes), set(scopes_by_case))
        self.assertEqual(
            {case: {(v["case_id"], v["source_hash"], v["start_char"], v["end_char"], v["quote"])
                    for v in refs.values()} for case, refs in actual_evidence.items()},
            {case: {(v["case_id"], v["source_hash"], v["start_char"], v["end_char"], v["quote"])
                    for v in refs.values()} for case, refs in evidence_by_case.items()},
        )
        excluded = next(ref for row in original["rows"] if row["case_id"] == "045155"
                        for ref in row["context_refs"].values()
                        if ref["ref_id"] == UNSENT_045155_CONTEXT_ID)
        self.assertNotIn((excluded["case_id"], excluded["source_hash"], excluded["start_char"],
                          excluded["end_char"], excluded["quote"]),
                         {(v["case_id"], v["source_hash"], v["start_char"], v["end_char"], v["quote"])
                          for v in actual_evidence.get("045155", {}).values()})
        available_context_ids = {
            ref_id
            for row in original["rows"]
            if row["case_id"] == "045155"
            for ref_id in row.get("context_refs", {})
        }
        self.assertIn(UNSENT_045155_CONTEXT_ID, available_context_ids)

    def test_preflight_and_initial_state_keep_bounded_work_partial(self):
        result = self.core.preflight(self.workload, cfg=self.cfg)
        self.assertIsInstance(result, dict)
        self.assertTrue(result.get("status"))
        self.assertEqual(result["scope_count"], EXPECTED_SCOPE_COUNT)
        for case in _rows(self.workload):
            state = self.tools.initial_state(case)
            serialized = json.dumps(state, ensure_ascii=False).lower()
            self.assertIn("partial", serialized)

    def test_job_uses_pinned_input_counter_and_never_exposes_kos_checklist(self):
        case = self._case()
        state = self.tools.initial_state(case)
        job = self.core.build_job(self.workload, case, state, self.cfg)
        self.assertEqual(job["input_reservation"], self.core.input_reservation(job["payload"]))
        self.assertLessEqual(job["input_reservation"], 6000)
        self.assertEqual(job["payload"]["max_tokens"], 800)
        rendered = json.dumps(job["payload"], ensure_ascii=False).lower()
        for forbidden in ("gold_noticed", "reference_checklist", "semantic_gold", "kos_inventory"):
            self.assertNotIn(forbidden, rendered)

    def test_tokenizer_pin_is_in_workload_and_byte_fallback_is_labeled(self):
        self.assertEqual(self.workload["input_counter"], self.token_budget.counter_identity())
        method = self.workload["input_counter"]["method"]
        if "fallback" not in method:
            self.assertEqual(self.workload["input_counter"]["revision"], self.token_budget.REVISION)
            self.assertTrue(self.workload["input_counter"]["files"])
        payload = {"messages": [{"role": "user", "content": "café"}], "max_tokens": 800}
        fallback = {"method": "full_serialized_payload_UTF8_bytes_plus128_fallback_not_provider_tokens"}
        with patch.object(self.token_budget, "counter_identity", return_value=fallback):
            self.assertGreater(self.token_budget.input_reservation(payload), 0)
            self.assertIn("fallback", self.token_budget.counter_identity()["method"])

    def test_response_schema_accepts_same_case_cross_scope_evidence(self):
        # Construct a valid wire turn from IDs in two different delivered
        # scopes of this same case. No historical TARGET pinning is expected.
        job = self._synthetic_job()
        normalized = self._validate(self._valid_wire(("ev-a", "ev-b")), job)
        self.assertEqual(len(normalized["aus"]), 1, normalized)
        self.assertFalse(normalized["au_errors"], normalized)

    @staticmethod
    def _synthetic_job():
        evidence = {
            "ev-a": {"case_id": "045155", "source_hash": "hash-45", "start_char": 0, "end_char": 8, "quote": "source A"},
            "ev-b": {"case_id": "045155", "source_hash": "hash-45", "start_char": 8, "end_char": 16, "quote": "source B"},
        }
        return {"case_id": "045155", "active_scope_ids": ["scope-a", "scope-b"],
                "source_hash": "hash-45", "catalog": {"evidence": evidence}, "draft_ids": []}

    @staticmethod
    def _valid_wire(evidence_ids=("ev-a", "ev-b")):
        return {
            "aus": [{"claim": "A supported legal point.", "kind": None,
                     "evidence_ids": list(evidence_ids), "limits": None}],
            "assessed_scope_ids": ["scope-a", "scope-b"],
            "next_action": {"tool": "get_drafts"},
        }

    def test_response_schema_enforces_types_enums_and_exact_keys(self):
        job = self._synthetic_job()
        valid = self._valid_wire()
        self.assertFalse(self._validate(valid, job).get("error"))
        malformed_values = []
        for key, value in (("claim", "  "), ("claim", 42), ("kind", "invented"),
                           ("evidence_ids", "ev-a"), ("limits", 7)):
            bad = copy.deepcopy(valid)
            bad["aus"][0][key] = value
            malformed_values.append(bad)
        bad = copy.deepcopy(valid)
        bad["unexpected"] = True
        malformed_values.append(bad)
        bad = copy.deepcopy(valid)
        bad["aus"][0]["unexpected"] = True
        malformed_values.append(bad)
        for value in malformed_values:
            with self.subTest(value=value):
                result = self._validate(value, job)
                self.assertTrue(result.get("au_errors") or result.get("error"), result)

    def test_long_claim_and_limits_warn_without_truncating(self):
        value = self._valid_wire(("ev-a",))
        value["aus"][0]["claim"] = "C" * 501
        value["aus"][0]["limits"] = "L" * 251
        result = self._validate(value, self._synthetic_job())
        self.assertTrue(result.get("warnings"))
        accepted = result.get("aus", [])
        self.assertEqual(len(accepted), 1)
        self.assertEqual(accepted[0]["claim"], "C" * 501)
        self.assertEqual(accepted[0]["limits"], "L" * 251)

    def test_foreign_unopened_and_preview_evidence_are_rejected_locally(self):
        job = self._synthetic_job()
        value = self._valid_wire(("ev-a", "ev-foreign"))
        value["aus"].append({"claim": "Keep the valid sibling AU.", "kind": None,
                             "evidence_ids": ["ev-a"], "limits": None})
        result = self._validate(value, job)
        self.assertEqual(len(result.get("aus", [])), 1)
        self.assertEqual(len(result.get("au_errors", [])), 1)
        self.assertTrue(result["aus"][0]["claim"].startswith("Keep the valid"))

        for ref_id in ("ev-available", "ev-preview"):
            invalid = self._valid_wire((ref_id,))
            response = self._validate(invalid, job)
            self.assertFalse(response.get("aus"), response)
            self.assertTrue(response.get("au_errors"), response)

    def test_eight_aus_is_transport_cap_not_case_quota(self):
        job = self._synthetic_job()
        value = self._valid_wire(("ev-a",))
        value["aus"] = [
            {"claim": f"Legal point {i}", "kind": None, "evidence_ids": ["ev-a"], "limits": None}
            for i in range(8)
        ]
        result = self._validate(value, job)
        self.assertEqual(len(result.get("aus", [])), 8)

        ninth = copy.deepcopy(value)
        ninth["aus"].append({"claim": "Ninth point", "kind": None,
                             "evidence_ids": ["ev-a"], "limits": None})
        response = self._validate(ninth, job)
        self.assertTrue(response.get("error") or response.get("au_errors"), response)

    def test_local_bad_candidate_keeps_good_draft_and_other_case_state(self):
        case = self._case("045155")
        original = self.tools.initial_state(case)
        other_case = self._case("099980")
        other_state = self.tools.initial_state(other_case)
        other_before = json.dumps(other_state, ensure_ascii=False, sort_keys=True)
        job = self.core.build_job(self.workload, case, original, self.cfg)
        active = job["active_scope_ids"]
        wire = {
            "aus": [
                {"claim": "Keep this valid sibling draft.", "kind": None,
                 "evidence_ids": [next(iter(job["catalog"]["evidence"]))], "limits": None},
                {"claim": "Reject this local bad candidate.", "kind": None,
                 "evidence_ids": ["foreign-or-unopened"], "limits": None},
            ],
            "assessed_scope_ids": active,
            "next_action": {"tool": "get_drafts"},
        }
        norm = self._validate(wire, job)
        updated = self.tools.apply_turn(case, original, norm)
        self.assertIsNot(updated, original)
        self.assertTrue(updated["finished"])
        self.assertEqual(updated["stop_reason"], "invalid_AU")
        self.assertEqual(len(updated["drafts"]), 1)
        self.assertEqual(next(iter(updated["drafts"].values()))["claim"], "Keep this valid sibling draft.")
        self.assertEqual(json.dumps(other_state, ensure_ascii=False, sort_keys=True), other_before)
        self.assertEqual(updated["case_status"], "partial")

    def test_transport_json_nonobject_root_is_invalid(self):
        job = self._synthetic_job()
        body = {"model": self.cfg["model"], "choices": [{"finish_reason": "stop",
                 "message": {"content": "[]"}}]}
        with self.assertRaises(ValueError):
            self.runner._normalize_body(body, job, self.cfg)
        duplicate = copy.deepcopy(body)
        duplicate["choices"][0]["message"]["content"] = '{"aus":[],"aus":[]}'
        with self.assertRaises(ValueError):
            self.runner._normalize_body(duplicate, job, self.cfg)
        truncated = copy.deepcopy(body)
        truncated["choices"][0]["finish_reason"] = "length"
        with self.assertRaises(ValueError):
            self.runner._normalize_body(truncated, job, self.cfg)

    def test_dispatch_rejects_unknown_usage_before_live_post(self):
        accounting, request, proof, opener_calls = self._accounting_dispatch_fixture()
        with patch.object(self.runner, "_usage_summary", return_value=(
                {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}, 1)), \
             patch.object(self.runner, "_provider_request_cap_exceeded", return_value=False):
            with self.assertRaisesRegex(self.runner.BudgetError, "unknown usage stops new admission"):
                accounting.dispatch(request, proof)
        self.assertEqual(opener_calls, [])
        self.assertEqual(accounting.ledger["attempts"], [])

    def test_remote_job_seen_without_local_post_is_unknown_and_blocks_next_post(self):
        accounting, _, _, _ = self._accounting_dispatch_fixture()
        remote_id = "remote-job-without-local-post"
        remote_hash = "remote-payload-hash"
        accounting.ledger["jobs"][remote_id] = {
            "job": {"payload_sha256": remote_hash}, "receipt_sha256": "synthetic-receipt"
        }
        # GET-observed terminal and in-flight states with no raw_response or usage
        # must remain unknown when this process never issued the corresponding POST.
        for remote_status in ("queued", "running", "failed", "interrupted", "completed"):
            with self.subTest(remote_status=remote_status):
                fake_receipt = {"transport_trace": {"job_status": remote_status}, "usage": None}
                with patch.object(self.runner, "_receipt", return_value=fake_receipt):
                    subtotal, unknown = self.runner._usage_summary(accounting.root, accounting.ledger)
                self.assertEqual(subtotal["total_tokens"], 0)
                self.assertEqual(unknown, 1)

        accounting, request, proof, opener_calls = self._accounting_dispatch_fixture()
        accounting.ledger["jobs"][remote_id] = {
            "job": {"payload_sha256": remote_hash}, "receipt_sha256": "synthetic-receipt"
        }
        accounting.ledger["observed_jobs"][remote_hash] = "failed"
        with patch.object(self.runner, "_receipt", return_value={"usage": None}), \
             patch.object(self.runner, "_usage_summary", wraps=self.runner._usage_summary):
            with self.assertRaisesRegex(self.runner.BudgetError, "unknown usage stops new admission"):
                accounting.dispatch(request, proof)
        self.assertEqual(opener_calls, [])
        self.assertEqual(accounting.ledger["attempts"], [])

    def test_dispatch_rejects_actual_usage_over_aggregate_cap_before_post(self):
        accounting, request, proof, opener_calls = self._accounting_dispatch_fixture()
        reserve = accounting.ledger["jobs"][next(iter(accounting.ledger["jobs"]))]["job"]["input_reservation"]
        output = request.data and json.loads(request.data)["payload"]["max_tokens"]
        observed_total = self.runner.MAX_TOTAL - reserve - output + 1
        self.assertGreater(observed_total, 0)
        with patch.object(self.runner, "_usage_summary", return_value=(
                {"input_tokens": 0, "output_tokens": 0, "total_tokens": observed_total}, 0)), \
             patch.object(self.runner, "_provider_request_cap_exceeded", return_value=False):
            with self.assertRaisesRegex(self.runner.BudgetError, "K0 aggregate budget exhausted"):
                accounting.dispatch(request, proof)
        self.assertEqual(opener_calls, [])
        self.assertEqual(accounting.ledger["attempts"], [])

    def test_dispatch_enforces_aggregate_reservation_and_twelve_attempt_caps(self):
        accounting, request, proof, opener_calls = self._accounting_dispatch_fixture()
        job = accounting.ledger["jobs"][next(iter(accounting.ledger["jobs"]))]["job"]
        reserved_total = job["input_reservation"] + job["payload"]["max_tokens"]
        accounting.ledger["reserved_input_tokens"] = self.runner.MAX_TOTAL - reserved_total + 1
        with patch.object(self.runner, "_usage_summary", return_value=(
                {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}, 0)), \
             patch.object(self.runner, "_provider_request_cap_exceeded", return_value=False):
            with self.assertRaisesRegex(self.runner.BudgetError, "K0 aggregate budget exhausted"):
                accounting.dispatch(request, proof)
        self.assertEqual(opener_calls, [])
        self.assertEqual(accounting.ledger["attempts"], [])

        accounting, request, proof, opener_calls = self._accounting_dispatch_fixture()
        accounting.ledger["attempts"] = [
            {"job_id": f"prior-{i}", "usage": {"input_tokens": 1, "output_tokens": 1,
                                                  "total_tokens": 2}}
            for i in range(self.runner.MAX_ATTEMPTS)
        ]
        with patch.object(self.runner, "_usage_summary", return_value=(
                {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}, 0)), \
             patch.object(self.runner, "_provider_request_cap_exceeded", return_value=False):
            with self.assertRaisesRegex(self.runner.BudgetError, "K0 aggregate budget exhausted"):
                accounting.dispatch(request, proof)
        self.assertEqual(opener_calls, [])
        self.assertEqual(len(accounting.ledger["attempts"]), self.runner.MAX_ATTEMPTS)

    def test_provider_request_cap_helper_and_dispatch_gate(self):
        accounting, request, proof, opener_calls = self._accounting_dispatch_fixture()
        helper = self.runner._provider_request_cap_exceeded
        valid_usage = {"input_tokens": self.runner.MAX_INPUT, "output_tokens": self.runner.MAX_OUTPUT,
                       "total_tokens": self.runner.MAX_INPUT + self.runner.MAX_OUTPUT}
        accounting.ledger["attempts"] = [{"job_id": "within-cap", "usage": valid_usage}]
        self.assertFalse(helper(accounting.root, accounting.ledger))
        accounting.ledger["attempts"] = [{"job_id": "input-over", "usage": {
            **valid_usage, "input_tokens": self.runner.MAX_INPUT + 1}}]
        self.assertTrue(helper(accounting.root, accounting.ledger))
        accounting.ledger["attempts"] = [{"job_id": "output-over", "usage": {
            **valid_usage, "output_tokens": self.runner.MAX_OUTPUT + 1}}]
        self.assertTrue(helper(accounting.root, accounting.ledger))
        accounting.ledger["attempts"] = []
        entry = accounting.ledger["jobs"][next(iter(accounting.ledger["jobs"]))]
        entry["receipt_sha256"] = "synthetic-receipt-hash"
        with patch.object(self.runner, "_receipt", return_value={"usage": {
                **valid_usage, "input_tokens": self.runner.MAX_INPUT + 1}}):
            self.assertTrue(helper(accounting.root, accounting.ledger))
        for dimension, exceeded in (("input_tokens", self.runner.MAX_INPUT + 1),
                                    ("output_tokens", self.runner.MAX_OUTPUT + 1)):
            accounting, request, proof, opener_calls = self._accounting_dispatch_fixture()
            accounting.ledger["attempts"] = [{"job_id": "over-cap", "usage": {
                **valid_usage, dimension: exceeded}}]
            with patch.object(self.runner, "_usage_summary", return_value=(
                    {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}, 0)):
                with self.assertRaisesRegex(self.runner.BudgetError, "provider per-request cap exceeded"):
                    accounting.dispatch(request, proof)
            self.assertEqual(opener_calls, [])
            self.assertEqual(len(accounting.ledger["attempts"]), 1)

    def test_run_report_pauses_completed_work_for_unknown_or_over_cap_usage(self):
        accounting, _, _, _ = self._accounting_dispatch_fixture()
        accounting.ledger["binding"] = {"test": "synthetic accounting report"}
        accounting.ledger["identity"] = "synthetic-ledger-identity"
        accounting.ledger["get_polls"] = 0
        accounting.max_new_requests = None
        accounting.readiness = type("Ready", (), {"snapshot": lambda self: {"status": "ready"}})()
        states = {}
        for case in self.workload["cases"]:
            state = self.tools.initial_state(case)
            for row in state["read_ledger"].values():
                row.update(state="assessed", assessed=True)
            state.update(finished=True, stop_reason="work_scope_complete")
            states[case["case_id"]] = state
        accounting.ledger["attempts"] = [{"job_id": "over-cap", "usage": {
            "input_tokens": self.runner.MAX_INPUT + 1, "output_tokens": 0,
            "total_tokens": self.runner.MAX_INPUT + 1}}]
        with patch.object(self.runner, "_usage_summary", return_value=(
                {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}, 0)):
            report = self.runner._report(accounting.root, self.workload, accounting, states,
                                         {}, False, 0.0, lambda: 0.0)
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["pauses"]["run"], "provider_per_request_cap_exceeded")
        self.assertTrue(all(row["work_scope_complete"] for row in report["results"]))

        accounting.ledger["attempts"] = []
        with patch.object(self.runner, "_usage_summary", return_value=(
                {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}, 1)), \
             patch.object(self.runner, "_provider_request_cap_exceeded", return_value=False):
            report = self.runner._report(accounting.root, self.workload, accounting, states,
                                         {}, False, 0.0, lambda: 0.0)
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["pauses"]["run"], "unknown_provider_usage")
        self.assertTrue(all(row["work_scope_complete"] for row in report["results"]))

    def test_workload_completion_never_marks_case_semantically_complete(self):
        case = self._case("045155")
        state = self.tools.initial_state(case)
        for entry in state["read_ledger"].values():
            entry.update(state="assessed", assessed=True)
        state["active_scope_ids"] = list(state["read_ledger"])
        finished = self.tools.finish_case(case, state, "work_scope_complete")
        self.assertTrue(finished["finished"])
        self.assertTrue(finished["work_scope_complete"])
        self.assertFalse(finished["case_source_assessment_complete"])
        self.assertEqual(finished["case_status"], "partial")

    def test_turn_navigation_distinguishes_delivered_assessed_and_unresolved(self):
        case = self._case("045155")
        state = self.tools.initial_state(case)
        state["active_scope_ids"] = [case["scopes"][0]["scope_id"]]
        first_job = self.core.build_job(self.workload, case, state, self.cfg)
        first_scope = first_job["active_scope_ids"][0]
        next_scope = next(s["scope_id"] for s in case["scopes"]
                          if s["scope_id"] not in first_job["active_scope_ids"])
        first_norm = self._validate({
            "aus": [], "assessed_scope_ids": [],
            "next_action": {"tool": "open_region", "scope_ids": [next_scope]},
        }, first_job)
        state = self.tools.apply_turn(case, state, first_norm)
        self.assertEqual(state["read_ledger"][first_scope]["state"], "delivered")
        self.assertEqual(state["read_ledger"][next_scope]["state"], "available")

        second_job = self.core.build_job(self.workload, case, state, self.cfg)
        second_norm = self._validate({
            "aus": [], "assessed_scope_ids": [next_scope],
            "next_action": {"tool": "finish_case", "reason": "needs_context"},
        }, second_job)
        state = self.tools.apply_turn(case, state, second_norm)
        self.assertTrue(state["finished"])
        self.assertEqual(state["read_ledger"][first_scope]["state"], "delivered")
        self.assertEqual(state["read_ledger"][next_scope]["state"], "unresolved")
        self.assertTrue(all(row["state"] in {"available", "delivered", "assessed", "unresolved"}
                            for row in state["read_ledger"].values()))
        self.assertEqual(state["case_status"], "partial")

    def test_invalid_raw_response_marks_delivery_once_when_replayed(self):
        case = self._case("045155")
        initial = self.tools.initial_state(case)
        job = self.core.build_job(self.workload, case, initial, self.cfg)
        receipt = {"raw_response": {"choices": [{"finish_reason": "length"}]},
                   "normalized": None, "status": "invalid"}

        untouched = self.runner._advance(case, initial, job, {"normalized": None})
        self.assertTrue(all(row["delivered_count"] == 0 for row in untouched["read_ledger"].values()))

        ledger_root = Path(self.temp.name) / "replay"
        ledger_root.mkdir()
        ledger = {"_root": str(ledger_root), "jobs": {job["request_id"]: {
            "job": job, "receipt_sha256": "synthetic-receipt", "status": "invalid"
        }}}
        with patch.object(self.runner, "_receipt", return_value=receipt):
            states_first, _ = self.runner._replay(self.workload, ledger, self.cfg)
            states_again, _ = self.runner._replay(self.workload, ledger, self.cfg)

        for states in (states_first, states_again):
            replayed = states[case["case_id"]]
            self.assertEqual(replayed["active_scope_ids"], job["active_scope_ids"])
            for scope_id, row in replayed["read_ledger"].items():
                if scope_id in job["active_scope_ids"]:
                    self.assertEqual(row["state"], "delivered")
                    self.assertEqual(row["delivered_count"], 1)
                    self.assertFalse(row["assessed"])
                else:
                    self.assertEqual(row["delivered_count"], 0)
                    self.assertEqual(row["state"], "available")

    def test_replace_id_revises_one_draft_without_recreating_collection(self):
        case = self._case("011904")
        state = self.tools.initial_state(case)
        job = self.core.build_job(self.workload, case, state, self.cfg)
        evidence_id = next(iter(job["catalog"]["evidence"]))
        first = self._validate({
            "aus": [{"claim": "Initial source-grounded point.", "kind": None,
                     "evidence_ids": [evidence_id], "limits": None}],
            "assessed_scope_ids": [], "next_action": {"tool": "get_drafts"},
        }, job)
        state = self.tools.apply_turn(case, state, first)
        original_id = first["aus"][0]["au_id"]

        revision_job = self.core.build_job(self.workload, case, state, self.cfg)
        revision = self._validate({
            "aus": [{"claim": "Revised source-grounded point.", "kind": None,
                     "evidence_ids": [evidence_id], "limits": None, "replace_id": original_id}],
            "assessed_scope_ids": [], "next_action": {"tool": "get_drafts"},
        }, revision_job)
        self.assertFalse(revision["au_errors"], revision)
        state = self.tools.apply_turn(case, state, revision)
        self.assertEqual(len(state["drafts"]), 1)
        self.assertNotIn(original_id, state["drafts"])
        self.assertEqual(state["revisions"][-1]["superseded_id"], original_id)
        self.assertEqual(next(iter(state["drafts"].values()))["claim"], "Revised source-grounded point.")

    def test_mock_runner_budgets_receipt_replay_and_cache_tamper(self):
        workload_path = self.output_root / "input" / "workload.json"
        report = self.runner.run(workload_path, self.output_root, cfg=self.cfg, mock=True)
        self.assertEqual(report["mode"], "mock")
        self.assertFalse(report["network_executed"])
        self.assertEqual(report["provider_POST_attempts"], 0)
        self.assertLessEqual(report["transport_POST_attempts"], 12)
        ledger = _load_json(self.output_root / "mock" / "runtime_ledger.json")
        self.assertTrue(all(a["reserved_input_tokens"] <= 6000 for a in ledger["attempts"]))
        self.assertLessEqual(ledger["reserved_input_tokens"] + ledger["reserved_output_tokens"], 30000)
        self.assertEqual(report["status"], "complete")
        self.assertTrue(report["work_scope_complete"])
        self.assertEqual(report["logical_requests"], 3)
        self.assertTrue(all(item["case_source_status"] == "partial" for item in report["results"]))

        # A terminal resume is receipt-only: it must add neither model POST nor
        # transport GET after every case work scope has completed.
        resumed_terminal = self.runner.run(workload_path, self.output_root, cfg=self.cfg, mock=True)
        self.assertEqual(resumed_terminal["transport_POST_attempts"], report["transport_POST_attempts"])
        self.assertEqual(resumed_terminal["GET_polls"], report["GET_polls"])

        mock_root = self.output_root / "mock"
        ledger_path = mock_root / "runtime_ledger.json"
        ledger = _load_json(ledger_path)
        entry = next(e for e in ledger["jobs"].values() if e["status"] == "verified")
        receipt_path = mock_root / "receipts" / (entry["job"]["request_id"] + ".json")
        original_receipt = receipt_path.read_bytes()

        # Corruption must be rejected from the receipt/hash binding before any
        # dispatch. All mutations stay inside this TemporaryDirectory.
        receipt = json.loads(original_receipt.decode("utf-8"))
        receipt["normalized"]["aus"][0]["claim"] += " tampered"
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(Exception):
            self.runner.run(workload_path, self.output_root, cfg=self.cfg, mock=True)
        receipt_path.write_bytes(original_receipt)

        # Model the crash window after a valid receipt is durable but before
        # its ledger entry commits. Reconciliation must adopt that receipt,
        # never issue a duplicate POST for it.
        rid = entry["job"]["request_id"]
        ledger["jobs"][rid]["status"] = "pending"
        ledger["jobs"][rid].pop("receipt_sha256", None)
        ledger["ledger_sha256"] = self.core.fingerprint(
            {k: v for k, v in ledger.items() if k != "ledger_sha256"}
        )
        ledger_path.write_text(json.dumps(ledger, ensure_ascii=False), encoding="utf-8")
        attempts_before = report["transport_POST_attempts"]
        resumed = self.runner.run(workload_path, self.output_root, cfg=self.cfg, mock=True)
        self.assertEqual(resumed["transport_POST_attempts"], attempts_before)

    def _delivered_evidence_ids(self, job):
        catalog = _mapping(job).get("catalog", {})
        if isinstance(catalog, dict):
            refs = []
            for key in ("evidence", "delivered", "delivered_refs", "evidence_refs", "scopes"):
                val = catalog.get(key)
                if isinstance(val, dict):
                    refs.extend(val.keys())
                elif isinstance(val, list):
                    refs.extend(str(_mapping(item).get("ref_id", _mapping(item).get("evidence_id", ""))) for item in val)
            if refs:
                return list(dict.fromkeys(x for x in refs if x))
        self.fail("job does not expose its delivered evidence catalog")

    def _first_two_scope_ids(self, job):
        ids = _mapping(job).get("active_scope_ids", [])
        if len(ids) < 2:
            ids = self._delivered_evidence_ids(job)[:2]
        return ids[:2]

    @staticmethod
    def _evidence_id_in_scope(case, scope_id):
        scope = next(scope for scope in case["scopes"] if scope["scope_id"] == scope_id)
        return scope["evidence_ids"][0]


if __name__ == "__main__":
    unittest.main()
