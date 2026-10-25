"""Resume accounting and unchanged host contract for the optional job transport."""
import copy
import json
import tempfile
import unittest
from unittest.mock import patch

from knowledge_base.pipeline_v1.tests import test_au_compact_runner as fixtures
from knowledge_base.pipeline_v1.au_compact import runner
from knowledge_base.pipeline_v1.au_compact.decoding import build_decoding
from knowledge_base.pipeline_v1.au_runtime_config import load_au_runtime_config
from knowledge_base.pipeline_v1.tests.test_compact_decoding import lark, lark_grammar, positive, dumps, ATOMS, TARGETS


class JobRunnerTests(unittest.TestCase):
    @unittest.skipUnless(lark, 'optional lark unavailable')
    def test_light_grammar_accepts_unicode_but_host_rejects_long_claim(self):
        grammar = build_decoding('r-1', 't-1', ATOMS, TARGETS, string_mode='host_validated')['ebnf']
        parser = lark.Lark(lark_grammar(grammar), start='root', parser='earley')
        value = positive()
        for claim in ['Rule.', 'Điều kiện và \\"quotation\\".', 'x' * 301]:
            value['aus'][0]['claim'] = claim
            parser.parse(dumps(value, ensure_ascii=False))
        self.assertTrue(list(runner._COMPACT_VALIDATOR.iter_errors(value)))
        value['aus'][0]['evidence_ref_ids'] = ['not-a-target']
        with self.assertRaises(lark.exceptions.LarkError):
            parser.parse(dumps(value))

    def test_jobs_resume_does_not_reserve_or_count_usage_twice(self):
        helper = fixtures.CompactRunnerTests()
        with tempfile.TemporaryDirectory() as folder:
            source, atoms, manifest = helper.setup_manifest(folder)
            args = helper.kwargs(folder, atoms)
            args['cfg'].update(transport='jobs', jobs_url='https://fake/v1/jobs')
            failure = {'usage': None, 'usage_state': 'unavailable', 'finish_reason': 'host_unresolved',
                       'latency_ms': 1800000, 'failure_diagnostic': {'kind': 'job_wait_timeout', 'retryable': True}}
            def fake_probe(cfg, root, opener):
                out = {'status': 'supported'}
                runner._atomic(root / 'compact_schema_probe.json', out)
                return out
            def fake_warm(cfg, policy, root, opener):
                out = {'status': 'success'}
                runner._atomic(root / 'warmup.json', out)
                return out
            compact = helper.compact_probe()
            compact.update(request_id='r-1', target_id='at-1')
            receipt = {'usage': {'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15},
                       'usage_state': 'provider', 'finish_reason': 'stop'}
            with patch.object(runner, 'compact_preflight', return_value={'status': 'pass'}), \
                 patch.object(runner, 'open_source', return_value=source), \
                 patch.object(runner, 'warmup', side_effect=fake_warm) as warm, \
                 patch.object(runner, '_compact_schema_probe', side_effect=fake_probe) as probe, \
                 patch.object(runner, '_call', side_effect=[runner.CompactRunError(json.dumps(failure)), (compact, receipt)]) as call:
                first = runner.run(manifest, **args)
                second = runner.run(manifest, retry_provider_unavailable=True, **args)
                # Simulate crash after completed cache save, before ledger save.
                ledger_path = args['cache_dir'].parent / 'runtime_ledger.json'
                stale = json.loads(ledger_path.read_text(encoding='utf-8'))
                stale.update(actual_input_tokens=0, actual_output_tokens=0, actual_total_tokens=0,
                             usage_unavailable=0, job_receipts={})
                runner._atomic(ledger_path, stale)
                third = runner.run(manifest, **args)
                fourth = runner.run(manifest, **args)
            self.assertEqual(first['status'], 'incomplete')
            self.assertEqual(second['status'], 'complete')
            self.assertEqual(third['status'], 'complete')
            self.assertEqual(third['runtime_ledger']['actual_total_tokens'], 15)
            self.assertEqual(fourth['runtime_ledger']['actual_total_tokens'], 15)
            self.assertEqual(call.call_count, 2)
            self.assertEqual(warm.call_count, 1)
            self.assertEqual(probe.call_count, 1)
            ledger = second['runtime_ledger']
            self.assertEqual((ledger['requests'], ledger['provider_attempts'], ledger['actual_total_tokens'], ledger['usage_unavailable']), (1, 1, 15, 0))

    def test_timeout_stops_dispatching_other_targets(self):
        helper = fixtures.CompactRunnerTests()
        with tempfile.TemporaryDirectory() as folder:
            source, atoms, manifest = helper.setup_manifest(folder)
            other = copy.deepcopy(manifest['requests'][0]); other['request_id'] = 'r-2'
            manifest['requests'].append(other)
            args = helper.kwargs(folder, atoms)
            failure = {'usage': None, 'usage_state': 'unavailable', 'failure_diagnostic': {'kind': 'transport', 'retryable': True}}
            with patch.object(runner, 'compact_preflight', return_value={'status': 'pass'}), \
                 patch.object(runner, 'open_source', return_value=source), \
                 patch.object(runner, 'warmup', return_value={'status': 'success'}), \
                 patch.object(runner, '_compact_schema_probe', return_value={'status': 'supported'}), \
                 patch.object(runner, '_call', side_effect=runner.CompactRunError(json.dumps(failure))) as call:
                result = runner.run(manifest, **args)
                resumed = runner.run(manifest, **args)
            self.assertEqual(call.call_count, 1)
            self.assertEqual(result['pending_request_ids'], ['r-2'])
            self.assertEqual(result['status'], 'incomplete')
            self.assertEqual(resumed['pending_request_ids'], ['r-2'])

    def test_string_ablation_keeps_schema_and_separates_cache(self):
        bounded = build_decoding('r', 't', ['a'], ['a'])['ebnf']
        light = build_decoding('r', 't', ['a'], ['a'], string_mode='host_validated')['ebnf']
        self.assertIn('json-char{1,300}', bounded)
        self.assertNotIn('json-char{1,300}', light)
        self.assertIn('json-char+', light)
        value = {'request_id': 'r', 'target_id': 't', 'decision': 'positive', 'coverage_status': 'complete',
                 'aus': [{'kind': 'holding', 'other_kind': None, 'claim': 'x' * 301, 'evidence_ref_ids': ['a'],
                          'speaker': 'unknown', 'attribution_role': 'proposition', 'needs_context': []}],
                 'hard_negative_reason': None, 'unresolved_reason': None}
        self.assertTrue(list(runner._COMPACT_VALIDATOR.iter_errors(value)))

    def test_jobs_url_derives_from_shared_au_config(self):
        cfg, _, _ = load_au_runtime_config({'AU_URL': 'https://fake/v1/chat/completions', 'AU_TRANSPORT': 'jobs'}, 'AU_COMPACT_')
        self.assertEqual(cfg['jobs_url'], 'https://fake/v1/jobs')


if __name__ == '__main__':
    unittest.main()
