import tempfile
import unittest
from pathlib import Path

import numpy as np

from pipeline_v2.retrieval.cache import Cache, validate_vectors
from pipeline_v2.retrieval.common import M3Error


class M3CacheTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.cache=Cache(Path(self.temp.name)/"run", "profile-a", dimensions=3)
        self.ids=["p1","p2"]
        self.hashes=["input-hash-1","input-hash-2"]
        self.vectors=np.array([[1,0,0],[0,1,0]],dtype=np.float32)

    def tearDown(self):
        self.cache.db.close()
        self.temp.cleanup()

    def test_normalized_vectors_validate_shape_finiteness_and_norm(self):
        self.assertTrue(np.array_equal(validate_vectors(self.vectors,2,3),self.vectors))
        for value,count,dim in [([[1,0]],2,3), ([[1,float("nan"),0],[0,1,0]],2,3),
                                ([[2,0,0],[0,1,0]],2,3)]:
            with self.subTest(value=value):
                with self.assertRaises(M3Error): validate_vectors(value,count,dim)

    def test_atomic_batch_commit_reloads_exact_vectors_and_is_idempotent(self):
        self.assertIsNone(self.cache.get_batch(self.ids,self.hashes))
        self.cache.commit_batch(self.ids,self.hashes,self.vectors)
        loaded=self.cache.get_batch(self.ids,self.hashes)
        self.assertTrue(np.array_equal(loaded,self.vectors))
        self.cache.commit_batch(self.ids,self.hashes,self.vectors)
        self.assertTrue(np.array_equal(self.cache.get_batch(self.ids,self.hashes),self.vectors))
        changed=self.vectors.copy(); changed[0]=[0,0,1]
        with self.assertRaises(M3Error): self.cache.commit_batch(self.ids,self.hashes,changed)

    def test_corrupt_or_missing_committed_array_is_rejected(self):
        self.cache.commit_batch(self.ids,self.hashes,self.vectors)
        base=self.cache._base(self.ids)
        array_path=base.with_suffix(".npz")
        original=array_path.read_bytes()
        array_path.write_bytes(original+b"corruption")
        with self.assertRaises(M3Error): self.cache.get_batch(self.ids,self.hashes)
        array_path.write_bytes(original)
        array_path.unlink()
        with self.assertRaises(M3Error): self.cache.get_batch(self.ids,self.hashes)

    def test_committed_cache_cannot_be_reused_for_other_inputs_or_profile(self):
        self.cache.commit_batch(self.ids,self.hashes,self.vectors)
        with self.assertRaises(M3Error): self.cache.get_batch(self.ids,["different-1","different-2"])
        other=Cache(Path(self.temp.name)/"run", "profile-b", dimensions=3)
        self.assertIsNone(other.get_batch(self.ids,self.hashes))
        other.db.close()

    def test_attempt_ledger_keeps_failed_and_unknown_token_attempts(self):
        first=self.cache.begin("batch-1","embed",tokens=12)
        self.cache.finish(first,"failed",0.5,tokens=12,error="offline-model-failure")
        second=self.cache.begin("batch-1","embed",tokens=None)
        usage=self.cache.usage()
        self.assertEqual(usage["model_requests"],2)
        self.assertEqual(usage["known_input_tokens"],12)
        self.assertEqual(usage["unknown_token_attempts"],1)
        self.assertEqual([x["status"] for x in usage["attempts"]], ["failed","started"])
        self.cache.finish(second,"succeeded",1.25,tokens=9)
        self.assertEqual(self.cache.usage()["known_input_tokens"],21)


if __name__=="__main__":
    unittest.main()
