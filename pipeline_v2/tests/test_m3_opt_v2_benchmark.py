"""No-network tests for benchmark sampling and separate OOM stress handling."""
from contextlib import nullcontext
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from pipeline_v2.optimization_v2 import benchmark
from pipeline_v2.optimization_v2.runtime import BenchmarkOOM


class SamplingContractTests(unittest.TestCase):
    def test_four_dense_windows_are_fixed_unique_and_shared_by_all_batch_sizes(self):
        passages = [{"passage_id": f"p{i:04}", "full_input_tokens": i + 1} for i in range(512)]
        first = benchmark.stratified_windows(passages)
        second = benchmark.stratified_windows(list(reversed(passages)))
        self.assertEqual(first, second)
        self.assertEqual(len(first), 4)
        ids_by_stratum = [row["passage_ids"] for row in first]
        self.assertTrue(all(len(ids) == len(set(ids)) == 64 for ids in ids_by_stratum))
        all_ids = [ident for group in ids_by_stratum for ident in group]
        self.assertEqual(len(all_ids), len(set(all_ids)))
        docs = {item["passage_id"]: item for item in passages}
        totals = {}
        for size in (16, 32, 64):
            actual_ids, real_tokens, padded_tokens = [], 0, 0
            for stratum in first:
                records = [docs[i] for i in stratum["passage_ids"]]
                actual_ids.extend(item["passage_id"] for item in records)
                for offset in range(0, len(records), size):
                    batch = records[offset:offset + size]
                    real_tokens += sum(item["full_input_tokens"] for item in batch)
                    padded_tokens += len(batch) * max(item["full_input_tokens"] for item in batch)
            self.assertEqual(actual_ids, all_ids)
            totals[size] = (len(actual_ids), real_tokens, padded_tokens)
        self.assertEqual(len({value[:2] for value in totals.values()}), 1)
        self.assertTrue(all(value[2] >= value[1] for value in totals.values()))

    def test_crossover_order_is_reproducible_and_balances_size_positions(self):
        orders = benchmark.crossover_orders([16, 32, 64], 3, 20261108)
        self.assertEqual(orders, benchmark.crossover_orders([16, 32, 64], 3, 20261108))
        self.assertEqual([set(row) for row in orders], [{16, 32, 64}] * 3)
        self.assertEqual({size: sum(row[pos] == size for row in orders for pos in range(3)) for size in (16, 32, 64)},
                         {16: 3, 32: 3, 64: 3})

    def test_mocked_oom_at_128_stress_keeps_16_32_64_candidates_and_usage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifacts = root / "pipeline_v2" / "artifacts"
            index_dir = artifacts / "index"
            index_dir.mkdir(parents=True)
            output_rel = "pipeline_v2/artifacts/benchmark"
            profile = {"benchmark": {"batch_sizes": [16, 32, 64], "strata": 4, "documents_per_stratum": 64,
                                      "repeats": 3, "seed": 37, "stress_batch_sizes": [16, 32, 64, 128],
                                      "parity_cosine_atol": .001}}
            metadata = [{"passage_id": f"p{i:04}", "full_input_tokens": i + 1, "case_id": f"c{i:04}"}
                        for i in range(512)]
            by_id = {item["passage_id"]: {**item, "text": f"fixture text {item['passage_id']}"} for item in metadata}

            class Lexical:
                def iter_documents(self, kind):
                    self_kind = kind
                    assert self_kind == "passage"
                    return iter(metadata)

            class Session:
                def __init__(self):
                    self.root = root
                    self.directory = index_dir
                    self.manifest = {"profile": profile}
                    self.lexical = Lexical()
                    self.ids = list(by_id)
                    self.byid = {ident: i for i, ident in enumerate(self.ids)}
                    self.vectors = np.tile(np.array([[1.0, 0.0]], dtype=np.float32), (len(self.ids), 1))
                    self.closed = False

                def full_passages(self, ids):
                    return [by_id[ident] for ident in ids]

                def close(self):
                    self.closed = True

            class Ledger:
                def __init__(self, *args):
                    self.db = type("DB", (), {"close": lambda self: None})()

                def usage(self):
                    return {"requests": len(fake_requests), "known_input_tokens": len(fake_requests), "unknown": None}

            fake_requests = []

            def fake_request(embedder, texts, kind, profile_arg, tokenizer, code, ledger, label):
                fake_requests.append(label)
                if label == "stress-128":
                    raise BenchmarkOOM("mocked OOM in stress guard")
                count = len(texts)
                lengths = [len(text.split()) for text in texts]
                input_tokens = sum(lengths)
                return np.tile(np.array([[1.0, 0.0]], dtype=np.float32), (count, 1)), {
                    "input_tokens": input_tokens, "padded_tokens": count * max(lengths),
                    "client_elapsed_seconds": .2, "remote_elapsed_seconds": .1,
                    "gpu_model_pool_seconds": .08, "peak_allocated_bytes": 10,
                    "peak_reserved_bytes": 20, "device_total_bytes": 100,
                }

            with patch.object(benchmark, "FastSession", side_effect=lambda *a, **k: Session()), \
                 patch.object(benchmark, "require_compatibility"), \
                 patch.object(benchmark, "PinnedTokenizer", return_value=object()), \
                 patch.object(benchmark, "Cache", Ledger), \
                 patch.object(benchmark, "run_lock", side_effect=lambda p: nullcontext()), \
                 patch.object(benchmark, "implementation", return_value={"fixture": "hash"}), \
                 patch.object(benchmark, "fingerprint", return_value="fixture-fingerprint"), \
                 patch.object(benchmark, "request_embedding", side_effect=fake_request):
                result = benchmark.benchmark_index(root, "pipeline_v2/artifacts/index", output_rel,
                                                   compatibility="receipt", embedder=object())
            self.assertEqual(result["execution_mode"], "simulated")
            self.assertEqual(result["status"], "simulated")
            self.assertEqual([(row["batch_size"], row["status"]) for row in result["stress"]],
                             [(16, "PASS"), (32, "PASS"), (64, "PASS"), (128, "OOM")])
            self.assertTrue(all(row["status"] == "PASS" for row in result["grid"]))
            self.assertTrue(all(row["documents"] == 256 * 3 for row in result["grid"]))
            self.assertEqual(sum("stress-" in label for label in fake_requests), 4)
            self.assertTrue(result["usage"]["known_input_tokens"] > 0)


if __name__ == "__main__":
    unittest.main()
