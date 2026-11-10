"""Independent invariants for schedule coverage and simulated-run isolation."""
import tempfile
import unittest
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

from pipeline_v2.full_corpus import runner
from pipeline_v2.optimization_v2.common import M3Error


class FakeLexical:
    def __init__(self, rows):
        self.rows = rows
        self.db = Mock()
        self.db.execute.return_value = [(batch, pid) for batch, pid, _ in rows]

    def get_many(self, kind, ids):
        assert kind == 'passage'
        docs = {p['passage_id']: p for _, _, p in self.rows}
        return [docs[pid] for pid in ids]

    def close(self): pass


class FullRunnerTests(unittest.TestCase):
    def test_local_plan_cli_does_not_parse_env_or_initialize_modal(self):
        with tempfile.TemporaryDirectory() as temp:
            output = io.StringIO()
            env_path = str(Path(temp) / 'missing.env')
            with patch('pipeline_v2.deploy_modal.parse_env', side_effect=AssertionError('env read')), \
                 patch('pipeline_v2.deploy_modal.build_environment', side_effect=AssertionError('environment built')), \
                 patch.object(runner, 'plan_full', return_value={'status': 'planned_local_no_inference', 'model_requests': 0}):
                with redirect_stdout(output):
                    rc = __import__('pipeline_v2.m3_full', fromlist=['main']).main(
                        ['--env-file', env_path, 'plan', '--output', 'pipeline_v2/artifacts/mock-full-plan'])
            self.assertEqual(rc, 0)
            self.assertEqual(json.loads(output.getvalue())['model_requests'], 0)

    def test_schedule_iterator_covers_partial_last_batch_once(self):
        rows = []
        for ordinal in range(131):
            batch = ordinal // 64
            pid = f'000001.txt:p{ordinal:06d}'
            rows.append((batch, pid, {'passage_id': pid}))
        result = list(runner.batches(FakeLexical(rows)))
        self.assertEqual([len(docs) for _, docs in result], [64, 64, 3])
        flattened = [d['passage_id'] for _, docs in result for d in docs]
        self.assertEqual(flattened, [r[1] for r in rows])
        self.assertEqual(len(flattened), len(set(flattened)))

    def test_execution_identity_binds_simulated_and_real_modes(self):
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp)
            (run / 'manifest.json').write_text('{}', encoding='utf-8')
            m = {'embedding_fingerprint': 'f' * 64}
            simulated = runner.execution_state(run, m, 'simulated')
            real = runner.execution_state(run, m, 'real_modal')
            self.assertNotEqual(simulated, real)
            self.assertEqual(simulated['execution_mode'], 'simulated')
            self.assertEqual(real['execution_mode'], 'real_modal')

    def test_mixed_injected_runtime_is_rejected_before_loading_plan_or_modal(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(runner, 'load_plan') as load_plan, \
                 patch.object(runner, 'OptModalEmbedder') as modal:
                with self.assertRaises(M3Error):
                    runner.run_full(temp, 'pipeline_v2/artifacts/unused', store=Mock(), max_batches=1)
                load_plan.assert_not_called()
                modal.assert_not_called()

    def _run_fixture(self, run_dir):
        manifest = run_dir / 'manifest.json'
        manifest.write_text('{}', encoding='utf-8')
        doc = {
            'passage_id': '000001.txt:p000001', 'case_id': '000001.txt',
            'source_hash': 'a' * 64, 'exact_input_sha256': 'b' * 64,
            'span_bytes': [0, 1], 'parent_handle': 'p000001',
            'policy_hash': 'c' * 64, 'tokenizer_fingerprint': 'd' * 64,
            'full_input_tokens': 2,
        }
        lexical = FakeLexical([(0, doc['passage_id'], doc)])
        m = {
            'embedding_fingerprint': 'f' * 64, 'collection': 'coliee_m3_full_fixture',
            'passages': 1, 'source_hashes': {'000001.txt': 'a' * 64},
            'profile': {'embedding': {'dimensions': 2}, 'qdrant': {'version': '1.20.0'}},
        }
        return doc, lexical, m

    class Store:
        def __init__(self): self.rows = []
        def server_info(self): return {'version': '1.20.0'}
        def ensure(self): return None
        def check_schema(self): return None
        def count(self): return len(self.rows)
        def matches(self, docs, vectors): return len(self.rows) == len(docs)
        def upsert(self, docs, vectors): self.rows.extend(docs)

    def test_cache_commit_before_db_upsert_is_reused_after_interruption(self):
        from contextlib import ExitStack
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp)
            doc, lexical, m = self._run_fixture(run_dir)
            self._run_fixture_doc = doc
            store = self.Store()
            fake_embedder = object()
            calls = []

            def commit_then_crash(embedder, texts, kind, profile, tok, code, ledger, label):
                calls.append(label)
                ledger.begin(label, 'document')
                ids = [doc['passage_id']]
                hashes = [doc['exact_input_sha256']]
                ledger.commit_batch(ids, hashes, np.array([[1.0, 0.0]], dtype=np.float32))
                raise KeyboardInterrupt()

            with ExitStack() as stack:
                stack.enter_context(patch.object(runner, 'load_plan', return_value=(Path.cwd(), run_dir, m, lexical)))
                stack.enter_context(patch.object(runner, 'batches', return_value=iter([(0, [doc])])) )
                stack.enter_context(patch.object(runner, 'PinnedTokenizer', return_value=object()))
                stack.enter_context(patch.object(runner, 'RawReader', return_value=Mock(text=Mock(return_value='x'))))
                stack.enter_context(patch.object(runner, 'request_embedding', side_effect=commit_then_crash))
                stack.enter_context(patch.object(runner, 'guard'))
                with self.assertRaises(KeyboardInterrupt):
                    runner.run_full(Path.cwd(), 'unused', embedder=fake_embedder, store=store)

            self.assertEqual(store.rows, [], 'crash was before Qdrant upsert')
            self.assertEqual(len(calls), 1)

            def cached_vector(*args):
                calls.append('unexpected-inference')
                raise AssertionError('committed vector should resume without model call')

            with ExitStack() as stack:
                stack.enter_context(patch.object(runner, 'load_plan', return_value=(Path.cwd(), run_dir, m, lexical)))
                stack.enter_context(patch.object(runner, 'batches', return_value=iter([(0, [doc])])) )
                stack.enter_context(patch.object(runner, 'PinnedTokenizer', return_value=object()))
                stack.enter_context(patch.object(runner, 'RawReader', return_value=Mock(text=Mock(return_value='x'))))
                stack.enter_context(patch.object(runner, 'request_embedding', side_effect=cached_vector))
                stack.enter_context(patch.object(runner, 'guard'))
                result = runner.run_full(Path.cwd(), 'unused', embedder=fake_embedder, store=store, max_batches=1)
            self.assertEqual(result['new_inference_batches'], 0)
            self.assertEqual(result['cached_batches'], 1)
            self.assertEqual(len(store.rows), 1)
            self.assertEqual(len(calls), 1)

    def test_committed_batch_with_missing_shard_fails_without_inference(self):
        from contextlib import ExitStack
        from pipeline_v2.full_corpus.storage import FullCache
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp)
            doc, lexical, m = self._run_fixture(run_dir)
            self._run_fixture_doc = doc
            cache = FullCache(run_dir, m['embedding_fingerprint'], 2)
            cache.db.execute('CREATE TABLE full_batches(batch INTEGER PRIMARY KEY, committed INTEGER NOT NULL)')
            cache.db.execute('INSERT INTO full_batches VALUES(0,1)')
            cache.db.commit()
            cache.db.close()
            from pipeline_v2.optimization_v2.common import write_json
            write_json(run_dir / 'execution_state.json', runner.execution_state(run_dir, m, 'simulated'))
            store = self.Store()
            fake_embedder = object()
            with ExitStack() as stack:
                stack.enter_context(patch.object(runner, 'load_plan', return_value=(Path.cwd(), run_dir, m, lexical)))
                stack.enter_context(patch.object(runner, 'batches', return_value=iter([(0, [doc])])) )
                stack.enter_context(patch.object(runner, 'PinnedTokenizer', return_value=object()))
                stack.enter_context(patch.object(runner, 'RawReader', return_value=Mock(text=Mock(return_value='x'))))
                stack.enter_context(patch.object(runner, 'guard'))
                inference = stack.enter_context(patch.object(runner, 'request_embedding'))
                with self.assertRaises(M3Error):
                    runner.run_full(Path.cwd(), 'unused', embedder=fake_embedder, store=store)
            inference.assert_not_called()


if __name__ == '__main__':
    unittest.main()
