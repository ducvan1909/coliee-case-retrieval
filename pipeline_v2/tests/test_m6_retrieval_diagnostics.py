"""RT1 raw-return observability fixtures; no provider or corpus requests."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from pipeline_v2.agent_harness.contracts import HarnessError, fingerprint
from pipeline_v2.full_search.hybrid import POLICY, fuse_channels
from pipeline_v2.m6_hybrid import EmbeddingBudget, HybridSearch, implementation_binding, observation
from pipeline_v2.retrieval_diagnostics import capture, inspect_run, verify_capture
from pipeline_v2.tests import test_m6_hybrid as hybrid_fixtures


class RetrievalDiagnosticTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.run_dir = self.root / 'run'
        self.query = 'norme de contrôle judiciaire'
        self.case = '000001.txt'
        self.action = 'a' * 64
        self.operation = fingerprint([self.action, self.query, self.case, 1])
        rows = [{'case_id': f'{index:06}.txt', 'rank': index - 1, 'score': 1.0 / index,
                 'passage_id': f'{index}:passage', 'source_hash': 'e' * 64, 'span_bytes': [0, 5]}
                for index in range(2, 6)]
        channels = {name: deepcopy(rows) for name in ('case_bm25', 'passage_bm25', 'dense_passage')}
        self.result = {'status': 'ok', 'policy': POLICY, 'execution_mode': 'cached_vector_diagnostic',
                       'model_requests': 0, 'request_id': 'request-fixture', 'query_case': self.case,
                       'query_sha256': sha256(self.query.encode('utf-8')).hexdigest(),
                       'channels': channels, 'hits': fuse_channels(channels, 1),
                       'coverage': {'dense_passage': {'scan_capped': True}},
                       'timings': {'dense_query_seconds': 0.25},
                       'query_vector': {'kind': 'cached_document_vector_diagnostic', 'passage_id': 'query:p1'},
                       'full_manifest_sha256': '1' * 64, 'sparse_manifest_sha256': '2' * 64,
                       'embedding_fingerprint': '3' * 64, 'collection': 'fixture', 'implementation_sha256': '4' * 64}
        self.session = Mock()
        self.session.search.return_value = self.result
        self.hybrid = HybridSearch(self.root, self.run_dir, EmbeddingBudget(0, 0),
                                   session_factory=lambda *_: self.session, execution_mode='cached_vector_diagnostic')
        self.addCleanup(self.hybrid.close)

    def search(self):
        return self.hybrid.search(self.query, self.case, 1, self.action)

    def links(self):
        events = self.hybrid.journal.events()
        return next(row for row in events if row['kind'] == 'search_returned'), events[0]

    def save(self):
        return capture(self.run_dir, operation=self.operation, action_id=self.action,
                       query=self.query, query_case=self.case, limit=1, result=self.result)

    def test_success_saves_full_channels_without_changing_payload_or_results(self):
        expected = deepcopy(self.result)
        before = observation(expected, {'source_need_id': 'need'}).observation
        returned = self.search()
        self.assertIs(returned, self.result)
        self.assertEqual(returned, expected)
        self.session.search.assert_called_once_with(self.query, self.case, 1)
        receipt, admission = self.links()
        body = verify_capture(self.run_dir, receipt, admission)
        self.assertEqual(body['result'], expected)
        self.assertEqual(body['query'], self.query)
        self.assertEqual(len(body['result']['channels']['dense_passage']), 4)
        self.assertEqual(len(body['result']['hits']), 1)
        self.assertEqual(before, observation(returned, {'source_need_id': 'need'}).observation)
        self.assertNotIn('diagnostic_path', before)
        self.assertEqual(inspect_run(self.run_dir)['searches'][0]['diagnostic_status'], 'verified')
        self.assertEqual(self.hybrid.usage()['model_requests'], 0)

    def test_save_failure_keeps_valid_result_and_marks_missing(self):
        with patch('pipeline_v2.m6_hybrid.capture_diagnostic', side_effect=OSError('local write failed')):
            self.assertIs(self.search(), self.result)
        receipt, _ = self.links()
        self.assertEqual(receipt['status'], 'success')
        self.assertEqual(receipt['diagnostic_status'], 'missing')
        self.assertEqual(receipt['diagnostic_error_type'], 'OSError')
        self.assertEqual(self.hybrid.usage()['search_failures'], 0)
        self.session.search.assert_called_once()
        self.assertEqual(inspect_run(self.run_dir)['searches'][0]['diagnostic_status'], 'missing')

    def test_existing_file_is_not_reused_or_overwritten(self):
        self.save()
        target = self.run_dir / 'retrieval_diagnostics' / f'{self.operation}.json'
        content = target.read_bytes()
        with self.assertRaises(FileExistsError): self.save()
        self.assertIs(self.search(), self.result)
        self.assertEqual(target.read_bytes(), content)
        receipt, _ = self.links()
        self.assertEqual(receipt['diagnostic_status'], 'missing')
        self.assertEqual(receipt['diagnostic_error_type'], 'FileExistsError')

    def test_missing_corrupt_and_traversal_artifact_rejected(self):
        self.search()
        receipt, admission = self.links()
        path = self.run_dir / receipt['diagnostic_path']
        content = path.read_bytes()
        path.write_bytes(content + b' ')
        with self.assertRaisesRegex(HarnessError, 'hash mismatch'): verify_capture(self.run_dir, receipt, admission)
        path.unlink()
        with self.assertRaises(FileNotFoundError): verify_capture(self.run_dir, receipt, admission)
        path.write_bytes(content)
        for relative in ('../outside.json', 'retrieval_diagnostics/../other.json', str(path.resolve())):
            with self.subTest(relative=relative), self.assertRaises(HarnessError):
                verify_capture(self.run_dir, {**receipt, 'diagnostic_path': relative}, admission)

    def test_linked_query_request_action_and_bindings_checked(self):
        self.search()
        receipt, admission = self.links()
        for key, value in (('m3_request_id', 'different'), ('action_id', 'b' * 64),
                           ('query_sha256', '9' * 64), ('diagnostic_bindings', {})):
            with self.subTest(key=key), self.assertRaises(HarnessError):
                verify_capture(self.run_dir, {**receipt, key: value}, admission)

    def test_interruption_after_save_retains_orphan_and_blocks_replay(self):
        append = self.hybrid.journal.append
        def interrupt(kind, **fields):
            if kind == 'search_returned': raise KeyboardInterrupt
            return append(kind, **fields)
        with patch.object(self.hybrid.journal, 'append', side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt): self.search()
        self.assertTrue((self.run_dir / 'retrieval_diagnostics' / f'{self.operation}.json').is_file())
        self.assertEqual(inspect_run(self.run_dir)['searches'][0]['status'], 'unknown')
        with self.assertRaisesRegex(HarnessError, 'already admitted'): self.search()
        self.session.search.assert_called_once()

    def test_transient_link_failure_keeps_success_and_no_retrieval_retry(self):
        append = self.hybrid.journal.append
        failed = False
        def flaky(kind, **fields):
            nonlocal failed
            if kind == 'search_returned' and not failed:
                failed = True
                raise OSError('link failed')
            return append(kind, **fields)
        with patch.object(self.hybrid.journal, 'append', side_effect=flaky):
            self.assertIs(self.search(), self.result)
        receipt, _ = self.links()
        self.assertEqual(receipt['status'], 'success')
        self.assertEqual(receipt['diagnostic_status'], 'missing')
        self.assertEqual(receipt['diagnostic_error_type'], 'OSError')
        self.session.search.assert_called_once()

    def test_exception_after_link_commit_does_not_duplicate_terminal_receipt(self):
        append = self.hybrid.journal.append
        def committed_then_exception(kind, **fields):
            append(kind, **fields)
            raise OSError('exception after commit')
        with patch.object(self.hybrid.journal, 'append', side_effect=committed_then_exception):
            self.assertIs(self.search(), self.result)
        self.assertEqual(len([row for row in self.hybrid.journal.events() if row['kind'] == 'search_returned']), 1)
        self.assertEqual(inspect_run(self.run_dir)['searches'][0]['diagnostic_status'], 'verified')
        self.session.search.assert_called_once()

    def test_underlying_search_failure_keeps_partial_unknown(self):
        self.session.search.side_effect = RuntimeError('dense failed after lexical')
        with self.assertRaises(RuntimeError): self.search()
        receipt, _ = self.links()
        self.assertEqual(receipt['status'], 'error')
        self.assertEqual(receipt['diagnostic_status'], 'unavailable')
        self.assertIn('partial channel results unknown', receipt['diagnostic_reason'])
        self.assertFalse((self.run_dir / 'retrieval_diagnostics').exists())

    def test_new_module_is_part_of_implementation_binding(self):
        binding = implementation_binding()
        self.assertEqual(binding['version'], 'm6-live-hybrid-v3')
        self.assertIn('pipeline_v2/retrieval_diagnostics.py', binding['files'])


class UsageRetentionTest(unittest.TestCase):
    # Reuse the existing fake transport/provider fixture without inheriting its tests.
    setUp = hybrid_fixtures.HybridTests.setUp
    runtime = hybrid_fixtures.HybridTests.runtime

    def test_failed_diagnostic_save_preserves_successful_embedding_receipt(self):
        hybrid = self.runtime(budget=EmbeddingBudget(1, 7))
        with patch('pipeline_v2.m6_hybrid.capture_diagnostic', side_effect=PermissionError):
            result = hybrid.search('procedural fairness', 'A', 1, 'd' * 64)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(hybrid.usage()['input_tokens'], 7)
        self.assertEqual(hybrid.usage()['model_requests'], 1)
        self.assertEqual(hybrid.usage()['search_receipts'][0]['diagnostic_status'], 'missing')


if __name__ == '__main__':
    unittest.main()
