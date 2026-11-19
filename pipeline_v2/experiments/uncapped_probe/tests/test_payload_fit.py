"""Regression tests rebuilding the blocked third request from frozen ledger data."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from jsonschema import ValidationError

from pipeline_v2.agent_harness.contracts import fingerprint
from pipeline_v2.agent_harness.modal_qwen import ModalQwenTransport
from pipeline_v2.experiments.uncapped_probe import policy
from pipeline_v2.experiments.uncapped_probe.replay_payload import replay


ROOT = Path(__file__).resolve().parents[4]
RUN = ROOT / 'cache/m6-uncapped-021095-20261114-200422096'
CAP = 8500
EXPECTED_CANDIDATES = {'012856.txt', '042319.txt', '090399.txt'}


class PayloadFitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not RUN.is_dir():
            raise unittest.SkipTest(f'recorded run fixture unavailable: {RUN}')
        if not (ROOT / 'cache/tokenizers/qwen36_27b_fp8').is_dir():
            raise unittest.SkipTest('pinned Qwen tokenizer fixture unavailable')
        if not (ROOT / 'data/task1_train_files_2026/cases').is_dir():
            raise unittest.SkipTest('local source corpus fixture unavailable')
        cls.temporary = TemporaryDirectory(prefix='payload-fit-replay-')
        cls.output = Path(cls.temporary.name) / 'replay'
        cls.report = replay(ROOT, RUN, cls.output, dry_open_first=True)
        cls.payload = __import__('json').loads((cls.output / 'payload.json').read_bytes())
        cls.pair_payload = __import__('json').loads(
            (cls.output / 'after_scripted_candidate_read_payload.json').read_bytes())
        cls.source_refs_before = cls.report['source_files_sha256']

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_reconstructed_third_request_fits_with_all_three_candidate_choices(self):
        self.assertEqual(self.report['source_prefix_last_seq'], 9)
        self.assertEqual(self.report['source_stop']['stop_detail'], 'payload_token_cap')
        self.assertEqual(self.report['status'], 'ready')
        self.assertLessEqual(self.report['input_tokens'], CAP)
        self.assertEqual(self.report['candidate_read_choices'] and
                         set(self.report['candidate_ids']), EXPECTED_CANDIDATES)
        choices = self.payload['m6']['candidates']
        self.assertEqual({row['case_id'] for row in choices.values()}, EXPECTED_CANDIDATES)
        self.assertEqual(set(self.report['candidate_read_choices']), EXPECTED_CANDIDATES)
        prompt_tools, prompt_schema, _, _ = policy.catalog(self.payload)
        full_tools, full_schema, _, _ = policy.catalog(self.payload, compact_prompt=False)
        self.assertEqual(prompt_schema, full_schema)
        read_tool = next(row for row in prompt_tools if row['name'] == 'read_case_passages')
        self.assertEqual(read_tool['parameters']['properties']['candidate_ref']['choices_from'],
                         'm6.candidates keys')
        self.assertNotIn('enum', read_tool['parameters']['properties']['candidate_ref'])
        schema_branch = next(branch for branch in full_schema['anyOf']
                             if branch['properties']['action']['const'] == 'read_case_passages')
        self.assertEqual(set(schema_branch['properties']['args']['properties']['candidate_ref']['enum']),
                         set(choices))
        self.assertEqual(self.report['controller_inference_requests'], 0)
        self.assertEqual(self.report['embedding_requests'], 0)
        self.assertEqual(self.report['retrieval_requests'], 0)
        self.assertTrue(self.report['historical_run_unchanged'])

    def test_stable_aliases_preserve_bindings_and_reject_removed_candidate_refs(self):
        old = self.payload
        old_candidates = old['m6']['candidates']
        old_alias_by_case = {row['case_id']: alias for alias, row in old_candidates.items()}
        changed = deepcopy(old)
        removed_case = sorted(old_alias_by_case)[0]
        removed_alias = old_alias_by_case[removed_case]
        del changed['m6']['candidates'][removed_alias]

        # Canonical bindings that remain available keep their payload-local refs.
        for case_id, alias in old_alias_by_case.items():
            if case_id == removed_case:
                continue
            self.assertIn(alias, changed['m6']['candidates'])
            self.assertEqual(changed['m6']['candidates'][alias]['case_id'], case_id)

        read = next(row for row in self.payload['available_tools']
                    if row['name'] == 'read_case_passages')
        args = {'candidate_ref': removed_alias, 'focus': 'procedural fairness'}
        with self.assertRaises(ValidationError):
            policy.translate(changed, {'action': 'read_case_passages', 'args': args})

    def test_every_raw_excerpt_ref_round_trips_exact_source_bytes(self):
        import hashlib

        # The next payload must carry both the query-side A passage and the
        # locally opened B passage into the assessment turn.
        refs = self.pair_payload['current_payload_source_refs']
        excerpt_refs = [row['ref'] for row in self.pair_payload['excerpts']]
        self.assertEqual(refs, excerpt_refs)
        cases = ROOT / 'data/task1_train_files_2026/cases'
        excerpt_cases = set()
        for row in self.pair_payload['excerpts']:
            excerpt_cases.add(row['case_id'])
            raw = (cases / row['case_id']).read_bytes()
            start, end = row['span_bytes']
            exact = raw[start:end]
            self.assertEqual(hashlib.sha256(raw).hexdigest(), row['source_hash'])
            self.assertEqual(exact.decode('utf-8'), row['text'])
            self.assertEqual(hashlib.sha256(exact).hexdigest(), row['text_sha256'])
            self.assertEqual(fingerprint([row['case_id'], row['source_hash'], row['span_bytes'],
                                          row['text_sha256']]), row['ref'])
        self.assertIn('021095.txt', excerpt_cases)
        selected_b = self.report['after_scripted_candidate_read']['candidate_id']
        self.assertIn(selected_b, excerpt_cases)
        self.assertTrue(all(len(row['text']) > 1 for row in self.pair_payload['excerpts']))

    def test_read_then_assessment_pair_fits_and_is_truthfully_reported(self):
        after = self.report['after_scripted_candidate_read']
        self.assertEqual(after['status'], 'ready')
        self.assertLessEqual(after['input_tokens'], CAP)
        self.assertEqual(after['controller_inference_requests'], 0)
        self.assertEqual(after['embedding_requests'], 0)
        self.assertTrue(after['assessment_tool_available'])
        self.assertEqual(set(after['raw_cases']), {'021095.txt', after['candidate_id']})
        self.assertGreater(after['pair_count'], 0)
        self.assertEqual(after['pending_source_count'], 1)
        self.assertEqual(after['pair_count'], 1)
        names = {tool['name'] for tool in self.pair_payload['available_tools']}
        self.assertIn('assess_case_link', names)
        self.assertTrue(self.pair_payload['m6']['pair_refs'])
        self.assertEqual(after['pending_source_count'], self.pair_payload['pending_source_count'])

    def test_hierarchical_read_routes_remain_available_after_compaction(self):
        names = {tool['name'] for tool in self.payload['available_tools']}
        self.assertIn('expand_query_map', names)
        self.assertIn('read_query_passages', names)
        self.assertTrue(self.payload['m6']['query_navigation']['current']['region_ref'])
        self.assertTrue(self.payload['m6']['query_maps'])

    def test_count_is_actual_pinned_chat_prompt_count(self):
        transport = ModalQwenTransport(ROOT / 'cache/tokenizers/qwen36_27b_fp8',
                                       instructions=policy.INSTRUCTIONS, wait_seconds=None)
        self.assertEqual(transport.count_tokens(__import__('json').dumps(
            self.payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()),
            self.report['input_tokens'])

    def test_shared_source_needs_hydrate_exactly_and_detect_tampering(self):
        compact = self.payload
        table = compact['m6']['source_needs']
        hydrated = policy.hydrate_body(compact)
        for key, need in table.items():
            self.assertEqual(key, 'n' + fingerprint(need)[:16])
        compact_candidates = compact['m6']['candidates']
        hydrated_candidates = hydrated['m6']['candidates']
        for alias, row in compact_candidates.items():
            expected = [table[key] for key in row['needs']]
            self.assertEqual(hydrated_candidates[alias]['needs'], expected)
        # Hydration must not mutate the provider-visible payload.
        self.assertEqual(compact['m6']['candidates'], compact_candidates)
        self.assertEqual(compact['m6']['candidates'], self.payload['m6']['candidates'])

        corrupt = deepcopy(compact)
        first_key = next(iter(corrupt['m6']['source_needs']))
        corrupt['m6']['source_needs'][first_key]['intent'] += ' tampered'
        with self.assertRaises(policy.ToolSemanticError):
            policy.hydrate_body(corrupt)

        dangling = deepcopy(compact)
        alias = next(iter(dangling['m6']['candidates']))
        dangling['m6']['candidates'][alias]['needs'][0] = 'n' + ('0' * 16)
        with self.assertRaises(policy.ToolSemanticError):
            policy.hydrate_body(dangling)

    def test_shared_needs_dispatch_uses_hydrated_canonical_need(self):
        candidate_ref, compact_candidate = next(iter(self.payload['m6']['candidates'].items()))
        full_candidate = policy.hydrate_body(self.payload)['m6']['candidates'][candidate_ref]
        action = {'action': 'read_case_passages', 'args': {
            'candidate_ref': candidate_ref, 'focus': full_candidate['needs'][0]['intent']}}
        translated = policy.translate(self.payload, action)
        self.assertEqual(translated['args']['m6_candidate'], full_candidate)

    def test_prompt_compaction_does_not_weaken_host_decoder_validation(self):
        prompt_tools, prompt_schema, _, _ = policy.catalog(self.payload)
        full_tools, full_schema, _, _ = policy.catalog(self.payload, compact_prompt=False)
        self.assertEqual(prompt_schema, full_schema)
        for name in ('read_case_passages', 'read_query_passages', 'assess_case_link'):
            prompt = next((row for row in prompt_tools if row['name'] == name), None)
            full = next((row for row in full_tools if row['name'] == name), None)
            if full is None:
                continue
            for key, prompt_field in prompt['parameters']['properties'].items():
                full_field = full['parameters']['properties'][key]
                if 'choices_from' in prompt_field:
                    self.assertNotIn('enum', prompt_field)
                    self.assertIn('enum', full_field)
        first_alias = next(iter(self.payload['m6']['candidates']))
        invalid = {'action': 'read_case_passages', 'args': {
            'candidate_ref': first_alias + '-stale', 'focus': 'procedural fairness'}}
        with self.assertRaises(ValidationError):
            policy.translate(self.payload, invalid)


if __name__ == '__main__':
    unittest.main()
