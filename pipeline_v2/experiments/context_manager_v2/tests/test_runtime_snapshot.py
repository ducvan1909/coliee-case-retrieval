"""Durability, prefix and ownership regressions for the CM4 RAM projection."""
from copy import deepcopy
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from pipeline_v2.agent_harness.contracts import HarnessError, fingerprint
from pipeline_v2.agent_harness.ledger import Ledger, RunState
from pipeline_v2.experiments.context_manager_v1.core import Snapshot
from pipeline_v2.experiments.context_manager_v2 import query_review
from pipeline_v2.experiments.context_manager_v2.runtime_snapshot import RuntimeSnapshot
from pipeline_v2.experiments.context_manager_v2.tests import test_engine as fixtures


class RuntimeSnapshotTests(unittest.TestCase):
    def test_prefix_hash_state_indexes_and_no_full_read_in_hot_getters(self):
        with TemporaryDirectory() as directory:
            engine, _ = fixtures.EngineTests().make(directory)
            with patch.object(engine.harness.ledger, 'read', side_effect=AssertionError('full history read')):
                fixtures.EngineTests().search_read(engine)
                for _ in range(3):
                    engine.context(); engine.state().usage(); engine.prepare(admit=False)
            events = Ledger(directory).read()
            self.assertEqual(engine._runtime.state.__dict__, RunState(events).__dict__)
            self.assertEqual(engine._runtime.prefix_sha256, fingerprint(events))
            self.assertEqual(query_review.queries(engine._events(), engine.context()),
                             query_review.queries(events, engine.context()))
            old = Snapshot.from_events(events, {})
            new = engine._snapshot()
            for name in ('needs', 'operations', 'candidates', 'bindings'):
                self.assertEqual(getattr(old, name), getattr(new, name))
            self.assertEqual(engine._runtime.stats['full_reads'], 1)
            self.assertEqual(engine._runtime.stats['rows_decoded'], 0)
            self.assertEqual(engine._runtime.stats['events_applied'], len(events))

    def test_external_append_and_second_engine_sync_only_suffix(self):
        with TemporaryDirectory() as directory:
            first, _ = fixtures.EngineTests().make(directory)
            second, _ = fixtures.EngineTests().make(directory)
            before = first._runtime.stats.copy()
            second.stop('operator_stop_file')
            self.assertEqual(first.state().final['stop_reason'], 'no_progress')
            self.assertEqual(first._runtime.stats['full_reads'], before['full_reads'])
            self.assertEqual(first._runtime.stats['rows_decoded'], before['rows_decoded'] + 1)
            self.assertEqual(first._runtime.prefix_sha256, fingerprint(Ledger(directory).read()))

    def test_internal_registry_and_reads_do_not_call_public_history_copy(self):
        with TemporaryDirectory() as directory:
            engine, _ = fixtures.EngineTests().make(directory)
            with patch.object(engine.harness, 'events', side_effect=AssertionError('public history copy')), \
                 patch.object(engine, 'events', side_effect=AssertionError('public history copy')):
                fixtures.EngineTests().search_read(engine)
                engine.prepare(admit=False)
            self.assertEqual(engine._runtime.prefix_sha256, fingerprint(engine.events()))

    def test_public_nested_values_and_mutators_do_not_change_committed_state(self):
        with TemporaryDirectory() as directory:
            engine, _ = fixtures.EngineTests().make(directory)
            original = engine._runtime.prefix_sha256
            state = engine.state()
            state.config['identity']['query_id'] = 'changed'
            state.catalog.clear()
            snapshot = state.snapshot(); snapshot['config'].clear()
            engine.context()['back'].append('changed')
            engine.events()[0]['config'].clear()
            engine.harness.events()[0]['config']['identity']['query_id'] = 'changed'
            engine.harness.inspect()['config'].clear()
            engine.inspect()['state']['config'].clear()
            for name in ('apply', 'queue', 'invalidate', 'add_result'):
                with self.assertRaises(HarnessError):
                    getattr(state, name)
            self.assertEqual(engine.state().config['identity']['query_id'], 'A')
            self.assertTrue(engine.state().catalog)
            self.assertEqual(engine._runtime.prefix_sha256, original)
            self.assertEqual(engine._runtime.prefix_sha256, fingerprint(engine.events()))
            engine.stop('operator_stop_file')
            with self.assertRaises(HarnessError):
                state.usage()

    def test_execute_and_prepare_results_do_not_expose_index_or_state_aliases(self):
        with TemporaryDirectory() as directory:
            engine, _ = fixtures.EngineTests().make(directory)
            prepared = engine.prepare()
            engine.reply(prepared['request_id'], fixtures.EngineTests().action(prepared, 'search_cases_by_issue'))
            result = engine.execute_pending()
            result['config'].clear()
            self.assertTrue(engine.state().config)
            before = engine.events()
            preview = engine.prepare(admit=False)
            for need in preview['manifest']['dispatch_m6'].get('source_needs', {}).values():
                need.clear()
            preview['manifest']['context']['back'].append('changed')
            self.assertEqual(engine.events(), before)
            self.assertNotIn('changed', engine.context()['back'])

    def test_committed_index_failure_rebuilds_without_duplicate_event(self):
        with TemporaryDirectory() as directory:
            engine, _ = fixtures.EngineTests().make(directory)
            before = len(engine.events())
            with patch.object(engine._runtime, '_index', side_effect=RuntimeError('after commit')):
                with self.assertRaises(RuntimeError):
                    engine.stop('operator_stop_file')
            self.assertFalse(engine._runtime.valid)
            durable = Ledger(directory).read()
            self.assertEqual(len(durable), before + 1)
            self.assertEqual(engine.state().final, durable[-1]['final'])
            self.assertEqual(len(engine.events()), before + 1)
            self.assertEqual(engine._runtime.prefix_sha256, fingerprint(durable))

    def test_commit_failure_does_not_publish_working_state(self):
        with TemporaryDirectory() as directory:
            engine, _ = fixtures.EngineTests().make(directory)
            before = engine._runtime.prefix_sha256
            with patch.object(Ledger, 'append', side_effect=RuntimeError('before INSERT')):
                with self.assertRaises(RuntimeError):
                    engine.stop('operator_stop_file')
            self.assertIsNone(engine.state().final)
            self.assertEqual(engine._runtime.prefix_sha256, before)

    def test_delta_query_uses_primary_key_and_preserves_full_audit_api(self):
        with TemporaryDirectory() as directory:
            engine, _ = fixtures.EngineTests().make(directory)
            engine.stop('operator_stop_file')
            ledger = Ledger(directory)
            with ledger.writer() as db:
                rows = ledger.read(db)
                self.assertEqual(ledger.read_after(rows[0]['seq'], db), rows[1:])
                detail = str(db.execute('EXPLAIN QUERY PLAN SELECT seq, record FROM events '
                    'WHERE seq > ? AND seq <= ? ORDER BY seq', (1, 2)).fetchall()).upper()
                self.assertIn('INTEGER PRIMARY KEY', detail)

    def test_invalidated_runtime_rejects_a_different_frozen_run(self):
        with TemporaryDirectory() as directory:
            engine, _ = fixtures.EngineTests().make(directory)
            changed = Ledger(directory).read()
            changed[0]['config']['identity']['query_id'] = 'another-query'
            engine._runtime.invalidate()
            with patch.object(engine.harness.ledger, 'read', return_value=changed):
                with self.assertRaisesRegex(HarnessError, 'configuration changed'):
                    engine.state()
            self.assertFalse(engine._runtime.valid)

    def test_navigation_registry_matches_legacy_without_iterating_history(self):
        from pipeline_v2.experiments.context_manager_v2.tests import test_map_first as maps
        from pipeline_v2.experiments.context_manager_v2.cli import choose
        fixture = maps.MapFirstTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        with TemporaryDirectory() as directory:
            engine, tools = fixture.make_engine(directory, leaf_bytes=1024)
            for step in range(3):
                payload = {'excerpts': [], 'current_payload_source_refs': []}
                expected = tools.registry(engine.events(), engine._state(), payload)
                class NoHistoryWalk:
                    runtime = engine._runtime
                    def __iter__(self):
                        raise AssertionError('Incremental navigation must not scan events')
                self.assertEqual(tools.registry(NoHistoryWalk(), engine._state(), payload), expected)
                prepared = engine.prepare(admit=False)
                names = {tool['name'] for tool in prepared['payload']['available_tools']}
                if step < 2 and 'read_query_passages' in names:
                    engine.step(lambda p: choose(p, 'read_query_passages'))
            engine._runtime.navigation_maps['wrong-tree'] = {'current': 'invalid', 'opened': set()}
            with self.assertRaisesRegex(HarnessError, 'different tree'):
                tools.registry(NoHistoryWalk(), engine._state(), payload)


if __name__ == '__main__':
    unittest.main()
