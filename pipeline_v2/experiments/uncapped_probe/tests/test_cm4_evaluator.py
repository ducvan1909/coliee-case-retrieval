"""Offline CM4 layout, durable branch bindings and stage evaluation regressions."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from pipeline_v2.agent_harness.contracts import HarnessError, fingerprint
from pipeline_v2.agent_harness.ledger import Ledger, RunState
from pipeline_v2.experiments.uncapped_probe import evaluator as ev
from pipeline_v2.experiments.uncapped_probe.tests import test_policy_evaluator as policy_fixtures
from pipeline_v2.m6_hybrid import EmbeddingBudget, EmbeddingJournal
from pipeline_v2.retrieval_diagnostics import capture


class CM4EvaluatorTests(unittest.TestCase):
    def fixture(self, root, *, source=True, identical=False, failed=False):
        run = root / 'run'
        harness = policy_fixtures.PolicyEvaluatorTests().make_harness(run / 'session')
        harness.config['cm23'] = {'passage_review': True}
        parent = 'a' * 64
        text = 'source literal query'
        anchor = text if identical else 'another literal source'
        need = {'source_need_id': 'need', 'a_anchor': {'text': anchor}, 'source_bound': source}
        args = {'text': text, 'limit': 50, 'channel': 'hybrid', '_m6_need': need}
        starts = {'kind': 'action_started', 'action_id': parent,
                  'action': {'action': 'search_corpus', 'args': args},
                  'executes_tool': True, 'action_fingerprint': 'f'}
        branches = [('source', text)] if source else [('issue', text), ('verbatim', anchor)]
        journal = EmbeddingJournal(run, root, EmbeddingBudget(0, 0))
        records = {}
        pool = [f'B{i:02}' for i in range(50)]
        for name, query in branches:
            if name == 'verbatim' and identical:
                records[name] = {'reused_branch': 'issue'}
                continue
            bid = fingerprint([parent, 'cm4-hybrid-branch', query])
            operation = journal.start_operation(bid, query, 'A', 50)
            fields = dict(operation=operation, action_id=bid, query_case='A', limit=50,
                          query_sha256=sha256(query.encode()).hexdigest(), elapsed_seconds=0)
            if failed:
                journal.append('search_returned', **fields, status='error', diagnostic_status='unavailable')
                break
            result = {'request_id': name, 'query_case': 'A', 'query_sha256': fields['query_sha256'],
                      'channels': {c: [{'case_id': case, 'rank': i+1} for i, case in enumerate(pool)]
                                   for c in ('case_bm25', 'passage_bm25', 'dense_passage')},
                      'hits': [{'case_id': case} for case in pool]}
            saved = capture(run, operation=operation, action_id=bid, query=query,
                            query_case='A', limit=50, result=result)
            journal.append('search_returned', **fields, status='success', m3_request_id=name, **saved)
            records[name] = {'action_id': bid, 'request_id': name, 'cases': pool,
                             'query_sha256': fields['query_sha256']}
        # Ten retained passages contain only five unique B; gold B49 falls at reranking.
        passages = [{'case_id': pool[i//2], 'hit_ref': f'h{i}', 'score': 100-i,
                     'case_rank': i//2+1, 'source_hash': 'd'*64, 'span_bytes': [i, i+1]}
                    for i in range(20)]
        obs = {} if failed else {'cm4_passage_review': True,
            'dual_retrieval': {'branches': records, 'rerank_pool': pool, 'scored_passages': passages},
            'hits': [{**row, 'rank': i+1} for i, row in enumerate(passages[:10])]}
        conclusion = {'decision': 'select', 'identity_packet_id': 'packet', 'identity_relation': 'same_decision'}
        context = {'candidate_conclusions': {parent: {'B00': conclusion}},
                   'passage_session': {'identity_packet': {'packet_id': 'packet', 'case_id': 'B00'}}}
        result_event = dict(kind='action_result', action_id=parent,
            status='error' if failed else 'success',
            result={'observation': obs, 'candidates': list(dict.fromkeys(h['case_id'] for h in obs.get('hits', []))),
                    'source_requests': [], 'source_hashes': {}, 'excerpts': []},
            reload_refs=[], invalidated_assessments=[], reason=None, assessments=[],
            pending_assessments=[], local_elapsed_ms=0, final=None, cm_context=context)
        with harness.ledger.writer() as db:
            state = RunState(harness.ledger.read(db))
            harness._start(db, state)
            for row in (starts, result_event):
                row = deepcopy(row)
                kind = row.pop('kind')
                Ledger.append(db, kind, **row)
            state = RunState(harness.ledger.read(db))
            harness._stop(db, state, 'failure' if failed else 'no_progress', 'fixture')
        labels = root / ev.LABELS
        labels.parent.mkdir(parents=True)
        labels.write_text(json.dumps({'A': ['B00', 'B49']}))
        return run

    def test_root_and_session_freeze_and_score_full_funnel(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            run = self.fixture(root)
            frozen = ev.freeze(run)
            self.assertEqual(frozen, ev.freeze(run / 'session'))
            self.assertIn('session/events.sqlite3', frozen['hashes'])
            report = ev.score(root, run / 'session', frozen)
            funnel = report['cm4_funnel']
            self.assertTrue(report['observed_channel_union']['complete_observed_search_evidence'])
            self.assertEqual(funnel['hybrid_pool']['count'], 50)
            self.assertEqual(funnel['retained_passage_count'], 10)
            self.assertEqual(funnel['retained_unique_b']['count'], 5)
            self.assertEqual(funnel['identity_selected']['cases'], ['B00'])
            self.assertEqual(funnel['gold_losses']['pool_to_scored'], ['B49'])
            self.assertIsNone(funnel['prediction']['f1'])
            self.assertEqual(report['model_calls_this_tool'], 0)
            self.assertFalse((run / 'events.sqlite3').exists())

    def test_dual_legacy_and_identical_reused_branch(self):
        for identical in (False, True):
            with self.subTest(identical=identical), TemporaryDirectory() as directory:
                root = Path(directory)
                run = self.fixture(root, source=False, identical=identical)
                report = ev.score(root, run, ev.freeze(run))
                self.assertEqual(len(report['searches']), 1 if identical else 2)
                self.assertTrue(report['observed_channel_union']['complete_observed_search_evidence'])

    def test_failed_branch_keeps_denominator_and_unknown_recall(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            run = self.fixture(root, source=False, failed=True)
            report = ev.score(root, run, ev.freeze(run))
            self.assertEqual(report['query_denominator'], 1)
            self.assertEqual(report['gold_denominator'], 2)
            self.assertIsNone(report['observed_channel_union']['recall'])

    def test_branch_and_retained_evidence_are_validated(self):
        with TemporaryDirectory() as directory:
            run = self.fixture(Path(directory))
            events = Ledger(run / 'session').read()
            row = next(e for e in events if e['kind'] == 'action_result')
            obs = row['result']['observation']
            original = deepcopy(obs)
            obs['dual_retrieval']['branches']['source']['action_id'] = 'b'*64
            with self.assertRaises(HarnessError): ev._search_links(events)
            obs.clear(); obs.update(deepcopy(original))
            obs['hits'][0]['case_id'] = 'B49'
            with self.assertRaises(HarnessError): ev._search_links(events)
            obs.clear(); obs.update(deepcopy(original))
            obs['hits'].reverse()
            with self.assertRaises(HarnessError): ev._search_links(events)

    def test_freeze_includes_reranker_mutation_and_ambiguous_layout(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            run = self.fixture(root)
            receipt = run / 'reranker' / 'request' / 'admission.json'
            receipt.parent.mkdir(parents=True)
            receipt.write_text('{}')
            frozen = ev.freeze(run)
            receipt.write_text('{"changed":true}')
            with self.assertRaisesRegex(HarnessError, 'changed'): ev.score(root, run, frozen)
            (run / 'events.sqlite3').write_bytes(b'')
            with self.assertRaisesRegex(HarnessError, 'Ambiguous'): ev.freeze(run)
            with self.assertRaisesRegex(HarnessError, 'Ambiguous'): ev.freeze(run / 'session')

    def test_legacy_anchor_does_not_imply_dual_and_prediction_metrics(self):
        action = {'kind': 'action_started', 'action_id': 'a', 'action': {'action': 'search_corpus',
            'args': {'text': 'issue', 'limit': 50, 'channel': 'hybrid', '_m6_need': {'a_anchor': {'text': 'literal'}}}}}
        self.assertEqual(set(ev._search_links([action])[0]), {'a'})
        state = RunState()
        state.final = {'prediction': ['B', 'X']}
        result = ev._funnel([], {}, {'B', 'C'}, state, True)['prediction']
        self.assertEqual((result['precision'], result['recall'], result['f1']), (.5, .5, .5))
        state.final = {'prediction': []}
        self.assertEqual(ev._funnel([], {}, {'B'}, state, True)['prediction']['f1'], 0)


if __name__ == '__main__':
    unittest.main()
