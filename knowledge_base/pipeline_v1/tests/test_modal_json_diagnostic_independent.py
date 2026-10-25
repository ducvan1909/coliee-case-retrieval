"""Independent local contracts with real FastAPI/TestClient and mocked backend.

Never import/deploy Modal or contact a real provider. HTTP tests use the local
ASGI transport; they do not verify the external Modal authentication proxy.
"""
import ast
import asyncio
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import threading
import types
import unittest
import sys
from unittest.mock import patch
from knowledge_base.pipeline_v1.deployments.modal import json_diagnostic as diagnostic
from fastapi import HTTPException
from fastapi.testclient import TestClient
ROOT = Path(__file__).resolve().parents[1]
GATEWAY = ROOT / "deployments/modal/job_gateway.py"
SERVER = ROOT / "deployments/modal/qwen35_9b_l40s.py"


class Response:
    def __init__(self, content=None, status_code=200, **kwargs):
        self.content, self.status_code = content, status_code


class Request:
    def __init__(self, payload):
        self.raw = json.dumps(payload).encode()

    async def stream(self):
        yield self.raw


def load_gateway():
    spec = importlib.util.spec_from_file_location(
        "knowledge_base.pipeline_v1.deployments.modal.independent_gateway", GATEWAY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assigned_ast(name):
    tree = ast.parse(SERVER.read_text(encoding="utf-8"))
    return next(n.value for n in tree.body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == name for t in n.targets))


class DeploymentBoundaryTests(unittest.TestCase):
    def test_modal_server_remains_private_without_importing_modal(self):
        tree = ast.parse(SERVER.read_text(encoding="utf-8"))
        decorators = [d for n in ast.walk(tree) if isinstance(n, ast.ClassDef)
                      for d in n.decorator_list if isinstance(d, ast.Call)
                      and isinstance(d.func, ast.Attribute) and d.func.attr == "server"]
        self.assertEqual(len(decorators), 1)
        auth = [k.value for k in decorators[0].keywords if k.arg == "unauthenticated"]
        self.assertEqual(len(auth), 1)
        self.assertIs(ast.literal_eval(auth[0]), False)

    def test_server_args_and_explicit_warmup_payload_unchanged(self):
        expected = {
            "SERVER_ARGS": "1c91f7f75222f579ea41948260338f1c57eb75c6e13f40b124c86bd56b02ff4f",
            "WARMUP_PAYLOAD": "3d6a65dc01679694c15182c0dca95759e3418b902a8966d1c41be4297f1d3d14",
        }
        for name, digest in expected.items():
            with self.subTest(name=name):
                self.assertEqual(hashlib.sha256(ast.dump(assigned_ast(name)).encode()).hexdigest(), digest)

    def test_grammar_schema_and_execution_policy_unchanged(self):
        expected = {
            "repair_agent/grammar.py": "7912051a99ad19036f9f59b90830e73a91bddfa685c29eca17a0160656b12702",
            "contracts/annotation_schema.v1.json": "32ef1c98a216e28f202209662f80a04d38b44b94146fa9861b30abb56ee6236d",
            "policies/execution_policy.v1.json": "b6b568dad554c64aeb30325e30cbf38dd8e4c776522496feb5e0c5386977cd5a",
            "policies/au_annotation_policy.v1.json": "ea28ac154c0dff527b64faaad89be8564f3bb69f31e856c3b31e7beb68c183ec",
        }
        for name, digest in expected.items():
            with self.subTest(name=name):
                self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), digest)


class GatewayBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.module = load_gateway()
        self.tmp = tempfile.TemporaryDirectory()
        self.commits = []
        self.app = self.module.create_app(self.tmp.name, lambda: self.commits.append(1))
        self.gateway = self.app.state.gateway
        self.calls = []
        self.gateway.call_backend = self.backend
        self.payload = {"model": "mock-qwen", "messages": [{"role": "user", "content": "mock"}],
                        "max_tokens": 16, "temperature": 0, "stream": False,
                        "ebnf": 'root ::= "ok"'}

    def tearDown(self):
        self.tmp.cleanup()

    def backend(self, payload):
        self.calls.append(payload)
        return 200, b'{"choices":[{"message":{"content":"ok"}}]}'

    def invoke(self, method, path, *args):
        # No lifespan: cold-start inference is intentionally tested separately.
        # Real FastAPI routing/body parsing/errors run over TestClient ASGI.
        client = TestClient(self.app)
        try:
            if method == "GET":
                if args:
                    path = path.replace("{job_id}", args[0])
                response = client.get(path)
            else:
                response = client.post(path, content=args[0].raw,
                                       headers={"Content-Type": "application/json"})
            value = response.json()
            if response.status_code >= 400:
                raise HTTPException(response.status_code, value.get("detail"))
            return value if method == "GET" else Response(value, response.status_code)
        finally:
            client.close()

    def sync(self):
        return self.invoke("POST", "/v1/chat/completions", Request(self.payload))

    def test_existing_job_read_never_dispatches_or_commits(self):
        jid = self.module.payload_job_id(self.payload)
        record = {"job_id": jid, "payload": self.payload, "status": "queued"}
        path = Path(self.tmp.name) / (jid + ".json")
        path.write_bytes(self.module.canonical_payload(record))
        before = path.read_bytes()
        result = self.invoke("GET", "/v1/jobs/{job_id}", jid)
        self.assertEqual(result["status"], "queued")
        self.assertNotIn("payload", result)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.commits, [])
        self.assertIsNone(self.gateway.worker)

    def test_busy_rejects_immediately_without_delayed_dispatch(self):
        with self.module.INFERENCE_MUTEX:
            with self.assertRaises(HTTPException) as caught:
                self.sync()
            self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(self.calls, [])
        self.assertIsNone(self.gateway.worker)
        self.assertTrue(self.module.INFERENCE_MUTEX.acquire(blocking=False))
        self.module.INFERENCE_MUTEX.release()

    def test_one_backend_call_preserves_request_bound_grammar(self):
        before = self.module.canonical_payload(self.payload)
        response = self.sync()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.module.canonical_payload(self.calls[0]), before)
        self.assertEqual(self.module.canonical_payload(self.payload), before)

    def test_unknown_backend_outcome_no_retry_and_future_dispatch_blocked(self):
        def unknown(payload):
            self.calls.append(payload)
            raise TimeoutError("secret credential must not escape")
        self.gateway.call_backend = unknown
        with self.assertRaises(HTTPException) as caught:
            self.sync()
        self.assertEqual(caught.exception.status_code, 504)
        self.assertNotIn("secret", str(caught.exception))
        with self.assertRaises(HTTPException) as caught:
            self.sync()
        self.assertEqual(caught.exception.status_code, 503)
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(self.module.INFERENCE_MUTEX.acquire(blocking=False))
        self.module.INFERENCE_MUTEX.release()

    def test_bad_job_id_read_is_bounded_without_backend(self):
        for jid in ("../secret", "A" * 64, "a" * 63, "a" * 65):
            with self.subTest(jid=jid), self.assertRaises(HTTPException) as caught:
                self.invoke("GET", "/v1/jobs/{job_id}", jid)
            self.assertIn(caught.exception.status_code, (400, 404))
        self.assertEqual(self.calls, [])

    def seed_original(self, status="completed"):
        payload = json.loads(diagnostic.PAYLOAD_PATH.read_text(encoding="utf-8"))
        self.assertEqual(self.module.payload_job_id(payload), diagnostic.PAYLOAD_SHA256)
        self.gateway.persist({"job_id": diagnostic.PAYLOAD_SHA256,
                              "payload": payload, "status": status, "created_at": "old"})
        return {"case_id": diagnostic.CASE_ID,
                "payload_sha256": diagnostic.PAYLOAD_SHA256, "payload": payload}

    def replay(self, value):
        return self.invoke("POST", "/v1/diagnostics/json/replay", Request(value))

    def test_diagnostic_info_busy_never_starts_inspector(self):
        inspected = []
        self.app = self.module.create_app(self.tmp.name, lambda: None,
            diagnostic_inspector=lambda: inspected.append(1) or {})
        with self.module.INFERENCE_MUTEX:
            with self.assertRaises(HTTPException) as caught:
                self.invoke("GET", "/v1/diagnostics/json/info")
            self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(inspected, [])
        self.assertEqual(self.calls, [])

    def test_no_diagnostic_rpc_accepts_arbitrary_source_or_code(self):
        with self.assertRaises(HTTPException) as caught:
            self.replay({"case_id": diagnostic.CASE_ID,
                         "payload_sha256": diagnostic.PAYLOAD_SHA256,
                         "payload": {}, "code": "raise SystemExit", "path": "/etc/environment"})
        self.assertEqual(caught.exception.status_code, 400)
        client = TestClient(self.app)
        try:
            response = client.post("/v1/diagnostics/json/info", json={"code": "x", "path": "x"})
        finally:
            client.close()
        self.assertIn(response.status_code, (404, 405))
        self.assertEqual(self.calls, [])
        self.assertEqual(self.commits, [])


    def test_diagnostic_info_error_releases_lock_and_redacts_exception(self):
        def inspect():
            raise RuntimeError("credential sentinel")
        self.app = self.module.create_app(self.tmp.name, lambda: None,
                                          diagnostic_inspector=inspect)
        with self.assertRaises(HTTPException) as caught:
            self.invoke("GET", "/v1/diagnostics/json/info")
        self.assertEqual(caught.exception.status_code, 503)
        self.assertNotIn("sentinel", str(caught.exception))
        self.assertTrue(self.module.INFERENCE_MUTEX.acquire(blocking=False))
        self.module.INFERENCE_MUTEX.release()

    def test_replay_busy_and_unavailable_never_admit_delayed_job(self):
        value = self.seed_original()
        self.commits.clear()
        with self.module.INFERENCE_MUTEX:
            with self.assertRaises(HTTPException) as caught:
                self.replay(value)
            self.assertEqual(caught.exception.status_code, 409)
        for attr in ("poisoned", "backend_uncertain"):
            setattr(self.gateway, attr, True)
            with self.assertRaises(HTTPException) as caught:
                self.replay(value)
            self.assertEqual(caught.exception.status_code, 503)
            setattr(self.gateway, attr, False)
        self.gateway.stop_event.set()
        with self.assertRaises(HTTPException) as caught:
            self.replay(value)
        self.assertEqual(caught.exception.status_code, 503)
        self.assertEqual(len(list(Path(self.tmp.name).glob("*.json"))), 1)
        self.assertEqual(self.commits, [])
        self.assertEqual(self.calls, [])

    def test_replay_rejects_nonterminal_original_and_altered_grammar(self):
        value = self.seed_original("running")
        with self.assertRaises(HTTPException) as caught:
            self.replay(value)
        self.assertEqual(caught.exception.status_code, 409)
        value["payload"]["ebnf"] = 'root ::= "replacement"'
        with self.assertRaises(HTTPException) as caught:
            self.replay(value)
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(len(list(Path(self.tmp.name).glob("*.json"))), 1)
        self.assertEqual(self.calls, [])

    def test_duplicate_replay_dispatches_once_and_resume_never_retries(self):
        value = self.seed_original()
        first = self.replay(value).content
        second = self.replay(value).content
        self.assertEqual(first["job_id"], second["job_id"])
        self.assertEqual(len(list(Path(self.tmp.name).glob("*.json"))), 2)
        record = self.gateway.read(first["job_id"])
        original = dict(record["payload"])
        self.assertEqual(original.pop("user"), diagnostic.ATTEMPT_BINDING)
        self.assertEqual(original, value["payload"])
        completed = threading.Event()
        execute = self.gateway.execute
        def monitored(record):
            execute(record)
            completed.set()
        self.gateway.execute = monitored
        self.gateway.start()
        try:
            self.assertTrue(completed.wait(2), "mock job did not complete")
        finally:
            self.gateway.stop(grace_seconds=2)
        self.assertFalse(self.gateway.worker.is_alive(), "worker leaked")
        self.assertEqual(len(self.calls), 1)
        resumed = self.module.create_app(self.tmp.name, lambda: None).state.gateway
        resumed.call_backend = self.backend
        resumed.start()
        resumed.stop(grace_seconds=2)
        self.assertFalse(resumed.worker.is_alive())
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(resumed.read(first["job_id"])["status"], "completed")

    def test_unknown_replay_outcome_and_restart_do_not_dispatch_again(self):
        value = self.seed_original()
        admitted = self.replay(value).content
        record = self.gateway.read(admitted["job_id"])
        record["status"] = "running"
        self.gateway.persist(record)
        recovered = self.module.create_app(self.tmp.name, lambda: None).state.gateway
        recovered.recover()
        self.assertEqual(recovered.read(admitted["job_id"])["status"], "interrupted")
        self.app = self.module.create_app(self.tmp.name, lambda: None)
        self.gateway = self.app.state.gateway
        repeated = self.replay(value).content
        self.assertEqual(repeated["status"], "interrupted")
        self.assertEqual(repeated["job_id"], admitted["job_id"])
        self.assertEqual(len(list(Path(self.tmp.name).glob("*.json"))), 2)
        self.assertEqual(self.calls, [])


class DiagnosticMetadataTests(unittest.TestCase):
    def test_scheduler_capture_has_typed_eos_only_and_unavailable_is_not_active(self):
        def open_mock(req, timeout):
            return io.BytesIO(b'{}')
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = Path(tmp) / "scheduler.json"
            snapshot.write_text(json.dumps({"available": True, "xgrammar_stop_token_ids": [248044],
                "model_eos_token_ids": [248044], "tokenizer_eos_token_id": 248046,
                "additional_stop_token_ids": [248046], "override_stop_tokens": None,
                "env": {"AU_TOKEN": "credential-sentinel"}, "server_args": {"api_key": "credential-sentinel"}}))
            with patch.object(diagnostic, "SCHEDULER_SNAPSHOT", snapshot), \
                 patch.object(diagnostic.urllib.request, "urlopen", open_mock), \
                 patch.object(diagnostic, "version", return_value="mock-version"):
                result = diagnostic.RuntimeInspector(tmp)()
                self.assertEqual(result["active_grammar_stop_set"], [248044])
                self.assertEqual(result["scheduler"]["tokenizer_eos_token_id"], 248046)
                self.assertNotIn("credential-sentinel", json.dumps(result))
                snapshot.write_text(json.dumps({"available": False, "xgrammar_stop_token_ids": [248044]}))
                result = diagnostic.RuntimeInspector(tmp)()
                self.assertEqual(result["active_grammar_stop_set"], "unavailable")
                self.assertFalse(result["scheduler"]["available"])
                snapshot.write_text(json.dumps({"available": True, "xgrammar_stop_token_ids": [248044]}))
                disabled = diagnostic.RuntimeInspector(tmp, diagnostic_setup_available=False)()
                self.assertEqual(disabled["active_grammar_stop_set"], "unavailable")
                self.assertFalse(disabled["scheduler"]["available"], "Failed setup reused an old valid snapshot")

    def test_real_multimodal_config_nested_text_eos_survives_filter(self):
        path = ROOT / "outputs/plan12_json_diagnostic_20261012/server_model_config.json"
        config = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(config["text_config"]["eos_token_id"], 248044)
        summary = diagnostic.filtered_info(config)
        def carried_eos(value):
            if isinstance(value, dict):
                return any((key == "eos_token_id" and item == 248044)
                           or carried_eos(item) for key, item in value.items())
            return False
        self.assertTrue(carried_eos(summary), "Actual Qwen text_config.eos_token_id was lost")
        self.assertNotIn("layer_types", json.dumps(summary))
        self.assertNotIn("hidden_size", json.dumps(summary))

    def test_real_saved_server_job_identity_content_and_matched_stop(self):
        path = ROOT / "outputs/plan12_json_diagnostic_20261012/server_job.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        saved = json.loads(diagnostic.RESULT_PATH.read_text(encoding="utf-8"))
        module = load_gateway()
        self.assertEqual(module.payload_job_id(record["payload"]), record["job_id"])
        self.assertEqual(module.payload_job_id(record["response"]), record["response_sha256"])
        choice = record["response"]["choices"][0]
        self.assertEqual(choice["matched_stop"], 248046)
        self.assertEqual(choice["message"]["content"], saved["receipt"]["raw_content"])
        summary = diagnostic.diagnostic_job(record)
        def carried_stop(value):
            if isinstance(value, dict):
                return any((key in ("matched", "matched_stop") and
                            (item == 248046 or isinstance(item, list) and 248046 in item))
                           or carried_stop(item) for key, item in value.items())
            if isinstance(value, list):
                return any(carried_stop(item) for item in value)
            return False
        self.assertTrue(carried_stop(summary), "Known server matched_stop=248046 was dropped from diagnostic")

    def test_chat_finish_stop_is_not_raw_stop_token_evidence(self):
        result = diagnostic.diagnostic_job({"response": {"choices": [
            {"finish_reason": "stop", "message": {"content": "private-sentinel"}}]}})
        self.assertEqual(result["finish_reasons"], ["stop"])
        self.assertFalse(result["raw_backend_finish_reason_available"])
        self.assertFalse(result["generated_token_ids_available"])
        self.assertNotIn("private-sentinel", json.dumps(result))

    def test_actual_carried_raw_token_metadata_is_filtered_without_invention(self):
        result = diagnostic.diagnostic_job({"response": {
            "meta_info": {"finish_reason": {"type": "stop", "matched": 248046,
                                             "api_key": "private-sentinel"}},
            "output_ids": [7, 248046]}})
        self.assertTrue(result["raw_backend_finish_reason_available"])
        self.assertEqual(result["raw_backend_finish_reason"], {"type": "stop", "matched": 248046})
        self.assertEqual(result["generated_token_ids"], [7, 248046])
        self.assertNotIn("private-sentinel", json.dumps(result))

    def test_metadata_allowlist_excludes_environment_and_arbitrary_values(self):
        raw = {"env": {"AU_TOKEN": "secret-sentinel"}, "api_key": "secret-sentinel",
               "model_path": "secret-sentinel", "eos_token_id": "secret-sentinel",
               "eos_token_ids": [248044, 248046], "context_length": True,
               "reasoning_parser": "secret-sentinel", "grammar_backend": "xgrammar",
               "server_args": {"env": "secret-sentinel", "api_key": "secret-sentinel",
                               "eos_token_id": 248046, "trust_remote_code": True}}
        filtered = diagnostic.filtered_info(raw)
        self.assertEqual(filtered, {"eos_token_ids": [248044, 248046],
                                   "grammar_backend": "xgrammar",
                                   "server_args": {"eos_token_id": 248046}})
        self.assertNotIn("secret-sentinel", json.dumps(filtered))

    def test_token_ids_type_and_size_are_bounded(self):
        for value in (True, -1, 10_000_000, [False], [1] * 129, "248046", {"id": 1}):
            with self.subTest(value=str(value)[:30]):
                self.assertIsNone(diagnostic.token_ids(value))

    def test_response_read_budget_is_enforced(self):
        with self.assertRaises(ValueError):
            diagnostic.bounded_json(io.BytesIO(b" " * (diagnostic.MAX_RESPONSE_BYTES + 1)))

    def test_runtime_inspection_only_gets_and_marks_active_stop_set_unavailable(self):
        requests = []
        backend = {"eos_token_id": 248044, "env": {"AU_TOKEN": "secret-sentinel"},
                   "server_args": {"eos_token_id": 248046, "api_key": "secret-sentinel"}}
        def open_mock(req, timeout):
            requests.append((req.full_url, req.get_method(), req.data, timeout))
            return io.BytesIO(json.dumps(backend).encode())
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("config.json", "generation_config.json", "tokenizer_config.json"):
                (Path(tmp) / name).write_text(json.dumps(backend), encoding="utf-8")
            with patch.object(diagnostic.urllib.request, "urlopen", open_mock), \
                 patch.object(diagnostic, "version", return_value="mock-version"):
                result = diagnostic.RuntimeInspector(tmp)()
        self.assertEqual(len(requests), 2)
        self.assertTrue(all(method == "GET" and data is None and timeout == 3
                            for url, method, data, timeout in requests))
        self.assertEqual({url for url, *_ in requests}, {
            "http://127.0.0.1:8001/get_server_info", "http://127.0.0.1:8001/get_model_info"})
        self.assertEqual(result["active_grammar_stop_set"], "unavailable")
        self.assertFalse(result["grammar_mask"]["available"])
        self.assertFalse(result["token_trace"]["available"])
        self.assertNotIn("secret-sentinel", json.dumps(result))
        for row in result["model_files"].values():
            self.assertEqual(row["evidence"], "checkpoint_metadata_not_active_scheduler")


class DiagnosticCLITests(unittest.TestCase):
    def run_mock_cli(self, *, execute=False, fail_post=False, mismatched_replay=False,
                     summarized_trace=False):
        calls = []
        old = {"job_id": diagnostic.PAYLOAD_SHA256,
               "payload_sha256": diagnostic.PAYLOAD_SHA256, "status": "completed",
               "payload": {"private": "must-not-echo"},
               "response": {"choices": [{"message": {"content": "must-not-echo"},
                                         "finish_reason": "stop"}]},
               "usage": {"prompt_tokens": 1151, "completion_tokens": 101}}
        class Opener:
            def open(self, req, timeout):
                calls.append(req)
                if req.get_method() == "POST":
                    if fail_post:
                        raise TimeoutError("secret-sentinel")
                    payload = json.loads(req.data)["payload"]
                    replay = {**payload, "user": diagnostic.ATTEMPT_BINDING}
                    jid = hashlib.sha256(json.dumps(replay, sort_keys=True, separators=(",", ":"),
                        ensure_ascii=False, allow_nan=False).encode()).hexdigest()
                    row = {"status": "queued", "job_id": "a" * 64 if mismatched_replay else jid,
                           "payload_sha256": "a" * 64 if mismatched_replay else jid}
                    if summarized_trace:
                        row.update(status="completed", finish_reasons=["stop"],
                            choices=[{"finish_reason": "stop", "matched_stop": 248046}],
                            raw_backend_finish_reason_available=True,
                            raw_backend_finish_reason={"type": "stop", "matched": 248046},
                            generated_token_ids_available=True, generated_token_ids=[7, 248046])
                elif "/jobs/" in req.full_url:
                    row = old
                else:
                    row = {"active_grammar_stop_set": "unavailable"}
                return io.BytesIO(json.dumps(row).encode())
        def build(handler):
            self.assertIsNone(handler.redirect_request(None, None, None, None, None, None))
            return Opener()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.json"
            module = load_gateway()
            with patch.dict("sys.modules", {
                "knowledge_base.pipeline_v1.deployments.modal.job_gateway": module}), \
                 patch.dict(diagnostic.os.environ, {
                     "AU_URL": "https://private.invalid/v1/chat/completions",
                     "AU_TOKEN": "secret-sentinel"}), \
                 patch.object(diagnostic.urllib.request, "build_opener", build):
                code = diagnostic.main(["--output", str(out)] + (["--execute"] if execute else []))
            report = json.loads(out.read_text(encoding="utf-8"))
        self.assertNotIn("secret-sentinel", json.dumps(report))
        self.assertNotIn("must-not-echo", json.dumps(report))
        self.assertTrue(all(req.get_header("Authorization") == "Bearer secret-sentinel"
                            for req in calls))
        return code, report, calls

    def test_cli_read_existing_job_is_get_only(self):
        code, report, calls = self.run_mock_cli()
        self.assertEqual(code, 0)
        self.assertEqual([req.get_method() for req in calls], ["GET", "GET"])
        self.assertEqual(report["original_job"]["status"], "completed")
        self.assertFalse(report["execute"])
        self.assertEqual(report.get("max_diagnostic_inferences", report.get("max_new_inferences")), 0)

    def test_cli_explicit_replay_one_post_uses_exact_saved_payload(self):
        code, report, calls = self.run_mock_cli(execute=True)
        self.assertEqual(code, 0)
        self.assertEqual([req.get_method() for req in calls], ["GET", "GET", "POST"])
        posted = json.loads(calls[-1].data)
        expected = json.loads(diagnostic.PAYLOAD_PATH.read_text(encoding="utf-8"))
        self.assertEqual(posted["payload"], expected)
        self.assertEqual(posted["payload_sha256"], diagnostic.PAYLOAD_SHA256)
        self.assertEqual(report.get("max_diagnostic_inferences", report.get("max_new_inferences")), 1)
        self.assertNotEqual(report["replay_payload_sha256"], diagnostic.PAYLOAD_SHA256)

    def test_cli_post_timeout_has_no_hidden_retry_and_retains_attempt_id(self):
        code, report, calls = self.run_mock_cli(execute=True, fail_post=True)
        self.assertEqual(code, 1)
        self.assertEqual(len([req for req in calls if req.get_method() == "POST"]), 1)
        self.assertIn("error", report)
        self.assertEqual(len(report["replay_payload_sha256"]), 64)

    def test_cli_accounts_for_startup_warmup_separately(self):
        _, report, _ = self.run_mock_cli()
        startup = report.get("startup_warmup")
        self.assertIsInstance(startup, dict,
            "A prose caveat does not provide a separate warmup count/unknown in request trace")
        self.assertTrue("count" in startup or "requests" in startup)
        count = startup.get("count", startup.get("requests"))
        self.assertTrue(count is None or type(count) is int)
        if count is None:
            self.assertTrue(startup.get("outcome") == "not_observed" or startup.get("reason"))

    def test_cli_rejects_replay_receipt_for_a_different_job(self):
        code, report, _ = self.run_mock_cli(execute=True, mismatched_replay=True)
        self.assertEqual(code, 1, "CLI accepted a replay receipt whose identity differs from submitted attempt")
        self.assertIn("error", report)

    def test_cli_preserves_filtered_replay_trace_returned_by_gateway(self):
        code, report, _ = self.run_mock_cli(execute=True, summarized_trace=True)
        self.assertEqual(code, 0)
        replay = report["replay_job"]
        self.assertTrue(replay["raw_backend_finish_reason_available"],
                        "Already filtered replay trace was lost by filtering as a full job record again")
        self.assertEqual(replay["raw_backend_finish_reason"], {"type": "stop", "matched": 248046})
        self.assertEqual(replay["generated_token_ids"], [7, 248046])
        self.assertEqual(replay["finish_reasons"], ["stop"])


class BackendHookTests(unittest.TestCase):
    def setUp(self):
        path = ROOT / "deployments/modal/json_runtime_hook.py"
        spec = importlib.util.spec_from_file_location("independent_runtime_hook", path)
        self.hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.hook)
        self.calls = []
        self.rows = []
        self.module = types.SimpleNamespace()
        module = self.module
        calls = self.calls
        self.result = object()
        result = self.result
        self.real_info = types.SimpleNamespace(stop_token_ids=[248044, 248046])
        real_info = self.real_info
        class Info:
            @staticmethod
            def from_huggingface(tokenizer, **kwargs):
                calls.append((tokenizer, kwargs))
                return real_info
        class Backend:
            def __init__(self, tokenizer, vocab_size=248320, model_eos_token_ids=None):
                self.info = module.TokenizerInfo.from_huggingface(tokenizer,
                    stop_token_ids=model_eos_token_ids)
                self.override_stop_tokens = None
                self.decode_state = ["original"]
                return result
            def dispatch_ebnf(self, grammar):
                return ("original-decode", grammar)
        module.TokenizerInfo, module.XGrammarGrammarBackend = Info, Backend
        self.factory = Info
        self.backend_cls = Backend
        self.decode = Backend.dispatch_ebnf
        self.tokenizer = types.SimpleNamespace(eos_token_id=248046, eos_token="<|im_end|>",
                                              additional_stop_token_ids=[248046])

    def construct(self):
        instance = self.backend_cls.__new__(self.backend_cls)
        returned = self.backend_cls.__init__(instance, self.tokenizer,
                                            model_eos_token_ids={248044})
        return instance, returned

    def test_init_wrapper_preserves_original_result_and_decode_identity(self):
        with patch.object(self.hook, "write_snapshot", side_effect=self.rows.append):
            self.hook.install_module(self.module)
            instance, returned = self.construct()
        self.assertIs(returned, self.result, "Original constructor return was replaced")
        self.assertIs(self.module.TokenizerInfo, self.factory)
        self.assertIs(instance.info, self.real_info, "Hook must return original real TokenizerInfo object")
        self.assertIs(self.backend_cls.dispatch_ebnf, self.decode)
        self.assertEqual(instance.decode_state, ["original"])
        self.assertEqual(instance.dispatch_ebnf("pinned"), ("original-decode", "pinned"))
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.rows[-1]["xgrammar_stop_token_ids"], [248044, 248046])
        self.assertEqual(self.rows[-1]["tokenizer_eos_token_id"], 248046)

    def test_init_original_exception_identity_and_factory_restoration(self):
        error = RuntimeError("original exception sentinel")
        def original(instance, tokenizer, vocab_size=248320, model_eos_token_ids=None):
            self.module.TokenizerInfo.from_huggingface(tokenizer,
                stop_token_ids=model_eos_token_ids)
            raise error
        self.backend_cls.__init__ = original
        with patch.object(self.hook, "write_snapshot", side_effect=self.rows.append):
            self.hook.install_module(self.module)
            with self.assertRaises(RuntimeError) as caught:
                self.construct()
        self.assertIs(caught.exception, error)
        self.assertIs(self.module.TokenizerInfo, self.factory)
        self.assertEqual(self.rows, [])

    def test_unreadable_sync_field_fails_closed(self):
        class BrokenTokenizer:
            @property
            def eos_token_id(self):
                raise ValueError("credential sentinel")
        self.tokenizer = BrokenTokenizer()
        with patch.object(self.hook, "write_snapshot", side_effect=self.rows.append):
            self.hook.install_module(self.module)
            with self.assertRaises(self.hook.EOSSyncError):
                self.construct()
        self.assertIs(self.module.TokenizerInfo, self.factory)
        self.assertEqual(self.calls, [])
        self.assertNotIn("credential sentinel", json.dumps(self.rows))

    def test_install_is_idempotent_and_does_not_replace_decode(self):
        self.hook.install_module(self.module)
        wrapped = self.backend_cls.__init__
        self.hook.install_module(self.module)
        self.assertIs(self.backend_cls.__init__, wrapped)
        self.assertIs(self.backend_cls.dispatch_ebnf, self.decode)

    def test_import_loader_preserves_original_import_exception(self):
        error = ImportError("original import failure")
        class Loader:
            def exec_module(self, module):
                raise error
        with self.assertRaises(ImportError) as caught:
            self.hook.ObserverLoader(Loader()).exec_module(self.module)
        self.assertIs(caught.exception, error)

    def test_finder_does_not_intercept_other_modules(self):
        with patch.object(self.hook.importlib.machinery.PathFinder, "find_spec") as finder:
            self.assertIsNone(self.hook.ObserverFinder().find_spec("arbitrary.user.source"))
        finder.assert_not_called()

    def test_finder_preserves_original_package_path_and_target_arguments(self):
        path, target = object(), object()
        original_loader = object()
        spec = types.SimpleNamespace(loader=original_loader)
        with patch.object(self.hook.importlib.machinery.PathFinder, "find_spec", return_value=spec) as finder:
            returned = self.hook.ObserverFinder().find_spec(self.hook.TARGET, path, target)
        finder.assert_called_once_with(self.hook.TARGET, path, target)
        self.assertIs(returned, spec)
        self.assertIs(returned.loader.delegate, original_loader)

    def test_loader_create_module_returns_original_identity(self):
        expected, spec = object(), object()
        calls = []
        class Loader:
            def create_module(self, value):
                calls.append(value)
                return expected
        self.assertIs(self.hook.ObserverLoader(Loader()).create_module(spec), expected)
        self.assertEqual(calls, [spec])

    def check_startup_diagnostic_failure(self, stage):
        tree = ast.parse(SERVER.read_text(encoding="utf-8"))
        server = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Server")
        startup = next(n for n in server.body if isinstance(n, ast.FunctionDef) and n.name == "startup")
        startup.decorator_list = []
        namespace = {"Path": Path, "_ensure_model_downloaded": lambda: "/mock-pinned-model",
                     "MODEL_PORT": 8001, "STARTUP_TIMEOUT": 3600, "SERVER_ARGS": {}}
        exec(compile(ast.Module(body=[startup], type_ignores=[]), str(SERVER), "exec"), namespace)
        original_error = RuntimeError("original backend startup sentinel")
        diagnostic_error = RuntimeError("diagnostic install credential sentinel")
        class BrokenSnapshotPath:
            def __init__(self, value):
                pass
            def unlink(self, **kwargs):
                raise PermissionError("diagnostic snapshot cleanup sentinel")
        if stage == "cleanup":
            namespace["Path"] = BrokenSnapshotPath
        class Endpoint:
            def __init__(self, **kwargs):
                pass
            def start(self):
                raise original_error
        endpoint_module = types.ModuleType("autoinference_utils.endpoint")
        endpoint_module.SGLangEndpoint = Endpoint
        hook_module = types.ModuleType("json_runtime_hook")
        def fail_install():
            if stage == "install":
                raise diagnostic_error
        hook_module.install = fail_install
        with patch.dict("sys.modules", {"autoinference_utils.endpoint": endpoint_module,
                                          "json_runtime_hook": hook_module,
                                          "uvicorn": types.ModuleType("uvicorn")}), \
             patch.object(sys, "path", list(sys.path)):
            with self.assertRaises(Exception) as caught:
                namespace["startup"](types.SimpleNamespace())
        self.assertIs(caught.exception, diagnostic_error if stage == "install" else original_error)

    def test_startup_sync_install_failure_blocks_backend(self):
        self.check_startup_diagnostic_failure("install")

    def test_startup_snapshot_cleanup_failure_does_not_block_original_backend(self):
        self.check_startup_diagnostic_failure("cleanup")


if __name__ == "__main__":
    unittest.main()
