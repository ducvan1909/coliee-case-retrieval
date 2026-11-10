"""Independent edge tests for full-corpus storage and resume contracts."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

import numpy as np

from pipeline_v2.full_corpus.storage import FullCache, FullQdrant, ReadonlyCache, PAYLOAD
from pipeline_v2.optimization_v2.common import M3Error
from pipeline_v2.source.core import canonical, digest
from pipeline_v2.retrieval.qdrant import point_id


def passage(pid='000001.txt:p000001'):
    return {
        'passage_id': pid, 'case_id': '000001.txt', 'source_hash': 'a' * 64,
        'exact_input_sha256': 'b' * 64, 'span_bytes': [0, 1],
        'parent_handle': 'p000001', 'policy_hash': 'c' * 64,
        'tokenizer_fingerprint': 'd' * 64,
    }


class FullStorageTests(unittest.TestCase):
    def store(self, dimension=2):
        s = FullQdrant('http://127.0.0.1:6333', 'coliee_m3_full_test', 'f' * 64, dimension)
        s._request = Mock()
        return s

    def row(self, p, vector=(1.0, 0.0), **payload_override):
        payload = {key: p[key] for key in PAYLOAD}
        payload['embedding_fingerprint'] = 'f' * 64
        payload.update(payload_override)
        return {'id': point_id(p['passage_id'], 'f' * 64), 'payload': payload,
                'vector': list(vector)}

    def test_qdrant_matches_accepts_exact_valid_batch(self):
        p = passage()
        s = self.store()
        s._request.return_value = [self.row(p)]
        self.assertTrue(s.matches([p], np.array([[1.0, 0.0]], dtype=np.float32)))

    def test_qdrant_matches_rejects_foreign_row_even_when_batch_is_incomplete(self):
        """A missing neighbor must not hide corruption in the row that did arrive."""
        p1, p2 = passage('000001.txt:p000001'), passage('000001.txt:p000002')
        s = self.store()
        s._request.return_value = [self.row(p1, vector=(0.0, 1.0), embedding_fingerprint='e' * 64)]
        with self.assertRaises(M3Error):
            s.matches([p1, p2], np.array([[1.0, 0.0], [1.0, 0.0]], dtype=np.float32))

    def test_qdrant_matches_rejects_unrequested_or_duplicate_id(self):
        p = passage()
        s = self.store()
        s._request.return_value = [self.row(p), {**self.row(p), 'id': 'foreign-id'}]
        with self.assertRaises(M3Error):
            s.matches([p], np.array([[1.0, 0.0]], dtype=np.float32))

    def test_readonly_cache_does_not_repair_orphan_array(self):
        with tempfile.TemporaryDirectory() as temp:
            fp = 'f' * 64
            p = passage()
            base = Path(temp) / 'vectors' / digest(canonical([fp, [p['passage_id']]]))
            base.parent.mkdir()
            np.savez(base.with_suffix('.npz'), vectors=np.array([[1.0, 0.0]], dtype=np.float32),
                     ids=np.array([p['passage_id']]), input_hashes=np.array([p['exact_input_sha256']]),
                     fingerprint=np.asarray(fp))
            cache = ReadonlyCache(temp, fp, 2)
            with self.assertRaises(M3Error):
                cache.get_batch([p['passage_id']], [p['exact_input_sha256']])
            self.assertFalse(base.with_suffix('.json').exists(), 'readonly verify must not write a repair receipt')

    def test_usage_counts_started_attempt_as_unknown_not_zero(self):
        with tempfile.TemporaryDirectory() as temp:
            cache = FullCache(temp, 'f' * 64, 2)
            try:
                cache.begin('in-flight', 'document')
                cache.finish(cache.begin('known', 'document'), 'error', 0.5, 13, 'RemoteError')
                usage = cache.usage()
                self.assertEqual(usage['model_requests'], 2)
                self.assertEqual(usage['known_input_tokens'], 13)
                self.assertEqual(usage['unknown_token_attempts'], 1)
                self.assertEqual(usage['status_counts'], {'error': 1, 'started': 1})
            finally:
                cache.db.close()

    def test_existing_collection_cycle_guard_fails_closed(self):
        """Pagination must not loop forever on a multi-offset cycle."""
        s = self.store()
        page_offsets = []
        def request(method, path, body=None):
            offset = (body or {}).get('offset')
            page_offsets.append(offset)
            cycle = ['A', 'B', 'A', 'B', 'A']
            if len(page_offsets) > len(cycle):
                raise AssertionError('pagination cycled without a guard')
            return {'points': [], 'next_page_offset': cycle[len(page_offsets) - 1]}
        s._request = request
        lexical = Mock()
        lexical.get_many.return_value = []
        with self.assertRaises(M3Error):
            s.validate_existing(lexical)


if __name__ == '__main__':
    unittest.main()
