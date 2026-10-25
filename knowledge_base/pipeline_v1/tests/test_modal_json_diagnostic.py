"""Local mocked diagnostics tests; never deploy or call inference providers."""
import io
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

from knowledge_base.pipeline_v1.deployments.modal import json_diagnostic as diagnostic
from knowledge_base.pipeline_v1.deployments.modal import job_gateway as gateway
from knowledge_base.pipeline_v1.deployments.modal import json_runtime_hook as hook
from knowledge_base.pipeline_v1.tests.test_au_job_gateway_asgi import (
    TestClient, _bridge_fastapi_starlette_startup_args,
)


class DiagnosticTests(unittest.TestCase):
    def test_filter_and_fixed_inspection_budgets(self):
        secret = "secret-credential-and-model-text"
        with tempfile.TemporaryDirectory() as directory:
            for name in ("config.json", "generation_config.json", "tokenizer_config.json"):
                Path(directory, name).write_text(json.dumps({"eos_token_id": [248044, 248046],
                    "token": secret, "chat_template": secret, "model_path": secret}))
            body = {"server_args": {"grammar_backend": "xgrammar", "api_key": secret,
                    "additional_stop_token_ids": [248046]}, "model_text": secret,
                    "eos_token_id": secret}
            calls = []
            def fake(req, timeout):
                calls.append((req.full_url, req.get_method(), timeout))
                return io.BytesIO(json.dumps(body).encode())
            with patch.object(diagnostic.urllib.request, "urlopen", fake):
                result = diagnostic.RuntimeInspector(directory)()
            self.assertNotIn(secret, json.dumps(result))
            self.assertEqual([c[1] for c in calls], ["GET", "GET"])
            self.assertEqual([c[2] for c in calls], [3, 3])
            self.assertEqual(result["active_grammar_stop_set"], "unavailable")
            self.assertFalse(result["grammar_mask"]["available"])
        with self.assertRaises(ValueError):
            diagnostic.bounded_json(io.BytesIO(b"x" * (diagnostic.MAX_RESPONSE_BYTES + 1)))
        self.assertEqual(diagnostic.filtered_info({"eos_token_id": True}), {})

    def test_pinned_artifacts_and_replay_binding(self):
        payload = json.loads(diagnostic.PAYLOAD_PATH.read_text(encoding="utf-8"))
        self.assertEqual(gateway.payload_job_id(payload), diagnostic.PAYLOAD_SHA256)
        replay = diagnostic.replay_payload(payload, gateway.payload_job_id)
        self.assertNotEqual(gateway.payload_job_id(replay), diagnostic.PAYLOAD_SHA256)
        self.assertEqual({k: v for k, v in replay.items() if k != "user"}, payload)
        self.assertEqual(replay["user"], diagnostic.ATTEMPT_BINDING)
        with self.assertRaises(ValueError):
            diagnostic.replay_payload({**payload, "max_tokens": 2}, gateway.payload_job_id)

    def test_cli_readonly_and_one_post_no_retries(self):
        for execute in (False, True):
            with tempfile.TemporaryDirectory() as directory:
                calls = []
                class Opener:
                    def open(self, req, timeout):
                        calls.append(req)
                        if req.full_url.endswith("/info"):
                            return io.BytesIO(b'{"grammar_mask":{"available":false}}')
                        identity = (gateway.payload_job_id(diagnostic.replay_payload(json.loads(
                            diagnostic.PAYLOAD_PATH.read_text(encoding="utf-8")), gateway.payload_job_id))
                            if req.get_method() == "POST" else diagnostic.PAYLOAD_SHA256)
                        return io.BytesIO(json.dumps({"job_id": identity,
                            "payload_sha256": identity, "status": "completed",
                            "response": {"choices": [{"finish_reason": "stop", "message": {
                                "content": "PRIVATE MODEL OUTPUT"}}]}}).encode())
                output = Path(directory, "report.json")
                with patch.dict(diagnostic.os.environ, {"AU_URL": "https://example.invalid/v1/chat/completions",
                        "AU_TOKEN": "PRIVATE TOKEN"}), patch.object(
                        diagnostic.urllib.request, "build_opener", return_value=Opener()):
                    self.assertEqual(diagnostic.main(["--output", str(output)] +
                        (["--execute"] if execute else [])), 0)
                self.assertEqual([r.get_method() for r in calls],
                    ["GET", "GET", "POST"] if execute else ["GET", "GET"])
                report = output.read_text()
                self.assertNotIn("PRIVATE TOKEN", report)
                self.assertNotIn("PRIVATE MODEL OUTPUT", report)

    def test_modal_auth_remains_private(self):
        source = Path(gateway.__file__).with_name("qwen35_9b_l40s.py").read_text()
        self.assertIn("unauthenticated=False", source)
        self.assertIn("RuntimeInspector(model_path, startup_warmup=warmup_accounting,", source)

    def test_cli_timeout_does_not_retry_or_expose_error(self):
        calls = []
        class Opener:
            def open(self, req, timeout):
                calls.append(req.get_method())
                self_timeout = timeout
                if self_timeout != 20:
                    raise AssertionError("Unexpected timeout budget")
                raise TimeoutError("PRIVATE TOKEN from provider")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory, "report.json")
            with patch.dict(diagnostic.os.environ, {"AU_URL": "https://example.invalid/v1/chat/completions",
                    "AU_TOKEN": "PRIVATE TOKEN"}), patch.object(
                    diagnostic.urllib.request, "build_opener", return_value=Opener()):
                self.assertEqual(diagnostic.main(["--execute", "--output", str(output)]), 1)
            self.assertEqual(calls, ["GET", "GET"])
            self.assertNotIn("PRIVATE TOKEN", output.read_text())

    def test_raw_metadata_never_inferred_from_chat_stop(self):
        record = {"response": {"choices": [{"finish_reason": "stop", "matched_stop": 248046}],
            "meta_info": {"finish_reason": {"type": "stop", "matched": 248046,
                "api_key": "private"}}, "output_ids": [123, 248046]}}
        result = diagnostic.diagnostic_job(record)
        self.assertTrue(result["raw_backend_finish_reason_available"])
        self.assertEqual(result["raw_backend_finish_reason"]["matched"], 248046)
        self.assertNotIn("private", json.dumps(result))
        self.assertEqual(result["choices"][0]["matched_stop"], 248046)
        self.assertEqual(diagnostic.diagnostic_job(result), result)
        del record["response"]["meta_info"]
        self.assertFalse(diagnostic.diagnostic_job(record)["raw_backend_finish_reason_available"])

    def test_nested_config_tokenizer_allowlist_and_actual_snapshot(self):
        value = diagnostic.filtered_info({"text_config": {"eos_token_id": 248044,
            "secret": "private"}, "eos_token": "<|im_end|>"})
        self.assertEqual(value["text_config"]["eos_token_id"], 248044)
        self.assertEqual(value["eos_token"], "<|im_end|>")
        self.assertNotIn("private", json.dumps(value))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "snapshot.json")
            path.write_text(json.dumps({"available": True, "xgrammar_stop_token_ids": [248044],
                "model_eos_token_ids": [248044], "tokenizer_eos_token_id": 248046,
                "tokenizer_eos_token": "<|im_end|>", "additional_stop_token_ids": [],
                "credential": "private"}))
            with patch.object(diagnostic, "SCHEDULER_SNAPSHOT", path), patch.object(
                    diagnostic.urllib.request, "urlopen", side_effect=TimeoutError):
                report = diagnostic.RuntimeInspector(directory)()
            self.assertEqual(report["active_grammar_stop_set"], [248044])
            self.assertEqual(report["scheduler"]["tokenizer_eos_token_id"], 248046)
            self.assertNotIn("private", json.dumps(report))
            with patch.object(diagnostic, "SCHEDULER_SNAPSHOT", path), patch.object(
                    diagnostic.urllib.request, "urlopen", side_effect=TimeoutError):
                disabled = diagnostic.RuntimeInspector(directory, diagnostic_setup_available=False)()
            self.assertFalse(disabled["scheduler"]["available"])
            self.assertFalse(disabled["scheduler"]["setup_available"])
            self.assertEqual(disabled["active_grammar_stop_set"], "unavailable")

    def test_hook_syncs_constructor_preserving_result_and_errors(self):
        calls = []
        info = types.SimpleNamespace(stop_token_ids=[248044, 248046])
        class Factory:
            @staticmethod
            def from_huggingface(tokenizer, **kwargs):
                calls.append(kwargs)
                return info
        module = types.SimpleNamespace(TokenizerInfo=Factory)
        class Backend:
            def __init__(self, tokenizer, vocab_size, model_eos_token_ids=None):
                self.info = module.TokenizerInfo.from_huggingface(tokenizer,
                    vocab_size=vocab_size, stop_token_ids=model_eos_token_ids)
                self.override_stop_tokens = None
        module.XGrammarGrammarBackend = Backend
        hook.install_module(module)
        tokenizer = types.SimpleNamespace(eos_token_id=248046, eos_token="<|im_end|>",
                                        additional_stop_token_ids=[])
        with patch.object(hook, "write_snapshot") as write:
            backend = Backend(tokenizer, 248070, {248044})
        self.assertIs(backend.info, info)
        self.assertIs(module.TokenizerInfo, Factory)

        self.assertEqual(len(calls), 1)
        self.assertEqual(write.call_args.args[0]["xgrammar_stop_token_ids"], [248044, 248046])
        self.assertEqual(calls[0]["stop_token_ids"], [248044, 248046])
        with patch.object(hook, "write_snapshot", side_effect=OSError):
            self.assertIs(Backend(tokenizer, 248070, {248044}).info, info)
        self.assertEqual(len(calls), 2)
        with patch.object(Factory, "from_huggingface", side_effect=RuntimeError("original")):
            with self.assertRaisesRegex(RuntimeError, "original"):
                Backend(tokenizer, 248070, {248044})
        self.assertIs(module.TokenizerInfo, Factory)

    def test_warmup_accounting_has_explicit_unknown_fields(self):
        inspector = diagnostic.RuntimeInspector("unused")
        self.assertIsNone(inspector.startup_warmup["requests"])
        self.assertIsNone(inspector.startup_warmup["usage"])
        self.assertIsNone(inspector.startup_warmup["latency_seconds"])
        self.assertFalse(inspector.startup_warmup["included_in_diagnostic_budget"])

    def test_cli_uses_project_dotenv_settings(self):
        from knowledge_base.config import settings
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, ".env")
            path.write_text('AU_URL=https://dotenv.invalid/v1/chat/completions\nAU_TOKEN=dotenv-secret\n')
            with patch.dict(diagnostic.os.environ, {"AU_TOKEN": "environment-secret"}):
                cfg = settings(path)
            self.assertEqual(cfg["AU_TOKEN"], "environment-secret")
            self.assertEqual(cfg["AU_URL"], "https://dotenv.invalid/v1/chat/completions")


@unittest.skipIf(TestClient is None, "ASGI packages unavailable")
class DiagnosticRouteTests(unittest.TestCase):
    def setUp(self):
        _bridge_fastapi_starlette_startup_args()
        self.directory = tempfile.TemporaryDirectory()
        self.calls = []
        self.app = gateway.create_app(self.directory.name, lambda: None,
            diagnostic_inspector=lambda: self.calls.append("info") or {"available": True})
        self.app.max_body_size = None
        # Do not start a worker: admission is tested without any inference.
        self.client = TestClient(self.app)
        self.gw = self.app.state.gateway

    def tearDown(self):
        self.client.close()
        self.directory.cleanup()

    def test_readonly_busy_unavailable_and_body_whitelist(self):
        self.assertEqual(self.client.get("/v1/diagnostics/json/info").status_code, 200)
        self.assertEqual(self.calls, ["info"])
        gateway.INFERENCE_MUTEX.acquire()
        try:
            self.assertEqual(self.client.get("/v1/diagnostics/json/info").status_code, 409)
        finally:
            gateway.INFERENCE_MUTEX.release()
        self.gw.backend_uncertain = True
        self.assertEqual(self.client.get("/v1/diagnostics/json/info").status_code, 503)
        self.assertEqual(self.client.post("/v1/diagnostics/json/replay", json={
            "path": "/etc/environment"}).status_code, 400)
        self.assertEqual(self.calls, ["info"])

    def test_replay_requires_old_job_hash_terminal_and_is_idempotent(self):
        payload = json.loads(diagnostic.PAYLOAD_PATH.read_text(encoding="utf-8"))
        body = {"case_id": diagnostic.CASE_ID, "payload_sha256": diagnostic.PAYLOAD_SHA256,
                "payload": payload}
        route = "/v1/diagnostics/json/replay"
        self.assertEqual(self.client.post(route, json=body).status_code, 404)
        self.gw.submit(diagnostic.PAYLOAD_SHA256, payload)
        self.assertEqual(self.client.post(route, json=body).status_code, 409)
        original = self.gw.read(diagnostic.PAYLOAD_SHA256)
        original["status"] = "completed"
        self.gw.persist(original)
        gateway.INFERENCE_MUTEX.acquire()
        try:
            self.assertEqual(self.client.post(route, json=body).status_code, 409)
        finally:
            gateway.INFERENCE_MUTEX.release()
        bad = {**body, "payload": {**payload, "temperature": 1}}
        self.assertEqual(self.client.post(route, json=bad).status_code, 409)
        first = self.client.post(route, json=body)
        self.assertEqual(first.status_code, 202)
        second = self.client.post(route, json=body)
        self.assertEqual(second.json()["job_id"], first.json()["job_id"])
        self.assertEqual(len(list(Path(self.directory.name).glob("*.json"))), 2)
        with patch.object(self.gw, "call_backend", return_value=(200, b'{"usage":{"completion_tokens":1}}')) as backend:
            record = self.gw.read(first.json()["job_id"])
            with gateway.INFERENCE_MUTEX:
                self.gw.execute(record)
            self.assertEqual(self.client.post(route, json=body).json()["status"], "completed")
            backend.assert_called_once()


if __name__ == "__main__":
    unittest.main()
