"""Offline regression tests for CM4's two-branch passage retrieval."""
from hashlib import sha256
import unittest

from pipeline_v2.agent_harness import ToolResult
from pipeline_v2.agent_harness.contracts import HarnessError
from pipeline_v2.experiments.context_manager_v2.dual_search import DualSearch
from pipeline_v2.full_search.hybrid import RRF_K


def digest(raw):
    return sha256(raw).hexdigest()


class DualSearchTests(unittest.TestCase):
    def setUp(self):
        self.query = 'prefix 😀 exact issue span suffix'.encode('utf-8')
        quote = 'exact issue span'.encode('utf-8')
        start = self.query.index(quote)
        self.anchor_span = [start, start + len(quote)]
        self.sources = {
            'A': self.query,
            'B_A': b'B_A lead one. ' + b'x' * 20 + b' B_A lead two.',
            'B_B': b'B_B only lead.',
            'B_C': b'B_C lead.',
        }
        self.actions = []

    def action(self, issue='issue wording'):
        return {'action': 'search_cases_by_issue', 'args': {
            'text': issue,
            '_m6_need': {'a_anchor': {'span_bytes': self.anchor_span},
                         'a_sources': [{'case_id': 'A', 'source_hash': digest(self.query)}]},
        }}

    def raw_reader(self, case):
        return self.sources[case]

    def lead(self, case, start, end, *, score=0.0, rank=1):
        raw = self.sources[case]
        return {'case_id': case, 'span_bytes': [start, end], 'source_hash': digest(raw),
                'rank': rank, 'score': score,
                'open_ref': {'case_id': case, 'source_hash': digest(raw), 'passage_ids': [case]}}

    def branch(self, action, hits):
        self.actions.append(action)
        return ToolResult({'hits': hits})

    def test_runs_issue_and_exact_raw_span_through_independent_hybrid_branches(self):
        captured = []

        def execute(action):
            query = action['args']['text']
            if query == 'issue wording':
                rows = [{'case_id': 'B_A', 'channels': {'passage_bm25': self.lead('B_A', 0, 12)}},
                        {'case_id': 'B_B', 'channels': {'passage_bm25': self.lead('B_B', 0, 14)}}]
            else:
                rows = [{'case_id': 'B_B', 'channels': {'passage_bm25': self.lead('B_B', 0, 14)}},
                        {'case_id': 'B_C', 'channels': {'passage_bm25': self.lead('B_C', 0, 9)}}]
            return self.branch(action, rows)

        def rerank(query, documents):
            captured.append((query, list(documents)))
            return [0.9 - 0.1 * i for i, _ in enumerate(documents)]

        result = DualSearch(rerank)(self.action(), execute, self.raw_reader)

        self.assertEqual([call['args']['text'] for call in self.actions],
                         ['issue wording', 'exact issue span'])
        self.assertEqual(captured[0][0], 'exact issue span')
        self.assertEqual(result.observation['dual_retrieval']['case_union'], ['B_B', 'B_A', 'B_C'])
        self.assertAlmostEqual(result.observation['dual_retrieval']['case_rrf']['B_B'],
                               1 / (RRF_K + 1) + 1 / (RRF_K + 2))
        self.assertEqual(result.candidates, tuple(dict.fromkeys(row['case_id'] for row in result.observation['hits'])))

    def test_source_bound_reranker_receives_the_same_locked_query_as_retrieval(self):
        for with_supports in (False, True):
            with self.subTest(with_supports=with_supports):
                self.actions.clear()
                self.query = 'prefix 😀 exact issue span suffix\n[1998] 1 S.C.R. 27\nExample v. Canada'.encode('utf-8')
                self.sources['A'] = self.query
                supports = []
                if with_supports:
                    for role, text in [('citation', '[1998] 1 S.C.R. 27'),
                                       ('group_member', 'Example v. Canada')]:
                        encoded = text.encode('utf-8')
                        start = self.query.index(encoded)
                        supports.append({'case_id': 'A', 'source_hash': digest(self.query),
                                         'span_bytes': [start, start + len(encoded)],
                                         'role': role, 'text': text})
                expected = '\n'.join(['exact issue span', *(s['text'] for s in supports)])
                action = self.action(expected)
                action['args']['_m6_need'].update(
                    source_bound=True, source_query_text=expected,
                    source_query_sha256=digest(expected.encode('utf-8')), a_supports=supports)
                captured = []

                def execute(branch_action):
                    return self.branch(branch_action, [{'case_id': 'B_A', 'channels': {
                        'one': self.lead('B_A', 0, 12)}}])

                def rerank(query, documents):
                    captured.append((query, list(documents)))
                    return [0.7] * len(documents)

                result = DualSearch(rerank)(action, execute, self.raw_reader)
                self.assertEqual([call['args']['text'] for call in self.actions], [expected])
                self.assertEqual(captured, [(expected, ['B_A lead one'])])
                self.assertEqual(result.candidates, ('B_A',))

    def test_source_bound_tampered_support_is_rejected_before_retrieval_or_rerank(self):
        action = self.action('exact issue span\nsuffix')
        action['args']['_m6_need'].update(
            source_bound=True, source_query_text=action['args']['text'],
            source_query_sha256=digest(action['args']['text'].encode('utf-8')),
            a_supports=[{'case_id': 'A', 'source_hash': digest(self.query),
                         'span_bytes': self.anchor_span, 'role': 'citation', 'text': 'suffix'}])

        def unexpected(*args):
            self.fail('Invalid source must not reach retrieval or reranking')

        with self.assertRaisesRegex(HarnessError, 'support text differs'):
            DualSearch(unexpected)(action, unexpected, self.raw_reader)

    def test_same_source_passage_found_in_both_branches_is_reranked_once_with_both_origins(self):
        calls = []
        start, end = 0, 12

        def execute(action):
            return self.branch(action, [{'case_id': 'B_A', 'channels': {
                'passage_bm25': self.lead('B_A', start, end),
                'dense_passage': self.lead('B_A', start, end, rank=2),
            }}])

        def rerank(query, documents):
            calls.append((query, documents))
            return [0.7] * len(documents)

        result = DualSearch(rerank)(self.action(), execute, self.raw_reader)

        self.assertEqual(len(calls), 1)
        self.assertEqual(len(calls[0][1]), 1)
        self.assertEqual(len(result.observation['dual_retrieval']['scored_passages']), 1)
        origins = result.observation['dual_retrieval']['scored_passages'][0]['origins']
        self.assertEqual({(row['branch'], row['channel']) for row in origins},
                         {('issue', 'passage_bm25'), ('issue', 'dense_passage'),
                          ('verbatim', 'passage_bm25'), ('verbatim', 'dense_passage')})

    def test_rerank_limit_is_passage_level_and_keeps_interleaved_cases(self):
        lead_a1 = self.lead('B_A', 0, 13)
        lead_a2 = self.lead('B_A', 35, len(self.sources['B_A']))
        lead_b = self.lead('B_B', 0, len(self.sources['B_B']))
        source_map = dict(self.sources)
        for i in range(4):
            source_map[f'B_{i}'] = f'passage {i}'.encode()
        self.sources.update(source_map)

        def execute(action):
            # Branch ranks establish stable case ordering; passage rank does not limit
            # how many independently retrieved leads a case contributes.
            rows = [
                {'case_id': 'B_A', 'channels': {'one': lead_a1, 'two': lead_a2}},
                {'case_id': 'B_B', 'channels': {'one': lead_b}},
            ]
            for i in range(4):
                case = f'B_{i}'
                rows.append({'case_id': case, 'channels': {'one': self.lead(case, 0, len(self.sources[case]))}})
            return self.branch(action, rows)

        # Score order intentionally interleaves case IDs. The top-k is passage
        # level: one case can retain more than one result without collapsing it.
        def rerank(_query, documents):
            by_content = {'B_A lead one.': 0.99, 'B_B only lead.': 0.97,
                          'passage 0': 0.95, 'B_A lead two.': 0.93,
                          'passage 1': 0.91, 'passage 2': 0.89, 'passage 3': 0.87}
            return [by_content[next((key for key in by_content if key in document), '')]
                    for document in documents]

        result = DualSearch(rerank, review_limit=4)(self.action(), execute, self.raw_reader)
        hits = result.observation['hits']
        self.assertEqual([row['case_id'] for row in hits], ['B_A', 'B_B', 'B_0', 'B_A'])
        self.assertEqual(len(hits), 4)
        self.assertEqual(len({row['hit_ref'] for row in hits}), 4)
        self.assertTrue(all('rank' in row and 'score' in row for row in hits))

    def test_rejects_changed_query_source_and_bad_reranker_response(self):
        def execute(action):
            return self.branch(action, [{'case_id': 'B_A', 'channels': {
                'one': self.lead('B_A', 0, 12)}}])

        with self.assertRaises(HarnessError):
            DualSearch(lambda _q, docs: [0.5] * len(docs))(
                self.action(), execute, lambda _case: b'changed')

        with self.assertRaises(HarnessError):
            DualSearch(lambda _q, _docs: [float('nan')])(
                self.action(), execute, self.raw_reader)

    def test_identical_issue_and_exact_query_reuses_one_branch(self):
        calls = []

        def execute(action):
            calls.append(action['args']['text'])
            return self.branch(action, [{'case_id': 'B_A', 'channels': {
                'one': self.lead('B_A', 0, 13)}}])

        result = DualSearch(lambda _q, docs: [0.5] * len(docs))(
            self.action('exact issue span'), execute, self.raw_reader)

        self.assertEqual(calls, ['exact issue span'])
        self.assertEqual(result.observation['dual_retrieval']['branches']['verbatim'],
                         {'reused_branch': 'issue'})

    def test_case_without_passage_uses_bounded_local_fallback_or_is_reported_missing(self):
        called = []

        def execute(action):
            return self.branch(action, [{'case_id': 'B_A'}])

        def fallback(case, query):
            called.append((case, query))
            return [self.lead('B_A', 0, 13)]

        selected = DualSearch(lambda _q, docs: [0.6] * len(docs), fallback=fallback)(
            self.action(), execute, self.raw_reader)
        self.assertEqual(called, [('B_A', 'exact issue span')])
        self.assertEqual(selected.observation['hits'][0]['case_id'], 'B_A')
        self.assertEqual(selected.observation['hits'][0]['origins'][0]['branch'], 'case_local')

        missing = DualSearch(lambda _q, docs: [0.6] * len(docs))(
            self.action(), execute, self.raw_reader)
        self.assertEqual(missing.observation['hits'], [])
        self.assertEqual(missing.observation['dual_retrieval']['missing_passage'], ['B_A'])


if __name__ == '__main__':
    unittest.main()
