"""Exact hybrid result reuse from a committed run-local retrieval receipt."""

from tempfile import TemporaryDirectory
from unittest import TestCase

from pipeline_v2.experiments.context_manager_v2.tests.view_helpers import canonical_ref

from pipeline_v2.agent_harness import RunIdentity, ToolResult
from pipeline_v2.agent_harness.contracts import fingerprint
from pipeline_v2.experiments.context_manager_v1.core import Snapshot
from pipeline_v2.experiments.context_manager_v2.cli import choose
from pipeline_v2.experiments.context_manager_v2.engine import Engine
from pipeline_v2.m6 import AdaptiveConfig
from pipeline_v2.m6_hybrid import EmbeddingBudget, EmbeddingJournal
from pipeline_v2.tests.test_m6_adaptive import Tools, source


ISSUE = 'procedural fairness and notice'


class SourceTools(Tools):
    def __init__(self):
        super().__init__()
        first = 'The initial ruling requires formal notice.\n'
        second = 'The later ruling discusses procedural fairness.'
        self.a = source('A', first + second)
        self.first = self.a.slice(0, len(first))
        self.second = self.a.slice(len(first), len(first + second))
        self.query_paragraphs = tuple({'handle': f'p{i:06}', 'span_bytes': piece.span_bytes}
                                      for i, piece in enumerate((self.first, self.second), 1))

    def query_start(self):
        continuation = {'case_id': 'A', 'source_hash': self.a.source_hash, 'cursor': 'next'}
        return ToolResult({'case_id': 'A', 'continuation': continuation}, (self.first,)), self.a

    def expand_source(self, args):
        if args['case_id'] == 'A':
            return ToolResult({'case_id': 'A'}, (self.second,))
        return super().expand_source(args)


class HybridFixture:
    execution_mode = 'real_query'
    expected_snapshot = {'full_manifest_sha256': 'full', 'sparse_manifest_sha256': 'sparse',
                         'embedding_fingerprint': 'embedder', 'collection': 'fixture'}
    fingerprint = fingerprint(expected_snapshot)

    def __init__(self, path, *, complete_receipt=True):
        self.journal = EmbeddingJournal(path, path, EmbeddingBudget(20, 4000))
        self.complete_receipt = complete_receipt
        self.calls = 0

    def remaining(self):
        return {'requests': 20, 'input_tokens': 4000}

    def search(self, query, query_case, limit, action_id):
        self.calls += 1
        operation = self.journal.start_operation(action_id, query, query_case, limit)
        payload = self.journal.events()[-1]
        request_id = f'fixture-{self.calls}'
        if self.complete_receipt:
            self.journal.append('search_returned', **{k: v for k, v in payload.items() if k != 'kind'},
                                status='success', m3_request_id=request_id, elapsed_seconds=123)
        return {**self.expected_snapshot, 'request_id': request_id, 'policy': 'fixture',
                'query_sha256': payload['query_sha256'], 'query_case': query_case,
                'execution_mode': self.execution_mode, 'model_requests': 1, 'timings': {'paid_s': 123},
                'hits': [{'case_id': 'B', 'score': 0.1, 'channels': {}}]}


class SearchReuseTests(TestCase):
    def make(self, path, *, complete_receipt=True):
        tools = SourceTools()
        backend = HybridFixture(path, complete_receipt=complete_receipt)
        identity = RunIdentity('reuse-fixture', 'A', tools.a.source_hash, 'c', 'i', 'p', 'm', 'p', 't', 'z')
        kw = dict(identity=identity, tools=tools, count_tokens=lambda body: len(body) // 6 + 100,
                  config=AdaptiveConfig(channel='hybrid'), hybrid_search=backend,
                  raw_reader=lambda case: {'A': tools.a, 'B': tools.b}[case].text.encode())
        return Engine(path, **kw), backend, kw

    @staticmethod
    def search(engine, ref='p000001', issue=ISSUE, proposition='This proposition should have a source.'):
        engine.step(lambda p: choose(p, 'search_cases_by_issue', a_paragraph_ref=ref, issue=issue,
                                    source_proposition=proposition))

    @staticmethod
    def missing(engine):
        engine.step(lambda p: choose(p, 'record_missing_evidence', reason='Need more source material.'))

    def second_anchor(self, engine):
        engine.step(lambda p: choose(p, 'read_case_passages', focus=ISSUE))
        self.missing(engine)
        engine.step(lambda p: choose(p, 'read_more_context'))

    def test_exact_issue_reuses_committed_hits_for_new_anchor_after_restart(self):
        with TemporaryDirectory() as path:
            engine, backend, kw = self.make(path)
            self.search(engine)
            first = engine.events()[-1]
            self.second_anchor(engine)
            before = backend.journal.events()
            reopened = Engine(path, **kw)
            self.search(reopened, 'p000002')
            events = reopened.events()
            self.assertEqual(backend.calls, 1)
            self.assertEqual(backend.journal.events(), before)
            self.assertFalse(events[-2]['executes_tool'])
            self.assertEqual(events[-1]['reason'], 'reused_exact_hybrid_search')
            observation = events[-1]['result']['observation']
            self.assertEqual(observation['search_reuse']['source_action_id'], first['action_id'])
            self.assertEqual(observation['search_reuse']['source_m3_request_id'], first['result']['observation']['request_id'])
            self.assertEqual(observation['hits'], first['result']['observation']['hits'])
            self.assertTrue({'model_requests', 'timings', 'request_id'}.isdisjoint(observation))
            snapshot = Snapshot.from_events(events, {})
            self.assertEqual(len(snapshot.needs), 2)
            self.assertEqual(len(snapshot.candidates[0]['need_ids']), 2)
            self.assertEqual(reopened.context()['need_id'], observation['m6_source_need']['source_need_id'])
            prepared = reopened.prepare(admit=False)
            preview = prepared['payload']
            self.assertFalse(preview['last_action_feedback']['last_action']['search_executed'])
            self.assertEqual(canonical_ref(prepared, preview['last_action_feedback']['last_successful_search']['source_need_id']),
                             reopened.context()['need_id'])
            self.assertEqual(preview['m6']['cm_page']['candidates'][0]['original_rank'], 1)
            self.missing(reopened)
            self.search(reopened, 'p000002')
            self.assertEqual(reopened.events()[-1]['status'], 'duplicate')
            self.assertEqual(backend.calls, 1)

    def test_changed_proposition_keeps_canonical_same_anchor_as_duplicate(self):
        with TemporaryDirectory() as path:
            engine, backend, _ = self.make(path)
            self.search(engine)
            self.missing(engine)
            changed = 'A changed diagnostic note about the same search.'
            self.search(engine, proposition=changed)
            self.assertEqual(backend.calls, 1)
            self.assertEqual(engine.events()[-1]['status'], 'duplicate')
            self.assertEqual(engine.events()[-3]['raw_model_reply']['args']['source_proposition'], changed)
            self.assertEqual(len(Snapshot.from_events(engine.events(), {}).needs), 1)
            self.assertEqual(engine.prepare(admit=False)['status'], 'ready')

    def test_different_issue_or_missing_source_receipt_calls_backend(self):
        for complete, issue in ((True, 'notice requirements for final orders'), (False, ISSUE)):
            with self.subTest(complete=complete), TemporaryDirectory() as path:
                engine, backend, _ = self.make(path, complete_receipt=complete)
                self.search(engine)
                self.second_anchor(engine)
                self.search(engine, 'p000002', issue=issue)
                self.assertEqual(backend.calls, 2)
                self.assertTrue(engine.events()[-2]['executes_tool'])
                self.assertNotIn('search_reuse', engine.events()[-1]['result']['observation'])
