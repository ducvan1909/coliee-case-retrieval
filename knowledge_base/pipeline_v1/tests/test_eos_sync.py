"""Mandatory EOS sync regression; offline only, no downloads or inference."""
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import types
import unittest
from unittest.mock import patch

if '--native-mask' in sys.argv:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from knowledge_base.pipeline_v1.deployments.modal import json_runtime_hook as hook

ROOT = Path(__file__).resolve().parents[1]


def fixture(actual=None, override=None, error=None, capture=True):
    module = types.SimpleNamespace()
    calls = []
    result = object()
    class Factory:
        @staticmethod
        def from_huggingface(tokenizer, **kw):
            calls.append(kw)
            return types.SimpleNamespace(stop_token_ids=kw['stop_token_ids'] if actual is None else actual)
    class Backend:
        def __init__(self, tokenizer, vocab_size, model_eos_token_ids=None, marker=None):
            if capture:
                self.info = module.TokenizerInfo.from_huggingface(tokenizer,
                    vocab_size=vocab_size, stop_token_ids=model_eos_token_ids)
            self.compiler_built = True
            self.override_stop_tokens = override
            self.marker = marker
            if error:
                raise error
            return result
    module.TokenizerInfo = Factory
    module.XGrammarGrammarBackend = Backend
    return module, calls, result


class EOSSyncTests(unittest.TestCase):
    def setUp(self):
        self.tokenizer = types.SimpleNamespace(eos_token_id=248046,
            additional_stop_token_ids=[248046, 248047], eos_token='<|im_end|>')

    def construct(self, module, **kw):
        cls = module.XGrammarGrammarBackend
        instance = cls.__new__(cls)
        returned = cls.__init__(instance, self.tokenizer, 248320, {248044}, **kw)
        return instance, returned

    def test_union_result_non_eos_identity_idempotence_and_metadata(self):
        module, calls, result = fixture()
        factory = module.TokenizerInfo
        hook.install_module(module)
        wrapped = module.XGrammarGrammarBackend.__init__
        hook.install_module(module)
        self.assertIs(wrapped, module.XGrammarGrammarBackend.__init__)
        marker = object()
        with patch.object(hook, 'write_snapshot') as write:
            instance, returned = self.construct(module, marker=marker)
        self.assertIs(returned, result)
        self.assertIs(instance.marker, marker)
        self.assertIs(module.TokenizerInfo, factory)
        self.assertEqual(calls[0], {'vocab_size': 248320, 'stop_token_ids': [248044, 248046, 248047]})
        row = write.call_args.args[0]
        self.assertEqual(row['input_model_eos_token_ids'], [248044])
        self.assertEqual(row['model_eos_token_ids'], [248044])
        self.assertEqual(row['effective_grammar_eos_token_ids'], row['expected_eos_union'])
        self.assertEqual(row['xgrammar_stop_token_ids'], row['expected_eos_union'])
        self.assertEqual(row['eos_sync_status'], 'validated')
        self.assertEqual(row['eos_sync_mode'], 'mandatory')

    def test_invalid_inputs_fail_before_constructor(self):
        for value in (True, -1, '248044', [1, True], [248320], [1.5], list(range(129))):
            module, calls, _ = fixture()
            hook.install_module(module)
            instance = module.XGrammarGrammarBackend.__new__(module.XGrammarGrammarBackend)
            with self.subTest(value=value), self.assertRaises(hook.EOSSyncError):
                module.XGrammarGrammarBackend.__init__(instance, self.tokenizer, 248320, value)
            self.assertEqual(calls, [])
        with self.assertRaises(hook.EOSSyncError):
            hook.eos_union(None, types.SimpleNamespace(eos_token_id=None), 248320)

    def test_actual_stop_mismatch_fails_before_compiler_and_restores_factory(self):
        for actual in ([248044], [248044, 248046, 248047, 248048], None, True):
            module, _, _ = fixture(actual=actual if actual is not None else [])
            factory = module.TokenizerInfo
            hook.install_module(module)
            instance = module.XGrammarGrammarBackend.__new__(module.XGrammarGrammarBackend)
            with self.assertRaises(hook.EOSSyncError):
                module.XGrammarGrammarBackend.__init__(instance, self.tokenizer, 248320, [248044])
            self.assertFalse(hasattr(instance, 'compiler_built'))
            self.assertIs(module.TokenizerInfo, factory)

    def test_original_exception_identity_and_optional_io(self):
        error = RuntimeError('original')
        module, _, _ = fixture(error=error)
        factory = module.TokenizerInfo
        hook.install_module(module)
        with self.assertRaises(RuntimeError) as caught:
            self.construct(module)
        self.assertIs(caught.exception, error)
        self.assertIs(module.TokenizerInfo, factory)
        module, _, result = fixture()
        hook.install_module(module)
        with patch.object(hook, 'write_snapshot', side_effect=OSError):
            self.assertIs(self.construct(module)[1], result)

    def test_override_and_unsupported_capture_fail_closed(self):
        for override in ([248044], True, 'bad', []):
            module, _, _ = fixture(override=override)
            hook.install_module(module)
            with self.assertRaises(hook.EOSSyncError):
                self.construct(module)
        module, _, _ = fixture(override={248044, 248046, 248047})
        hook.install_module(module)
        with patch.object(hook, 'write_snapshot'):
            self.construct(module)
        module, _, _ = fixture(capture=False)
        hook.install_module(module)
        with self.assertRaises(hook.EOSSyncError):
            self.construct(module)

    def test_unsupported_signature_and_loader_not_silent(self):
        module = types.SimpleNamespace(XGrammarGrammarBackend=type('Bad', (), {}))
        with self.assertRaises(hook.EOSSyncError):
            hook.install_module(module)
        class Loader:
            def exec_module(self, module):
                pass
        with self.assertRaises(hook.EOSSyncError):
            hook.ObserverLoader(Loader()).exec_module(module)

    def test_child_bootstrap_failure_is_fatal_without_exception_text(self):
        bootstrap = ROOT / 'deployments/modal/sitecustomize.py'
        module = types.ModuleType('json_runtime_hook')
        module.install = lambda: (_ for _ in ()).throw(RuntimeError('private credential'))
        with patch.dict(sys.modules, {'json_runtime_hook': module}):
            with self.assertRaises(SystemExit) as caught:
                runpy.run_path(str(bootstrap))
        self.assertEqual(str(caught.exception), 'COLIEE mandatory EOS sync bootstrap failed')
        module.install = lambda: None
        with patch.dict(sys.modules, {'json_runtime_hook': module}):
            runpy.run_path(str(bootstrap))

    def test_actual_xgrammar_021_offline_mask(self):
        # The pre-existing native diagnostic wheel is cp310, while .venv is
        # cp312. Run only this native check in the existing Python310 runtime.
        # No install, no mutation of historic artifacts, no skip on failure.
        python = Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs/Python/Python310/python.exe'
        self.assertTrue(python.is_file(), 'Existing Python310 needed for pinned cp310 XGrammar')
        proc = subprocess.run([str(python), str(Path(__file__).resolve()), '--native-mask'],
            cwd=ROOT.parents[1], capture_output=True, text=True, timeout=180)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn('XGrammar 0.2.1 offline mask PASS', proc.stdout)
        print(proc.stdout.strip())


def native_mask():
    sys.dont_write_bytecode = True
    deps = ROOT / 'outputs/grammar_diagnostic_deps'
    sys.path[:0] = [str(deps / 'pinned'), str(deps / 'runtime')]
    import xgrammar as xgr
    import numpy as np
    from importlib.metadata import version
    from transformers import PreTrainedTokenizerFast
    assert version('xgrammar') == '0.2.1'
    tokenizer = PreTrainedTokenizerFast(tokenizer_file=str(deps / 'tokenizer.json'), eos_token='<|im_end|>')
    tokenizer.additional_stop_token_ids = []
    payload_path = ROOT / 'outputs/plan12_formal_20261012_003243/batch_5/invalid_reason_int.payload.json'
    payload = json.loads(payload_path.read_text(encoding='utf-8'))
    prefix = json.loads(payload_path.with_name('invalid_reason_int.result.json').read_text(encoding='utf-8'))['receipt']['raw_content']
    module = types.SimpleNamespace(TokenizerInfo=xgr.TokenizerInfo)
    class Backend:
        def __init__(self, tokenizer, vocab_size, model_eos_token_ids=None):
            self.info = module.TokenizerInfo.from_huggingface(tokenizer,
                vocab_size=vocab_size, stop_token_ids=model_eos_token_ids)
            self.compiler = xgr.GrammarCompiler(self.info, max_threads=1)
            self.override_stop_tokens = None
    module.XGrammarGrammarBackend = Backend
    hook.install_module(module)
    with patch.object(hook, 'write_snapshot'):
        backend = Backend(tokenizer, 248320, [248044])
    assert backend.info.stop_token_ids == [248044, 248046]
    compiled = backend.compiler.compile_grammar(payload['ebnf'])
    def matcher(text):
        obj = xgr.GrammarMatcher(compiled)
        assert obj.accept_string(text), repr(text)
        return obj
    for text, complete in [(prefix, False), (prefix + 'x"}]}}]}', True)]:
        obj = matcher(text)
        assert obj.is_completed() == complete
        mask = np.full((1, (248320 + 31) // 32), -1, dtype=np.int32)
        obj.fill_next_token_bitmask(mask)
        for token in [248044, 248046]:
            assert bool((int(mask[0, token // 32]) >> (token % 32)) & 1) == complete
            assert matcher(text).accept_token(token) == complete
    complete = prefix + 'x"}]}}]}'
    assert not xgr.GrammarMatcher(compiled).accept_string('prose ' + complete)
    assert not matcher(complete).accept_string('{}')
    assert not xgr.GrammarMatcher(compiled).accept_string(complete.replace('proposal-75d57', 'proposal-INVALID'))
    assert not xgr.GrammarMatcher(compiled).accept_string(complete.replace('"reason":"}x"', '"reason":42'))
    from knowledge_base.pipeline_v1.au_compact.decoding import build_decoding
    compact = build_decoding('request-1', 'target-1', ['a', 'b'], ['b'])
    au_compiled = backend.compiler.compile_grammar(compact['ebnf'])
    valid = {'request_id': 'request-1', 'target_id': 'target-1', 'decision': 'positive',
        'coverage_status': 'complete', 'aus': [{'kind': 'holding', 'other_kind': None,
        'claim': 'Rule.', 'evidence_ref_ids': ['b'], 'speaker': 'current_court',
        'attribution_role': 'proposition', 'needs_context': []}],
        'hard_negative_reason': None, 'unresolved_reason': None}
    text = json.dumps(valid, separators=(',', ':'))
    assert xgr.GrammarMatcher(au_compiled).accept_string(text)
    for invalid in (text.replace('["b"]', '["unknown-source"]'),
                    text.replace('["b"]', '["a"]'),
                    text.replace('target-1', 'unknown-target'),
                    text.replace('"Rule."', '42'), 'prose ' + text, text + '{}'):
        assert not xgr.GrammarMatcher(au_compiled).accept_string(invalid)
    print('XGrammar 0.2.1 offline mask PASS: both EOS blocked before root, allowed after root; rooted JSON, finite proposal/source IDs, target evidence and string types unchanged; inference=0')


if __name__ == '__main__':
    if '--native-mask' in sys.argv:
        native_mask()
    else:
        unittest.main()
