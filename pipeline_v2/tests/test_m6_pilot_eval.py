"""Use real M6 ledger events with synthetic gold to check pilot stage diagnostics."""

from dataclasses import asdict, replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from pipeline_v2.agent_harness.contracts import HarnessError, fingerprint
from pipeline_v2.agent_harness.ledger import RunState
from pipeline_v2.reviews.m6_discovery_pilot.evaluate import TRAIN_LABELS, collect, score, summarize, write
from pipeline_v2.tests.test_m6_adaptive import Transport, harness


class PilotEvaluationTests(unittest.TestCase):
    def evaluate(self, steps):
        with TemporaryDirectory() as directory:
            agent = harness(directory, Transport(steps))
            agent.run()
            events = agent.events()
        return summarize(RunState(events), events, {'B', 'missing'})

    def test_full_gold_denominator_and_missing_selector(self):
        result = self.evaluate(['search_cases_by_issue', 'read_case_passages', 'reload_evidence',
                                'assess_case_link', 'finish_case_review'])
        self.assertEqual((result['gold_count'], result['gold_retrieved']), (2, 1))
        self.assertEqual(result['gold_stage_counts'], {'retrieval': 1, 'selector_unavailable': 1})
        self.assertIsNone(result['prediction'])
        self.assertTrue(result['pairs']['B']['paired_payload_receipt_seqs'])
        self.assertEqual(result['controller_usage']['requests'], 5)

    def test_retrieved_without_open_and_opened_without_delivery(self):
        self.assertEqual(self.evaluate(['search_cases_by_issue', 'finish_case_review'])['pairs']['B']['first_gap'],
                         'source_open')
        with TemporaryDirectory() as directory:
            agent = harness(directory, Transport(['search_cases_by_issue', 'read_case_passages']))
            agent.budget = replace(agent.budget, max_requests=2)
            agent.config['budget'] = asdict(agent.budget)
            agent.run()
            events = agent.events()
            row = summarize(RunState(events), events, {'B'})
        self.assertEqual(row['pairs']['B']['first_gap'], 'evidence_delivery')
        self.assertTrue(row['pairs']['B']['opens'])
        self.assertFalse(row['pairs']['B']['delivered_refs'])

    def test_reject_holdout_before_run_or_label_access(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            write(root / 'cohort.json', {'discovery_queries': ['A', 'B', 'C'], 'holdout_queries': ['C']})
            write(root / 'manifest.json', {'queries': ['A', 'B', 'C'], 'cohort': 'cohort.json'})
            with self.assertRaisesRegex(HarnessError, 'Unexpected pilot cohort'):
                collect(root, root / 'manifest.json', root / 'missing-runs')

    def test_freeze_then_score_and_reject_changed_receipt(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            runs = root / 'runs'
            queries = ['A.txt', 'B.txt', 'C.txt']
            profile = {'embedding_budget': {'max_requests': 0, 'max_input_tokens': 0}}
            write(root / 'cohort.json', {'discovery_queries': queries, 'holdout_queries': []})
            manifest = root / 'manifest.json'
            write(manifest, {'queries': queries, 'profile': profile, 'cohort': 'cohort.json'})
            for query in queries:
                run = runs / query
                agent = harness(run, Transport(['finish_case_review']))
                agent.identity = replace(agent.identity, query_id=query)
                agent.config['identity'] = asdict(agent.identity)
                from pipeline_v2.agent_harness import ToolResult
                agent.initial = ToolResult({})
                agent.full_query = None
                preview = agent.prepare()
                write(run / 'first_payload.json', preview)
                write(run / 'plan.json', {'settings': {**profile, 'query_id': query},
                                          'preflight_status': 'ready', 'first_payload_sha256': fingerprint(preview),
                                          'binding': {'identity': asdict(agent.identity)}})
                with self.assertRaisesRegex(HarnessError, 'no terminal ledger'):
                    collect(root, manifest, runs)
                agent.run()
            frozen = root / 'freeze.json'
            write(frozen, collect(root, manifest, runs)[0])
            labels = root / TRAIN_LABELS
            labels.parent.mkdir(parents=True)
            write(labels, {query: ['missed.txt'] for query in queries})
            report = score(root, manifest, runs, frozen)
            self.assertEqual(report['gold_total'], 3)
            self.assertEqual(report['candidate_recall'], 0)
            self.assertIsNone(report['final_metrics'])
            write(runs / queries[0] / 'report_new.json', {})
            with self.assertRaisesRegex(HarnessError, 'Frozen pilot inputs changed'):
                score(root, manifest, runs, frozen)


if __name__ == '__main__':
    unittest.main()
