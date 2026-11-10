"""Bounded benchmark control-flow tests; no paid inference or Qdrant."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from pipeline_v2.optimization import benchmark as module


class BenchmarkControlTests(unittest.TestCase):
    def run_fixture(self, oom=None):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root=Path(temp.name)
        (root/"index").mkdir()
        (root/"index/manifest.json").write_text("{}")
        passages=[{"passage_id":str(i),"text":str(i),"full_input_tokens":i+2} for i in range(256)]
        session=SimpleNamespace(passages=passages,vectors=np.tile([[1.,0.,0.]],(256,1)),
                                byid={str(i):i for i in range(256)},directory=root/"index",
                                base={"embedding_fingerprint":"baseline"},close=lambda:None)
        profile={"embedding":{"dimensions":3},"benchmark":{"representative_size":256,"batch_sizes":[16,32,64,128],"repeats":2,"parity_cosine_atol":.001}}
        called=[]
        ledgers=[]
        original_cache=module.Cache
        def cache(*args,**kwargs):
            value=original_cache(*args,**kwargs);ledgers.append(value);return value
        def request(remote,texts,profile,tok,code,ledger,label):
            called.append(label)
            if oom and label==f"stress-{oom}":raise module.BenchmarkOOM("simulated")
            n=len(texts)
            latency={16:1.,32:1.2,64:2.,128:5.}[n]
            return np.tile([[1.,0.,0.]],(n,1)),{"input_tokens":n*10,"padded_tokens":n*11,
                "remote_elapsed_seconds":latency,"client_elapsed_seconds":latency,
                "gpu_model_pool_seconds":latency*.8,"peak_allocated_bytes":60,
                "peak_reserved_bytes":99,"device_total_bytes":100}
        with patch.object(module,"Cache",side_effect=cache),patch.object(module,"load_profile",return_value=profile),patch.object(module,"FastSession",return_value=session),patch.object(module,"PinnedTokenizer"),patch.object(module,"request_embedding",side_effect=request):
            result=module.benchmark_index(root,"index","pipeline_v2/artifacts/test",embedder=object())
        for value in ledgers:value.db.close()
        return result,called

    def test_winner_uses_measured_throughput_and_allocated_not_reserved(self):
        result,_=self.run_fixture()
        self.assertEqual(result["status"],"simulated")
        self.assertEqual(result["winner_batch_size"],64)
        self.assertEqual(len(result["grid"]),4)
        self.assertLess(result["grid"][2]["reserved_headroom_fraction"],.1)
        self.assertGreaterEqual(result["grid"][2]["memory_headroom_fraction"],.1)

    def test_oom_stops_larger_sizes_without_claiming_their_success(self):
        result,calls=self.run_fixture(oom=32)
        self.assertEqual([x["status"] for x in result["grid"]],["PASS","OOM"])
        self.assertTrue(result["larger_sizes_not_run_due_to_oom"])
        self.assertNotIn("stress-64",calls)
        self.assertNotIn("stress-128",calls)
        self.assertEqual(result["winner_batch_size"],16)


if __name__=="__main__":unittest.main()
