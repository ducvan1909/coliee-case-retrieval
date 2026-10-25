"""Independent EOS contract checks; no serving imports, network, or snapshot writes."""
import ast
import hashlib
import importlib.util
import inspect
import json
from pathlib import Path
import runpy
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "deployments/modal/json_runtime_hook.py"


class EOSSyncIndependentTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("eos_sync_independent_hook", HOOK)
        self.hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.hook)
        self.rows, self.calls, self.inputs = [], [], []
        self.result = object()
        self.module = types.SimpleNamespace()
        module, calls, inputs, result = self.module, self.calls, self.inputs, self.result

        class Factory:
            @staticmethod
            def from_huggingface(tokenizer, vocab_size=None, stop_token_ids=None,
                                 *, marker=None):
                calls.append((tokenizer, vocab_size, stop_token_ids, marker))
                stops = stop_token_ids
                if stops is None:
                    stops = tokenizer.eos_token_id
                if type(stops) is int:
                    stops = [stops]
                return types.SimpleNamespace(stop_token_ids=list(stops or []))

        class Backend:
            def __init__(self, tokenizer, vocab_size=248320, model_eos_token_ids=None,
                         *, marker=None, init_xgrammar=True):
                inputs.append((tokenizer, vocab_size, model_eos_token_ids, marker, init_xgrammar))
                self.override_stop_tokens = None
                if init_xgrammar:
                    self.info = module.TokenizerInfo.from_huggingface(
                        tokenizer, vocab_size=vocab_size,
                        stop_token_ids=model_eos_token_ids, marker=marker)
                    # Compiler captures its info at creation; later mutation is too late.
                    self.compiler_stops = tuple(self.info.stop_token_ids)
                return result

        self.factory = module.TokenizerInfo = Factory
        self.backend = module.XGrammarGrammarBackend = Backend
        self.tokenizer = types.SimpleNamespace(eos_token_id=248046,
            eos_token="<|im_end|>", additional_stop_token_ids=[])
        self.writer = patch.object(self.hook, "write_snapshot", side_effect=self.rows.append)
        self.writer.start()
        self.addCleanup(self.writer.stop)

    def construct(self, model=None, *, positional=False, **kwargs):
        self.hook.install_module(self.module)
        instance = self.backend.__new__(self.backend)
        if positional:
            returned = self.backend.__init__(instance, self.tokenizer, 248320, model, **kwargs)
        else:
            returned = self.backend.__init__(instance, tokenizer=self.tokenizer,
                                             model_eos_token_ids=model, **kwargs)
        return instance, returned

    def assert_stops(self, instance, expected):
        self.assertEqual(set(instance.compiler_stops), set(expected))
        self.assertEqual(len(instance.compiler_stops), len(set(expected)))
        self.assertEqual(set(self.calls[-1][2]), set(expected))
        self.assertTrue(self.rows[-1]["available"])
        self.assertEqual(set(self.rows[-1]["xgrammar_stop_token_ids"]), set(expected))
        self.assertIs(self.module.TokenizerInfo, self.factory)

    def test_01_scalar_union_before_compiler(self):
        instance, _ = self.construct(248044)
        self.assert_stops(instance, [248044, 248046])

    def test_02_list_union(self):
        instance, _ = self.construct([248044, 7])
        self.assert_stops(instance, [248044, 248046, 7])

    def test_03_none_model_uses_tokenizer_and_additional(self):
        self.tokenizer.additional_stop_token_ids = [8]
        instance, _ = self.construct(None)
        self.assert_stops(instance, [248046, 8])

    def test_04_none_tokenizer_uses_model(self):
        self.tokenizer.eos_token_id = None
        instance, _ = self.construct([248044])
        self.assert_stops(instance, [248044])

    def test_05_duplicate_union_does_not_mutate_inputs(self):
        model = [248044, 248044, 248046]
        self.tokenizer.additional_stop_token_ids = [248046, 7, 7]
        instance, _ = self.construct(model)
        self.assert_stops(instance, [248044, 248046, 7])
        self.assertEqual(model, [248044, 248044, 248046])
        self.assertEqual(self.tokenizer.additional_stop_token_ids, [248046, 7, 7])

    def test_06_additional_scalar_and_tokenizer_list(self):
        self.tokenizer.eos_token_id = [248046, 9]
        self.tokenizer.additional_stop_token_ids = 8
        instance, _ = self.construct(248044)
        self.assert_stops(instance, [248044, 248046, 9, 8])

    def test_07_set_tuple_inputs(self):
        self.tokenizer.additional_stop_token_ids = (8, 9)
        instance, _ = self.construct({248044})
        self.assert_stops(instance, [248044, 248046, 8, 9])

    def test_08_invalid_ids_fail_closed(self):
        for bad in (True, -1, 248320, 10_000_000, "248044", [False],
                    [248044, -1], {"id": 248044}):
            with self.subTest(bad=bad):
                before = len(self.calls)
                try:
                    self.construct(bad)
                except (ValueError, TypeError, RuntimeError):
                    pass
                else:
                    self.fail("Invalid model EOS admitted to compiler")
                self.assertEqual(len(self.calls), before)
                self.assertIs(self.module.TokenizerInfo, self.factory)
        for vocab in (None, True, -1, 0, 10_000_000):
            with self.subTest(vocab=vocab), self.assertRaises((ValueError, TypeError, RuntimeError)):
                self.construct([248044], vocab_size=vocab)
        self.tokenizer.eos_token_id = None
        for empty in (None, []):
            with self.subTest(empty=empty), self.assertRaises((ValueError, TypeError, RuntimeError)):
                self.construct(empty)
        with self.assertRaises((ValueError, TypeError, RuntimeError)):
            self.construct(list(range(129)))

    def test_09_invalid_additional_ids_fail_closed(self):
        self.tokenizer.additional_stop_token_ids = [248320]
        with self.assertRaises((ValueError, TypeError, RuntimeError)):
            self.construct(248044)
        self.assertFalse(self.calls)

    def test_10_positional_signature_and_non_eos_identity(self):
        original_signature = inspect.signature(self.backend.__init__)
        marker = object()
        instance, returned = self.construct([248044], positional=True, marker=marker)
        self.assert_stops(instance, [248044, 248046])
        self.assertIs(returned, self.result)
        self.assertEqual(inspect.signature(self.backend.__init__), original_signature)
        self.assertIs(self.inputs[-1][0], self.tokenizer)
        self.assertEqual(self.inputs[-1][1], 248320)
        self.assertIs(self.inputs[-1][3], marker)
        self.assertIs(self.calls[-1][3], marker)

    def test_11_keyword_and_defaults(self):
        self.hook.install_module(self.module)
        instance = self.backend.__new__(self.backend)
        returned = self.backend.__init__(instance, tokenizer=self.tokenizer)
        self.assert_stops(instance, [248046])
        self.assertIs(returned, self.result)
        self.assertEqual(self.calls[-1][1], 248320)

    def test_12_original_exception_identity_and_restore(self):
        error = RuntimeError("original-constructor-error")
        module = self.module
        def failing(instance, tokenizer, vocab_size=248320, model_eos_token_ids=None):
            module.TokenizerInfo.from_huggingface(tokenizer, vocab_size=vocab_size,
                                                stop_token_ids=model_eos_token_ids)
            raise error
        self.backend.__init__ = failing
        with self.assertRaises(RuntimeError) as caught:
            self.construct([248044])
        self.assertIs(caught.exception, error)
        self.assertIs(self.module.TokenizerInfo, self.factory)

    def test_13_factory_exception_identity_and_restore(self):
        error = LookupError("original-factory-error")
        with patch.object(self.factory, "from_huggingface", side_effect=error):
            with self.assertRaises(LookupError) as caught:
                self.construct([248044])
        self.assertIs(caught.exception, error)
        self.assertIs(self.module.TokenizerInfo, self.factory)

    def test_14_install_idempotent(self):
        self.hook.install_module(self.module)
        wrapped = self.backend.__init__
        self.hook.install_module(self.module)
        self.assertIs(self.backend.__init__, wrapped)
        instance, _ = self.construct([248044])
        self.assert_stops(instance, [248044, 248046])
        self.assertEqual(len(self.calls), 1)

    def test_15_second_model_no_old_stop_cache(self):
        first, _ = self.construct([248044])
        self.assert_stops(first, [248044, 248046])
        self.tokenizer = types.SimpleNamespace(eos_token_id=12, additional_stop_token_ids=[13])
        second, _ = self.construct([11])
        self.assert_stops(second, [11, 12, 13])
        self.assertEqual(set(first.compiler_stops), {248044, 248046})
        self.assertEqual(len(self.calls), 2)

    def test_16_init_xgrammar_false_not_reported_fixed(self):
        with self.assertRaises((ValueError, RuntimeError)):
            self.construct([248044], init_xgrammar=False)
        self.assertFalse(self.calls)
        self.assertFalse(any(row.get("eos_sync_status") == "validated" for row in self.rows))
        self.assertIs(self.module.TokenizerInfo, self.factory)
        # Unknown constructor contracts must also fail at installation/import.
        def unsupported(instance, tokenizer, *, init_xgrammar=True):
            pass
        self.backend.__init__ = unsupported
        with self.assertRaises((ValueError, RuntimeError)):
            self.hook.install_module(self.module)
        self.assertIs(self.backend.__init__, unsupported)
        delegate = types.SimpleNamespace(exec_module=lambda module: None)
        with self.assertRaises((ValueError, RuntimeError)):
            self.hook.ObserverLoader(delegate).exec_module(self.module)
        # Python ignores ordinary sitecustomize exceptions; SystemExit is required.
        hook_module = types.ModuleType("json_runtime_hook")
        def rejected_install():
            raise RuntimeError("mandatory-install-rejected")
        hook_module.install = rejected_install
        with patch.dict("sys.modules", {"json_runtime_hook": hook_module}):
            with self.assertRaises(SystemExit) as caught:
                runpy.run_path(str(ROOT / "deployments/modal/sitecustomize.py"))
        self.assertNotEqual(caught.exception.code, 0)
        # Missing mandatory hook import must fail the child bootstrap too.
        with patch.dict("sys.modules", {"json_runtime_hook": None}):
            with self.assertRaises(SystemExit) as caught:
                runpy.run_path(str(ROOT / "deployments/modal/sitecustomize.py"))
        self.assertNotEqual(caught.exception.code, 0)

    def test_17_captured_mismatch_fails_closed(self):
        # A factory silently ignoring its stop argument must not be called synced.
        with patch.object(self.factory, "from_huggingface",
                          return_value=types.SimpleNamespace(stop_token_ids=[248044])):
            try:
                self.construct([248044])
            except (ValueError, RuntimeError):
                pass
            else:
                self.assertTrue(self.rows)
                self.assertFalse(self.rows[-1]["available"])
                self.assertIsNot(self.rows[-1].get("eos_sync_applied"), True)

    def test_18_observer_write_error_does_not_block_sync(self):
        with patch.object(self.hook, "write_snapshot", side_effect=OSError("disk-error")):
            instance, returned = self.construct([248044])
        self.assertEqual(set(instance.compiler_stops), {248044, 248046})
        self.assertIs(returned, self.result)
        self.assertIs(self.module.TokenizerInfo, self.factory)

    def test_19_real_evidence_and_local_mask_counterfactual(self):
        artifact = ROOT / "outputs/plan12_json_runtime_20261012/runtime_info_fixed_09.json"
        runtime = json.loads(artifact.read_text(encoding="utf-8"))
        scheduler = runtime["runtime"]["scheduler"]
        self.assertEqual(scheduler["xgrammar_stop_token_ids"], [248044])
        self.assertEqual(scheduler["tokenizer_eos_token_id"], 248046)
        self.assertEqual(runtime["original_job"]["matched_stop"], [248046])
        mask = json.loads((ROOT / "outputs/plan12_json_diagnostic_20261012/observed_runtime_mask.json")
                          .read_text(encoding="utf-8"))
        self.assertEqual(mask["runtime_evidence_sha256"], hashlib.sha256(artifact.read_bytes()).hexdigest())
        observed = mask["checks"]["observed"]
        union = mask["checks"]["union_counterfactual"]
        self.assertFalse(observed["grammar_root_complete_before_stop"])
        self.assertEqual(observed["token_ids"], union["token_ids"])
        old = next(x for x in observed["all_special_tokens"] if x["id"] == 248046)
        new = next(x for x in union["all_special_tokens"] if x["id"] == 248046)
        self.assertTrue(old["allowed_by_next_token_mask"])
        self.assertFalse(new["allowed_by_next_token_mask"])

    def test_20_modal_injected_pythonpath_preserved_before_endpoint_start(self):
        path = ROOT / "deployments/modal/qwen35_9b_l40s.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        # No image-level PYTHONPATH replaces Modal's bootstrap dependency paths.
        for call in ast.walk(tree):
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == "env":
                for arg in call.args:
                    if isinstance(arg, ast.Dict):
                        self.assertNotIn("PYTHONPATH", [k.value for k in arg.keys if isinstance(k, ast.Constant)])
        cls = next(x for x in tree.body if isinstance(x, ast.ClassDef) and x.name == "Server")
        startup = next(x for x in cls.body if isinstance(x, ast.FunctionDef) and x.name == "startup")
        startup.decorator_list = []
        sentinel = RuntimeError("stop-before-warmup")
        class Endpoint:
            def __init__(self, **kwargs):
                pass
            def start(self):
                raise sentinel
        endpoint = types.ModuleType("autoinference_utils.endpoint")
        endpoint.SGLangEndpoint = Endpoint
        hook = types.ModuleType("json_runtime_hook")
        hook.install = lambda: None
        class NoWritePath:
            def __init__(self, *args):
                pass
            def unlink(self, **kwargs):
                pass
        ns = {"Path": NoWritePath, "_ensure_model_downloaded": lambda: "/mock",
              "MODEL_PORT": 8001, "SERVER_ARGS": {}, "STARTUP_TIMEOUT": 60}
        exec(compile(ast.Module(body=[startup], type_ignores=[]), str(path), "exec"), ns)
        import os
        import sys
        for inherited in ("/modal/injected" + os.pathsep + "/deps", ""):
            with self.subTest(inherited=inherited), patch.dict(os.environ, {"PYTHONPATH": inherited}), \
                 patch.object(sys, "path", list(sys.path)), patch.dict(sys.modules, {
                     "autoinference_utils.endpoint": endpoint, "json_runtime_hook": hook,
                     "uvicorn": types.ModuleType("uvicorn")}):
                with self.assertRaises(RuntimeError) as caught:
                    ns["startup"](types.SimpleNamespace())
                self.assertIs(caught.exception, sentinel)
                expected = "/opt/coliee/diagnostics" + (os.pathsep + inherited if inherited else "")
                self.assertEqual(os.environ["PYTHONPATH"], expected)
        install_error = RuntimeError("mandatory-parent-install-rejected")
        with patch.object(hook, "install", side_effect=install_error), \
             patch.object(endpoint, "SGLangEndpoint") as creation, \
             patch.object(sys, "path", list(sys.path)), \
             patch.dict(os.environ, {"PYTHONPATH": "/modal/injected"}), \
             patch.dict(sys.modules, {"autoinference_utils.endpoint": endpoint,
                                     "json_runtime_hook": hook,
                                     "uvicorn": types.ModuleType("uvicorn")}):
            with self.assertRaises(RuntimeError) as caught:
                ns["startup"](types.SimpleNamespace())
        self.assertIs(caught.exception, install_error)
        creation.assert_not_called()


if __name__ == "__main__":
    unittest.main()
