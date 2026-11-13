"""Persistent regressions for purpose tools, evidence delivery and recovery."""
import json
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from pipeline_v2.agent_harness import Budget, RunIdentity, SourceExcerpt, ToolResult
from pipeline_v2.agent_harness.contracts import ModelReply, HarnessError, fingerprint
from pipeline_v2.agent_harness.adaptive_policy import catalog, citations, translate
from pipeline_v2.m6 import AdaptiveHarness, AdaptiveConfig
from pipeline_v2.tests.test_m3_source_tools import SourceToolsFixture
from pipeline_v2.tests.test_m4_tools import LexicalFixture
from pipeline_v2.m4 import M3Tools
from dataclasses import replace


def source(case, text):
    raw = text.encode('utf-8'); digest = sha256(raw).hexdigest()
    return SourceExcerpt(case, digest, (0, len(raw)), text, digest)


class Tools:
    fingerprint = 'tools-v1'
    def __init__(self):
        self.a = source('A', 'Évidence: 2012 SCC 12 applies the fairness test.')
        self.query_paragraphs = ({'handle': 'p000001', 'span_bytes': self.a.span_bytes},)
        self.b = source('B', 'The fairness test requires notice and an opportunity to respond.')
        self.reads = []
    def query_start(self):
        return ToolResult({'kind': 'query_map', 'items': []}, (self.a,)), self.a
    def verify_source(self, case, digest):
        return any(row.case_id == case and row.source_hash == digest for row in (self.a, self.b))
    def search_corpus(self, args):
        return ToolResult({'hits': [{'case_id': 'B', 'open_ref': {'case_id': 'B', 'source_hash': self.b.source_hash, 'passage_ids': ['B-1']}}]}, candidates=('B',))
    def open_source(self, args):
        self.reads.append(('open', args))
        return ToolResult({'case_id': 'B'}, (self.b,), ('B',))
    def search_case(self, args):
        self.reads.append(('search', args))
        return self.search_corpus(args)
    def expand_source(self, args):
        return self.open_source(args)
    def open_query(self, args):
        return ToolResult({}, (self.a,))


class Transport:
    def __init__(self, steps): self.steps, self.payloads, self.schemas = list(steps), [], []
    @staticmethod
    def count_tokens(payload): return len(payload) // 10 + 1
    def send_structured(self, payload, request_id, schema):
        body = json.loads(payload); self.payloads.append(body); self.schemas.append(schema)
        step = self.steps.pop(0)
        if callable(step): action = step(body)
        else:
            name = step
            fields = next(row['properties']['args']['properties'] for row in schema['anyOf'] if row['properties']['action']['const'] == name)
            args = {}
            for key, field in fields.items():
                if key not in next(row['properties']['args']['required'] for row in schema['anyOf'] if row['properties']['action']['const'] == name): continue
                if 'enum' in field: args[key] = field['enum'][0]
                else: args[key] = 'procedural fairness' if key in ('issue', 'focus') else 'The current excerpts leave the relation unknown.'
            if name == 'reload_evidence':
                args['evidence_ref'] = next(key for key, refs in body['m6']['reloads'].items() if len(refs) == 2)
            if name == 'finish_case_review': args['reason'] = 'complete_policy'
            if 'case_relation' in args: args['case_relation'] = 'unknown'
            action = {'action': name, 'args': args}
        return ModelReply(action, 1, 1, 1)


def harness(path, transport, tools=None, **kwargs):
    tools = tools or Tools()
    identity = RunIdentity('run', 'A', tools.a.source_hash, 'candidates', 'index', 'profile', 'model', 'prompt', 'tools', 'tokenizer')
    return AdaptiveHarness(path, identity=identity, budget=Budget(12, 12, 100000, 18000, 512),
                           m3_tools=tools, transport=transport, **kwargs)


class AdaptiveTests(unittest.TestCase):
    def test_real_loop_need_lineage_raw_redelivery_and_resume(self):
        with TemporaryDirectory() as path:
            transport = Transport(['search_cases_by_issue', 'read_case_passages', 'reload_evidence', 'assess_case_link', 'finish_case_review'])
            agent = harness(path, transport)
            result = agent.run()
            self.assertEqual(result['stop_reason'], 'complete')
            self.assertEqual(result['selection_status'], 'pending_selection')
            self.assertIsNone(result['prediction'])
            self.assertEqual(result['usage']['requests'], 5)
            self.assertEqual(len(result['active_assessment_ids']), 1)
            need = result['assessments'][0]['source_need_id']
            self.assertEqual(need, transport.payloads[1]['m6']['candidates'][next(iter(transport.payloads[1]['m6']['candidates']))]['needs'][0]['source_need_id'])
            assessment_payload = transport.payloads[3]
            self.assertEqual({row['case_id'] for row in assessment_payload['excerpts']}, {'A', 'B'})
            for event in agent.events():
                if event['kind'] == 'request_admitted':
                    body = json.loads(event['payload'])
                    self.assertEqual(body['m6']['schema_fingerprint'], fingerprint(catalog(body)[1]))
                    self.assertTrue(body['available_tools'])
            self.assertEqual(harness(path, Transport([])).run()['usage']['requests'], 5)

    def test_bad_candidate_ref_rejected_and_usage_kept(self):
        with TemporaryDirectory() as path:
            bad = lambda body: {'action': 'read_case_passages', 'args': {'candidate_ref': 'fabricated', 'focus': 'notice'}}
            agent = harness(path, Transport(['search_cases_by_issue', bad]))
            result = agent.run()
            self.assertEqual(result['stop_reason'], 'failure')
            self.assertEqual(result['usage']['requests'], 2)
            self.assertEqual(result['usage']['reported_output_tokens'], 2)
            self.assertFalse(result['fallback'])
            self.assertTrue(result['fallback_unavailable'])

    def test_citation_raw_utf8_span_and_wrong_ref_rejected(self):
        tools = Tools(); row = tools.a.to_record()
        body = {'query_id': 'A', 'excerpts': [row], 'current_payload_source_refs': [row['ref']],
                'm6': {'candidates': {}, 'query_targets': {}, 'expansions': {}, 'reloads': {}, 'review_candidates': {}, 'review_count': 0, 'max_reviews': 1}}
        refs = citations(body); self.assertEqual(len(refs), 1)
        citation = next(iter(refs.values())); start, end = citation['span_bytes']
        self.assertEqual(row['text'].encode('utf-8')[start:end].decode('utf-8'), '2012 SCC 12')
        with self.assertRaises(Exception):
            translate(body, {'action': 'find_citation_matches', 'args': {'citation_ref': row['ref']}})
        body['current_payload_source_refs'] = []
        self.assertEqual(citations(body), {})

    def test_second_focus_searches_within_candidate(self):
        with TemporaryDirectory() as path:
            tools = Tools()
            transport = Transport(['search_cases_by_issue', 'read_case_passages', 'read_case_passages', 'finish_case_review'])
            result = harness(path, transport, tools).run()
            self.assertEqual(result['stop_reason'], 'complete')
            self.assertEqual([kind for kind, _ in tools.reads], ['open', 'search', 'open'])

    def test_no_progress_and_baseline_binding(self):
        with TemporaryDirectory() as path:
            steps = ['search_cases_by_issue'] + ['read_case_passages'] * 7
            result = harness(path, Transport(steps), config=AdaptiveConfig(no_progress_actions=2)).run()
            self.assertEqual(result['stop_reason'], 'no_progress')
            self.assertIsNone(result['prediction'])
        with TemporaryDirectory() as path:
            with self.assertRaises(HarnessError): harness(path, Transport([]), baseline=[])

    def test_selector_cannot_select_without_current_assessment(self):
        with TemporaryDirectory() as path:
            result = harness(path, Transport(['finish_case_review']), selector=lambda state: {'prediction': ['B'], 'assessment_ids': []}, selector_fingerprint='frozen').run()
            self.assertEqual(result['stop_reason'], 'failure')


    def test_counterevidence_cannot_borrow_third_candidate(self):
        with TemporaryDirectory() as path:
            transport = Transport(['search_cases_by_issue', 'read_case_passages', 'reload_evidence', 'assess_case_link', 'finish_case_review'])
            harness(path, transport).run()
            body = transport.payloads[3]
            third = source('C', 'A different case about fairness.').to_record()
            body['excerpts'].append(third)
            body['current_payload_source_refs'].append(third['ref'])
            pair = next(iter(catalog(body)[3]))
            args = {'pair_ref': pair, 'case_relation': 'unknown', 'passage_location': 'bounded',
                    'reason': 'Insufficient evidence', 'counterevidence': [third['ref']]}
            with self.assertRaisesRegex(HarnessError, 'another_pair'):
                translate(body, {'action': 'assess_case_link', 'args': args})
            b = next(row for row in body['excerpts'] if row['case_id'] == 'B')
            args['counterevidence'] = [b['ref']]
            internal = translate(body, {'action': 'assess_case_link', 'args': args})
            materialized = json.loads(internal['args']['assessments'][0]['counterevidence'])
            self.assertEqual(materialized[0]['source_hash'], b['source_hash'])
            self.assertEqual(materialized[0]['span_bytes'], b['span_bytes'])

    def test_prepare_never_admits_and_binds_first_payload(self):
        with TemporaryDirectory() as path:
            transport = Transport([])
            agent = harness(path, transport)
            preview = agent.prepare()
            self.assertEqual(preview['status'], 'ready')
            self.assertEqual(agent.inspect()['usage']['requests'], 0)
            self.assertEqual(transport.payloads, [])
            self.assertTrue(preview['payload']['m6']['citation_refs'])

    def test_interrupted_admission_resume_does_not_send_again(self):
        class Crash(Transport):
            def send_structured(self, *args): raise SystemExit('interrupted')
        with TemporaryDirectory() as path:
            agent = harness(path, Crash([]))
            with self.assertRaises(SystemExit): agent.run()
            resumed = harness(path, Transport([])).run()
            self.assertEqual(resumed['usage']['requests'], 1)
            self.assertEqual(resumed['usage']['unknown_receipts'], 1)
            self.assertEqual(resumed['stop_reason'], 'failure')

    def test_last_open_is_unread_at_request_cap(self):
        with TemporaryDirectory() as path:
            agent = harness(path, Transport(['search_cases_by_issue', 'read_case_passages']))
            agent.budget = replace(agent.budget, max_requests=2)
            from dataclasses import asdict
            agent.config['budget'] = asdict(agent.budget)
            result = agent.run()
            self.assertEqual(result['stop_reason'], 'budget')
            self.assertTrue(result['pending_source_refs'])
            self.assertEqual(result['active_assessment_ids'], [])

    def test_review_audit_is_bounded_and_finding_persisted(self):
        with TemporaryDirectory() as path:
            transport = Transport(['search_cases_by_issue', 'read_case_passages', 'reload_evidence', 'assess_case_link',
                                   'reload_evidence', 'review_conflicting_link', 'finish_case_review'])
            result = harness(path, transport).run()
            self.assertEqual(result['stop_reason'], 'complete')
            reviews = [row for row in result['assessments'] if row['reason'].startswith('Targeted review: ')]
            self.assertEqual(len(reviews), 1)
            self.assertIn('untriggered_audit', transport.payloads[5]['m6']['review_candidates'].values())
            self.assertNotIn('review_conflicting_link', [row['name'] for row in transport.payloads[6]['available_tools']])

    def test_pending_review_still_consumes_review_cap(self):
        def pending_review(body):
            pair = next(iter(catalog(body)[3]))
            return {'action': 'review_conflicting_link', 'args': {'pair_ref': pair, 'case_relation': 'unknown',
                    'passage_location': 'bounded', 'reason': 'Need context', 'finding': 'Attribution remains unresolved',
                    'missing_evidence': ['Read the original quoted speaker introduction.']}}
        with TemporaryDirectory() as path:
            transport = Transport(['search_cases_by_issue', 'read_case_passages', 'reload_evidence', 'assess_case_link',
                                   'reload_evidence', pending_review, 'reload_evidence', 'finish_case_review'])
            result = harness(path, transport).run()
            self.assertEqual(result['stop_reason'], 'complete')
            self.assertEqual(transport.payloads[7]['m6']['review_count'], 1)
            self.assertNotIn('review_conflicting_link', [tool['name'] for tool in transport.payloads[7]['available_tools']])
            self.assertEqual(len(result['pending_assessments']), 1)

    def test_partial_current_a_keeps_original_need(self):
        from pipeline_v2.agent_harness.evidence import slice_record
        with TemporaryDirectory() as path:
            agent = harness(path, Transport(['search_cases_by_issue', 'read_case_passages', 'reload_evidence', 'assess_case_link', 'finish_case_review']))
            agent.run()
            body = agent.transport.underlying.payloads[3]
            original_pairs = catalog(body)[3]
            a = next(row for row in body['excerpts'] if row['case_id'] == 'A')
            clipped = slice_record(a, a['span_bytes'][0], a['span_bytes'][1] - 3)
            body['excerpts'] = [clipped if row['case_id'] == 'A' else row for row in body['excerpts']]
            body['current_payload_source_refs'] = [row['ref'] for row in body['excerpts']]
            pairs = catalog(body)[3]
            self.assertEqual(next(iter(pairs.values()))['source_need_id'], next(iter(original_pairs.values()))['source_need_id'])
            self.assertEqual(next(iter(pairs.values()))['context_coverage'], 'partial')


class RealM3AdaptiveTests(SourceToolsFixture):
    def test_citation_search_reaches_later_bounded_scan_page(self):
        text = 'The decision in 2012 SCC 12 states the fairness test.'
        for case in ('000001.txt', '000002.txt'):
            self.add_case(case, text, [{'span_bytes': [0, len(text.encode('utf-8'))]}])
        reader = self.make_session(); self.addCleanup(reader.close)
        tools = M3Tools(reader, LexicalFixture(), '000001.txt', byte_budget=4096, map_limit=1)
        initial, full = tools.query_start()
        original_identity_search = reader.search_identity
        reader.search_identity = lambda **args: original_identity_search(**{**args, 'case_scan_limit': 1})
        identity = RunIdentity('pages', '000001.txt', full.source_hash, 'c', 'i', 'p', 'm', 'prompt', 't', 'tok')
        transport = Transport(['find_citation_matches', 'continue_citation_search', 'read_case_passages',
                               'reload_evidence', 'assess_case_link', 'finish_case_review'])
        agent = AdaptiveHarness(self.root / 'pages', identity=identity, budget=Budget(8,8,100000,20000,512),
                                m3_tools=tools, transport=transport, initial_observation=initial, query_excerpt=full)
        result = agent.run()
        self.assertEqual(result['stop_reason'], 'complete')
        self.assertEqual(result['candidates'], ['000002.txt'])
        self.assertEqual(len(result['active_assessment_ids']), 1)
        self.assertTrue(transport.payloads[1]['m6']['citation_search_pages'])
        self.assertEqual(result['assessments'][0]['candidate_id'], '000002.txt')

    def test_identity_and_expansion_use_real_source_contract(self):
        text = 'The test in 2012 SCC 12 applies.\nNext paragraph.'
        boundary = len('The test in 2012 SCC 12 applies.'.encode('utf-8'))
        for case in ('000001.txt', '000002.txt'):
            self.add_case(case, text, [{'span_bytes': [0, boundary]}, {'span_bytes': [boundary + 1, len(text.encode('utf-8'))]}])
        reader = self.make_session(); self.addCleanup(reader.close)
        tools = M3Tools(reader, LexicalFixture(), '000001.txt', byte_budget=4096, map_limit=1)
        initial, full = tools.query_start()
        identity = RunIdentity('real', '000001.txt', full.source_hash, 'c', 'i', 'p', 'm', 'prompt', 't', 'tok')
        agent = AdaptiveHarness(self.root / 'run', identity=identity, budget=Budget(8,8,100000,20000,512),
                                m3_tools=tools, transport=Transport([]), initial_observation=initial, query_excerpt=full)
        prepared = agent.prepare()
        self.assertEqual(prepared['status'], 'ready')
        for row in prepared['payload']['m6']['expansions'].values():
            self.assertIn(row['binding'].get('target_handle'), ('u0000', 'u0001'))
        # Multiple query targets survive encode(sort_keys) without enum fingerprint drift.
        self.assertGreaterEqual(len(prepared['payload']['m6']['query_targets']), 2)
        self.assertEqual(prepared['payload']['m6']['schema_fingerprint'], fingerprint(catalog(prepared['payload'])[1]))
        result = agent._identity_search({'text': '2012 SCC 12', 'limit': 5,
                                         '_m6_need': {'source_need_id': 'citation-need', 'a_refs': [], 'intent': '2012 SCC 12'}})
        self.assertEqual(result.observation['identity_status'], 'observed_not_identity_verified')
        self.assertTrue(result.observation['coverage'])
        self.assertEqual(result.candidates, ('000002.txt',))
        self.assertEqual(result.observation['hits'][0]['method_version'], 'literal_unicode_casefold_observation_v1')


if __name__ == '__main__': unittest.main()
