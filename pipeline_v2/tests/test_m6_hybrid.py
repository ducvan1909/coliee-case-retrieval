"""Exercise M6 hybrid routing and embedding admission without provider inference."""

from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from requests import HTTPError, Request, Response

from pipeline_v2.agent_harness.contracts import HarnessError
from pipeline_v2.full_search.hybrid import POLICY, RUNTIME_DIR, fuse_channels
from pipeline_v2.m6 import AdaptiveConfig
from pipeline_v2.m6_hybrid import (MAX_OUTPUT_CAP, OUTPUT_CAP, AccountedSparseHybridSession,
                                   EmbeddingBudget, HybridSearch, M6Qdrant, fuse_m6_channels)
from pipeline_v2.sparse_bm25.index import SparseHybridSession
from pipeline_v2.retrieval.cache import Cache
from pipeline_v2.tests.test_m6_adaptive import Tools, Transport, harness


class HybridTests(unittest.TestCase):
    def test_m6_fusion_expands_to_fifty_without_changing_rrf_order(self):
        channels = {
            name: [{'case_id': f'{i:06d}.txt', 'passage_id': f'{name}-{i}', 'score': 1000-i}
                   for i in range(1, 61)]
            for name in ('dense', 'case', 'passage')
        }
        default_rows = fuse_m6_channels(channels, OUTPUT_CAP)
        rows = fuse_m6_channels(channels, 50)

        self.assertEqual(MAX_OUTPUT_CAP, 50)
        self.assertEqual(len(default_rows), OUTPUT_CAP)
        self.assertEqual(len(rows), 50)
        self.assertEqual([row['case_id'] for row in rows],
                         [f'{i:06d}.txt' for i in range(1, 51)])
        self.assertEqual([row['channels']['dense']['rank'] for row in rows],
                         list(range(1, 51)))

    def test_accounted_search_expands_from_one_twenty_result_backend_call(self):
        channels = {
            name: [{'case_id': f'{i:06d}.txt', 'passage_id': f'{name}-{i}', 'score': 1000-i}
                   for i in range(1, 61)]
            for name in ('dense', 'case', 'passage')
        }
        baseline = {
            'hits': fuse_m6_channels(channels, OUTPUT_CAP),
            'channels': channels,
            'timings': {'total_seconds': 1.0},
        }
        session = object.__new__(AccountedSparseHybridSession)
        calls = []

        def base_search(_session, query, query_case, limit, passage_id):
            calls.append((query, query_case, limit, passage_id))
            return dict(baseline, timings=dict(baseline['timings']))

        with patch.object(SparseHybridSession, '_search', base_search):
            result = session._search('issue', 'query.txt', 50, None)

        self.assertEqual(calls, [('issue', 'query.txt', OUTPUT_CAP, None)])
        self.assertEqual(result['hits'], fuse_m6_channels(channels, 50))
        self.assertGreaterEqual(result['timings']['total_seconds'], 1.0)

    def test_m6_fusion_and_search_reject_fifty_one(self):
        with self.assertRaises(HarnessError):
            fuse_m6_channels({}, 51)
        session = object.__new__(AccountedSparseHybridSession)
        with self.assertRaises(HarnessError):
            session._search('issue', 'query.txt', 51, None)

    def test_hybrid_config_accepts_fifty_and_rejects_fifty_one(self):
        self.assertEqual(AdaptiveConfig(channel='hybrid', search_limit=50).search_limit, 50)
        with self.assertRaises(HarnessError):
            AdaptiveConfig(channel='hybrid', search_limit=51)

    def test_only_exact_query_uses_extended_timeout(self):
        session = Mock()
        session.request.return_value.status_code = 200
        session.request.return_value.json.return_value = {'status': 'ok', 'result': {}}
        db = M6Qdrant('http://127.0.0.1:6333', 'fixture', 'fingerprint', session=session, timeout=135)
        body = {'params': {'exact': True}}
        db._request('POST', db.path + '/points/query?timeout=120', body)
        session.request.assert_called_once_with(
            'POST', 'http://127.0.0.1:6333/collections/fixture/points/query?timeout=86400',
            json=body, timeout=(10, None))
        db._request('GET', db.path)
        session.request.assert_called_with(
            'GET', 'http://127.0.0.1:6333/collections/fixture', json=None, timeout=135)

    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.run_dir = self.root / 'run'
        self.tools = Tools()
        self.calls = []

    def runtime(self, *, budget=EmbeddingBudget(2, 20), interrupt=False, dense_failure=False):
        owner = self

        class Session:
            def search(self, issue, case, limit):
                owner.calls.append(issue)
                self.last_request_id = f'{len(owner.calls):032x}'
                self.journal.reserve(self.last_request_id, 7)
                ledger = Cache(owner.root / RUNTIME_DIR / self.last_request_id, 'fixture')
                try:
                    attempt = ledger.begin('query', 'v2_query')
                    if interrupt:
                        raise KeyboardInterrupt
                    ledger.finish(attempt, 'success', 0.5, 7, receipt={'input_tokens': 7})
                finally:
                    ledger.db.close()
                if dense_failure:
                    response = Response()
                    response.status_code = 500
                    response._content = b'{"status":{"error":"Timeout: Search"}}'
                    response.request = Request('POST', 'http://127.0.0.1:6333/collections/fixture/points/query?timeout=120').prepare()
                    raise HTTPError(response=response)
                lead = {'case_id': 'B', 'passage_id': 'B-1', 'source_hash': owner.tools.b.source_hash,
                        'score': 0.75, 'rank': 1, 'span_bytes': [0, 8]}
                channels = {'case_bm25': [], 'passage_bm25': [], 'dense_passage': [lead]}
                return {'status': 'ok', 'execution_mode': 'real_query', 'policy': POLICY, 'model_requests': 1,
                        'request_id': self.last_request_id, 'query_case': case,
                        'query_sha256': sha256(issue.encode()).hexdigest(), 'channels': channels,
                        'hits': fuse_channels(channels, limit)}

            def close(self):
                pass

        def factory(root, journal):
            session = Session()
            session.journal = journal
            return session

        hybrid = HybridSearch(self.root, self.run_dir, budget, session_factory=factory)
        self.addCleanup(hybrid.close)
        return hybrid

    def agent(self, transport, hybrid):
        return harness(self.run_dir, transport, self.tools, config=AdaptiveConfig(channel='hybrid'),
                       hybrid_search=hybrid)

    def test_hybrid_issue_schema_and_dense_lead_to_assessment(self):
        hybrid = self.runtime(budget=EmbeddingBudget(1, 7))
        transport = Transport(['search_cases_by_issue', 'read_case_passages', 'reload_evidence',
                               'assess_case_link', 'finish_case_review'])
        agent = self.agent(transport, hybrid)
        first = agent.prepare()
        self.assertEqual(self.calls, [])
        self.assertFalse(hybrid.journal.path.exists())
        issue_tool = next(t for t in first['payload']['available_tools'] if t['name'] == 'search_cases_by_issue')
        self.assertEqual(set(issue_tool['parameters']['properties']), {'issue', 'a_paragraph_ref'})
        result = agent.run()
        self.assertEqual(self.calls, ['procedural fairness'])
        self.assertEqual(len(result['active_assessment_ids']), 1)
        self.assertEqual(self.tools.reads[0][1]['passage_ids'], ['B-1'])
        self.assertEqual(result['embedding_usage']['input_tokens'], 7)
        self.assertEqual(result['embedding_usage']['model_requests'], 1)
        self.assertNotIn('search_cases_by_issue', {t['name'] for t in transport.payloads[1]['available_tools']})

    def test_each_new_issue_runs_separate_hybrid_search(self):
        hybrid = self.runtime()
        def reload_a(body):
            ref = next(key for key, refs in body['m6']['reloads'].items() if refs == [self.tools.a.ref])
            return {'action': 'reload_evidence', 'args': {'evidence_ref': ref}}
        def next_issue(body):
            return {'action': 'search_cases_by_issue', 'args': {'issue': 'notice and the right to respond',
                    'a_paragraph_ref': next(iter(body['m6']['a_paragraphs']))}}
        transport = Transport(['search_cases_by_issue', reload_a, next_issue, 'finish_case_review'])
        result = self.agent(transport, hybrid).run()
        self.assertEqual(self.calls, ['procedural fairness', 'notice and the right to respond'])
        self.assertEqual(result['embedding_usage']['model_requests'], 2)

    def test_token_cap_stops_before_provider_attempt(self):
        result = self.agent(Transport(['search_cases_by_issue']), self.runtime(budget=EmbeddingBudget(1, 6))).run()
        self.assertEqual(result['stop_reason'], 'budget')
        self.assertEqual(result['stop_detail'], 'embedding_budget:input_token_cap')
        self.assertEqual(result['embedding_usage']['model_requests'], 0)
        self.assertEqual(result['embedding_usage']['search_budget_stops'], 1)

    def test_dense_failure_keeps_successful_embedding_usage(self):
        result = self.agent(Transport(['search_cases_by_issue']), self.runtime(dense_failure=True)).run()
        self.assertEqual(result['stop_reason'], 'failure')
        self.assertEqual(result['embedding_usage']['search_failures'], 1)
        self.assertEqual(result['embedding_usage']['input_tokens'], 7)
        self.assertEqual(result['embedding_usage']['model_requests'], 1)
        self.assertEqual(result['candidates'], [])
        receipt = result['embedding_usage']['search_receipts'][0]
        self.assertEqual(receipt['http_status'], 500)
        self.assertEqual(receipt['http_endpoint'], 'points/query')
        self.assertTrue(receipt['http_timeout_reported'])

    def test_interrupted_embedding_is_not_resent_on_resume(self):
        hybrid = self.runtime(interrupt=True)
        with self.assertRaises(KeyboardInterrupt):
            self.agent(Transport(['search_cases_by_issue']), hybrid).run()
        resumed = self.agent(Transport([]), self.runtime()).run()
        self.assertEqual(self.calls, ['procedural fairness'])
        self.assertEqual(resumed['stop_detail'], 'interrupted_action')
        self.assertEqual(resumed['embedding_usage']['unknown_receipt_attempts'], 1)
        self.assertIsNone(resumed['embedding_usage']['model_requests'])
        self.assertIsNone(resumed['embedding_usage']['input_tokens'])


if __name__ == '__main__':
    unittest.main()
