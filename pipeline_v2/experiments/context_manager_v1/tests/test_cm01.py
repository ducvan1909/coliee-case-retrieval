"""Offline contract tests; no inference, labels or remote retrieval."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from pipeline_v2.agent_harness import SourceExcerpt
from pipeline_v2.agent_harness.contracts import HarnessError, encode, fingerprint
from pipeline_v2.experiments.context_manager_v1.core import Config, Session, Snapshot
from pipeline_v2.experiments.context_manager_v1.cli import synthetic


def count(value):
    return len(value) // 6 + 100


class CM01Tests(unittest.TestCase):
    def session(self, directory, size=50, config=None):
        return Session(directory, synthetic(size), count, config or Config())

    def test_traverse_archive_without_loss_and_restart(self):
        with TemporaryDirectory() as d:
            session = self.session(d)
            seen, cursor = [], None
            while True:
                p = session.compile('pool', cursor)
                self.assertEqual(p['status'], 'ready')
                self.assertLessEqual(p['view']['page']['count'], 5)
                seen += p['manifest']['shown_candidate_ids']
                session.receipt(p['request_id'], 'success')
                cursor = p['view']['page']['controls'].get('next')
                if not cursor:
                    break
            self.assertEqual(seen, [f'{n:06}.txt' for n in range(50)])
            other = self.session(d)
            self.assertEqual(other.state()['seen_candidates'], session.state()['seen_candidates'])

    def test_page_token_shrink_uses_actual_displayed_count(self):
        with TemporaryDirectory() as d:
            session = self.session(d, config=Config(page_tokens=450))
            p = session.compile('pool')
            self.assertEqual(p['status'], 'ready')
            size = p['view']['page']['count']
            self.assertGreater(size, 0)
            session.receipt(p['request_id'], 'success')
            q = session.compile('pool', p['view']['page']['controls']['next'])
            self.assertEqual(q['view']['page']['start'], size)

    def test_bound_view_sizes_and_canonical_pool_intact(self):
        with TemporaryDirectory() as d:
            for size in (3, 50, 500, 10000):
                s = self.session(Path(d) / str(size), size)
                p = s.compile('pool')
                self.assertEqual(p['status'], 'ready')
                self.assertLessEqual(p['input_tokens'], 8500)
                self.assertLessEqual(len(p['view']['page']['cards']), 5)
                self.assertEqual(len(s.snapshot.candidates), size)

    def test_needs_current_duplicate_handle_is_idempotent(self):
        with TemporaryDirectory() as d:
            s = self.session(d)
            p = s.compile('needs')
            self.assertEqual(p['status'], 'ready')
            self.assertEqual(len(p['manifest']['shown_need_ids']), 3)
            self.assertEqual(s.state()['seen_needs'], set())
            s.receipt(p['request_id'], 'unknown')
            self.assertEqual(s.state()['seen_needs'], set())
            with self.assertRaises(HarnessError):
                s.compile()

    def test_latest_native_results_and_pair_status(self):
        snap = synthetic(5)
        snap.operations[-1]['hits'] = list(reversed(snap.operations[-1]['hits']))
        snap.assessments = [{'candidate_id': '000002.txt', 'source_need_id': 'need-0'}]
        snap = Snapshot.from_record(snap.record())
        with TemporaryDirectory() as d:
            s = Session(d, snap, count)
            p = s.compile('results')
            self.assertEqual(p['manifest']['shown_candidate_ids'], [x['case_id'] for x in snap.operations[-1]['hits']])
            self.assertTrue(all(c['status_for_current_need'] == 'unassessed' for c in p['view']['page']['cards']))

    def test_tamper_foreign_cursor_and_config_drift(self):
        with TemporaryDirectory() as d:
            s = self.session(d)
            p = s.compile('pool')
            s.receipt(p['request_id'], 'success')
            with self.assertRaises(HarnessError):
                s.compile('pool', 'guessed-cursor')
            with self.assertRaises(HarnessError):
                Session(d, synthetic(51), count)
            with self.assertRaises(HarnessError):
                Session(d, synthetic(50), count, Config(page_size=4))
            path = Path(d) / 'manifests' / (p['request_id'] + '.json')
            path.write_bytes(path.read_bytes() + b' ')
            with self.assertRaises(HarnessError):
                s.load(p['request_id'])

    def test_focus_work_boundary_old_response_and_duplicate_dispatch(self):
        with TemporaryDirectory() as d:
            s = self.session(d)
            p = s.compile('results')
            s.receipt(p['request_id'], 'success')
            ref = next(k for k, v in p['manifest']['handles'].items() if v['kind'] == 'candidate')
            action = {'action': 'read_case_passages', 'args': {'candidate_ref': ref, 'focus': 'legal fairness'}}
            r = s.command(p['request_id'], action)
            self.assertEqual(r['dispatch_intent']['execution'], 'not_executed_CM1')
            with self.assertRaises(HarnessError):
                s.command(p['request_id'], action)
            q = s.compile('needs')
            s.receipt(q['request_id'], 'success')
            different = next(k for k, v in q['manifest']['handles'].items() if v['kind'] == 'need' and v['need_id'] != s.state()['focus']['need_id'])
            self.assertFalse(any(branch['properties']['action']['const'] == 'set_context_focus'
                                 for branch in q['manifest']['schema']['anyOf']))
            from jsonschema import ValidationError
            with self.assertRaises(ValidationError):
                s.command(q['request_id'], {'action': 'set_context_focus', 'args': {'need_ref': different}})
            s.command(q['request_id'], {'action': 'record_missing_evidence', 'args': {'reason': 'Need more surrounding text'}})
            t = s.compile('needs')
            s.receipt(t['request_id'], 'success')
            s.command(t['request_id'], {'action': 'set_context_focus', 'args': {'need_ref': different}})
            old = s.compile('pool'); s.receipt(old['request_id'], 'success')
            new = s.compile('pool'); s.receipt(new['request_id'], 'success')
            with self.assertRaises(HarnessError):
                s.command(old['request_id'], {'action': 'show_context_page', 'args': {'page_ref': old['view']['page']['controls']['needs']}})

    def test_snapshot_mutation_and_collision_rejected(self):
        with TemporaryDirectory() as d:
            s = self.session(d)
            with patch.object(s, '_handle', return_value='collision'):
                with self.assertRaises(HarnessError):
                    s.compile('pool')
            s.snapshot.needs['need-0']['intent'] = 'changed'
            with self.assertRaises(HarnessError):
                s.compile()

    def test_same_candidate_uses_current_need_lead(self):
        snap = Snapshot('A', {}, [{'case_id': 'B', 'need_ids': ['n1', 'n2'], 'open_ref': {'wrong': 'global'}}],
                        {'n1': {'intent': 'one'}, 'n2': {'intent': 'two'}},
                        [{'need_id': 'n1', 'hits': [{'case_id': 'B', 'rank': 1, 'open_ref': {'lead': 1}}]},
                         {'need_id': 'n2', 'hits': [{'case_id': 'B', 'rank': 1, 'open_ref': {'lead': 2}}]}])
        with TemporaryDirectory() as d:
            s = Session(d, snap, count)
            p = s.compile('results'); s.receipt(p['request_id'], 'success')
            ref = next(k for k, v in p['manifest']['handles'].items() if v['kind'] == 'candidate')
            result = s.command(p['request_id'], {'action': 'read_case_passages', 'args': {'candidate_ref': ref, 'focus': 'legal issue'}})
            self.assertEqual(result['dispatch_intent']['canonical_candidate']['open_ref'], {'lead': 2})

    def test_counter_binding_and_writer_lock(self):
        import sqlite3
        with TemporaryDirectory() as d:
            s = self.session(d)
            with self.assertRaises(HarnessError):
                Session(d, synthetic(50), count, counter_binding='other-tokenizer')
            db = sqlite3.connect(Path(d) / 'context_writer.sqlite3')
            try:
                db.execute('BEGIN EXCLUSIVE')
                with self.assertRaises(HarnessError):
                    s.compile()
            finally:
                db.rollback(); db.close()

    def test_unresolved_view_cannot_compile_or_dispatch(self):
        with TemporaryDirectory() as d:
            s = self.session(d)
            p = s.compile('pool')
            with self.assertRaises(HarnessError):
                s.compile('needs')
            ref = p['view']['page']['controls']['needs']
            with self.assertRaises(HarnessError):
                s.command(p['request_id'], {'action': 'show_context_page', 'args': {'page_ref': ref}})

    def test_repeat_is_warning_not_forced_scheduler_or_stop(self):
        with TemporaryDirectory() as d:
            s = self.session(d)
            for number in range(3):
                p = s.compile('pool')
                self.assertEqual(p['status'], 'ready')
                self.assertEqual(bool(p['view']['warnings']), number >= 2)
                s.receipt(p['request_id'], 'success')

    def test_raw_preserve_or_unfit_and_foreign_source(self):
        from hashlib import sha256
        text = 'Épreuve ' * 150
        raw = text.encode()
        row = SourceExcerpt('query.txt', sha256(raw).hexdigest(), (0, len(raw)), text, sha256(raw).hexdigest()).to_record()
        snap = synthetic(3)
        snap.bindings['source_hashes']['query.txt'] = row['source_hash']
        snap = Snapshot.from_record(snap.record())
        evidence = {'excerpts': [row], 'current_payload_source_refs': [row['ref']], 'pending_source_count': 1}
        with TemporaryDirectory() as d:
            s = Session(Path(d)/'okay', snap, count)
            p = s.compile('query', evidence=evidence)
            self.assertEqual(p['view']['excerpts'], [row])
            self.assertEqual(p['manifest']['canonical_evidence'], evidence)
            s = Session(Path(d)/'tiny', snap, count, Config(input_cap=500, soft_target=450, page_tokens=1000))
            p = s.compile('query', evidence=evidence)
            self.assertEqual(p['status'], 'unfit')
            self.assertFalse(any(e['kind'] == 'view_admitted' for e in s.events()))
            s = Session(Path(d)/'foreign', synthetic(3), count)
            with self.assertRaises(HarnessError):
                s.compile('query', evidence=evidence)


if __name__ == '__main__':
    unittest.main()
