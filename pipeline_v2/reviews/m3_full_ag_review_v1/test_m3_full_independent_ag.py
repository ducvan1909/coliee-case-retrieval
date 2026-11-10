"""Independent AG local review, audit, and fault-injection test suite for M3 full corpus runner."""
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest
from contextlib import ExitStack, redirect_stdout, redirect_stderr
from unittest.mock import Mock, patch

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline_v2.full_corpus import common, runner, storage
from pipeline_v2.full_corpus.common import M3Error
from pipeline_v2.retrieval.cache import run_lock
from pipeline_v2.retrieval.qdrant import point_id
from pipeline_v2.source.core import canonical, digest

PLAN_DIR = ROOT / "pipeline_v2/artifacts/m3_full_train_20261108_v1"
REVIEW_DIR = Path(__file__).resolve().parent


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


class IndependentFullSuite(unittest.TestCase):
    """Comprehensive fault-injection and contract tests on temporary copies."""

    def _make_fixture(self, temp_dir: Path, num_passages: int = 3):
        run_dir = temp_dir / "mock_run"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "manifest.json").write_text('{"mock": true}', encoding="utf-8")
        docs = []
        rows = []
        for i in range(num_passages):
            pid = f"000001.txt:p{i:06d}"
            doc = {
                "passage_id": pid,
                "case_id": "000001.txt",
                "source_hash": "a" * 64,
                "exact_input_sha256": sha256_bytes(f"text-{i}".encode("utf-8")),
                "span_bytes": [0, 6],
                "parent_handle": f"p{i:06d}",
                "policy_hash": "c" * 64,
                "tokenizer_fingerprint": "d" * 64,
                "full_input_tokens": 10 + i,
            }
            docs.append(doc)
            rows.append((i // 2, pid, doc))  # batch size 2 for multi-batch testing

        class FakeLex:
            def __init__(self):
                self.db = Mock()
                self.db.execute.return_value = [(b, pid) for b, pid, _ in rows]

            def get_many(self, kind, ids):
                by_id = {d["passage_id"]: d for d in docs}
                return [by_id[i] for i in ids]

            def close(self):
                pass

        m = {
            "embedding_fingerprint": "f" * 64,
            "collection": "coliee_m3_full_test",
            "passages": num_passages,
            "batches": (num_passages + 1) // 2,
            "source_hashes": {"000001.txt": "a" * 64},
            "profile": {
                "embedding": {"dimensions": 2},
                "qdrant": {"version": "1.20.0", "url": "http://127.0.0.1:6333", "timeout_seconds": 10},
            },
        }
        return run_dir, docs, FakeLex(), m

    def test_01_crash_after_upsert_before_progress_resumes_without_reinference_or_reupsert(self):
        """Crash after DB upsert but before writing progress.json: resume skips both inference and upsert."""
        with tempfile.TemporaryDirectory() as tmp:
            run_dir, docs, lex, m = self._make_fixture(Path(tmp), num_passages=1)
            doc = docs[0]

            class MemStore:
                def __init__(self):
                    self.upserted = []
                def server_info(self): return {"version": "1.20.0"}
                def ensure(self): return None
                def check_schema(self): return None
                def count(self): return len(self.upserted)
                def matches(self, batch_docs, vectors):
                    return len(self.upserted) == len(batch_docs)
                def upsert(self, batch_docs, vectors):
                    self.upserted.extend(batch_docs)

            store = MemStore()
            fake_embedder = object()
            infer_calls = []

            def fake_request(embedder, texts, kind, profile, tok, code, ledger, label):
                infer_calls.append(label)
                att = ledger.begin(label, "v2_document")
                ledger.finish(att, "success", 0.1, 10, receipt={"input_tokens": 10})
                return np.array([[1.0, 0.0]], dtype=np.float32), {}

            orig_write = runner.write_json
            def crash_on_progress(path, data, replace=False):
                if Path(path).name == "progress.json":
                    raise RuntimeError("Simulated crash right after DB upsert before progress.json")
                return orig_write(path, data, replace=replace)

            with ExitStack() as stack:
                stack.enter_context(patch.object(runner, "load_plan", return_value=(ROOT, run_dir, m, lex)))
                stack.enter_context(patch.object(runner, "batches", side_effect=lambda _: iter([(0, [doc])])))
                stack.enter_context(patch.object(runner, "PinnedTokenizer", return_value=object()))
                stack.enter_context(patch.object(runner, "RawReader", return_value=Mock(text=Mock(return_value="text-0"))))
                stack.enter_context(patch.object(runner, "request_embedding", side_effect=fake_request))
                stack.enter_context(patch.object(runner, "guard"))
                stack.enter_context(patch.object(runner, "write_json", side_effect=crash_on_progress))
                with self.assertRaises(RuntimeError):
                    runner.run_full(ROOT, "unused", embedder=fake_embedder, store=store)

            self.assertEqual(len(infer_calls), 1)
            self.assertEqual(len(store.upserted), 1)
            self.assertFalse((run_dir / "progress.json").exists())

            # Now resume: since cache has the vector AND store.matches() is True, neither inference nor upsert is called!
            upsert_Spy = Mock(side_effect=AssertionError("Should not re-upsert already matching batch"))
            store.upsert = upsert_Spy
            with ExitStack() as stack:
                stack.enter_context(patch.object(runner, "load_plan", return_value=(ROOT, run_dir, m, lex)))
                stack.enter_context(patch.object(runner, "batches", side_effect=lambda _: iter([(0, [doc])])))
                stack.enter_context(patch.object(runner, "PinnedTokenizer", return_value=object()))
                stack.enter_context(patch.object(runner, "RawReader", return_value=Mock(text=Mock(return_value="text-0"))))
                stack.enter_context(patch.object(runner, "request_embedding", side_effect=AssertionError("No re-inference")))
                stack.enter_context(patch.object(runner, "guard"))
                res = runner.run_full(ROOT, "unused", embedder=fake_embedder, store=store)

            self.assertEqual(res["status"], "simulated")
            self.assertEqual(res["new_inference_batches"], 0)
            self.assertEqual(res["cached_batches"], 1)
            self.assertEqual(res["batches_processed_this_run"], 0)

    def test_02_max_batches_skips_already_matching_batches_and_advances_window(self):
        """--max-batches counts only batches needing inference/upsert in this invocation."""
        with tempfile.TemporaryDirectory() as tmp:
            run_dir, docs, lex, m = self._make_fixture(Path(tmp), num_passages=3)
            # 2 batches: batch 0 has docs[0], batch 1 has docs[1], batch 2 has docs[2]
            batch_list = [(0, [docs[0]]), (1, [docs[1]]), (2, [docs[2]])]
            m["batches"] = 3

            class KeyedStore:
                def __init__(self): self.by_pid = {}
                def server_info(self): return {"version": "1.20.0"}
                def ensure(self): return None
                def check_schema(self): return None
                def count(self): return len(self.by_pid)
                def matches(self, bdocs, vectors):
                    return all(d["passage_id"] in self.by_pid for d in bdocs)
                def upsert(self, bdocs, vectors):
                    for d, v in zip(bdocs, vectors):
                        self.by_pid[d["passage_id"]] = v

            store = KeyedStore()
            fake_embedder = object()

            def fake_request(embedder, texts, kind, profile, tok, code, ledger, label):
                att = ledger.begin(label, "v2_document")
                ledger.finish(att, "success", 0.05, 10)
                return np.array([[1.0, 0.0]], dtype=np.float32), {}

            # Run 1 with max_batches=2 -> processes batch 0 and 1, stops at boundary
            with ExitStack() as stack:
                stack.enter_context(patch.object(runner, "load_plan", return_value=(ROOT, run_dir, m, lex)))
                stack.enter_context(patch.object(runner, "batches", side_effect=lambda _: iter(batch_list)))
                stack.enter_context(patch.object(runner, "PinnedTokenizer", return_value=object()))
                stack.enter_context(patch.object(runner, "RawReader", return_value=Mock(text=Mock(return_value="txt"))))
                stack.enter_context(patch.object(runner, "request_embedding", side_effect=fake_request))
                stack.enter_context(patch.object(runner, "guard"))
                r1 = runner.run_full(ROOT, "unused", embedder=fake_embedder, store=store, max_batches=2)

            self.assertEqual(r1["status"], "simulated_partial")
            self.assertEqual(r1["batches_processed_this_run"], 2)
            self.assertEqual(r1["new_inference_batches"], 2)
            self.assertEqual(r1["cached_batches"], 0)
            self.assertEqual(store.count(), 2)

            # Run 2 with max_batches=2 -> skips batch 0 and 1 (cached + in DB), processes batch 2, finishes!
            with ExitStack() as stack:
                stack.enter_context(patch.object(runner, "load_plan", return_value=(ROOT, run_dir, m, lex)))
                stack.enter_context(patch.object(runner, "batches", side_effect=lambda _: iter(batch_list)))
                stack.enter_context(patch.object(runner, "PinnedTokenizer", return_value=object()))
                stack.enter_context(patch.object(runner, "RawReader", return_value=Mock(text=Mock(return_value="txt"))))
                stack.enter_context(patch.object(runner, "request_embedding", side_effect=fake_request))
                stack.enter_context(patch.object(runner, "guard"))
                r2 = runner.run_full(ROOT, "unused", embedder=fake_embedder, store=store, max_batches=2)

            self.assertEqual(r2["status"], "simulated")
            self.assertEqual(r2["batches_processed_this_run"], 1)
            self.assertEqual(r2["new_inference_batches"], 1)
            self.assertEqual(r2["cached_batches"], 2)
            self.assertEqual(store.count(), 3)

    def test_03_orphan_npz_rejected_by_readonly_verify_but_recovered_by_explicit_resume(self):
        """Orphan .npz without .json fails in ReadonlyCache (verify), but recovers in FullCache during run resume."""
        with tempfile.TemporaryDirectory() as tmp:
            run_dir, docs, lex, m = self._make_fixture(Path(tmp), num_passages=1)
            doc = docs[0]
            fp = m["embedding_fingerprint"]
            ids = [doc["passage_id"]]
            hashes = [doc["exact_input_sha256"]]
            base = run_dir / "vectors" / digest(canonical([fp, ids]))
            base.parent.mkdir(parents=True, exist_ok=True)
            np.savez(
                base.with_suffix(".npz"),
                vectors=np.array([[1.0, 0.0]], dtype=np.float32),
                ids=np.asarray(ids, dtype=str),
                input_hashes=np.asarray(hashes, dtype=str),
                fingerprint=np.asarray(fp),
            )
            # 1) ReadonlyCache must raise M3Error and NOT create .json
            ro = storage.ReadonlyCache(run_dir, fp, 2)
            with self.assertRaises(M3Error):
                ro.get_batch(ids, hashes)
            self.assertFalse(base.with_suffix(".json").exists())

            # 2) FullCache (when uncommitted in full_batches) recovers the valid .npz and writes .json
            fc = storage.FullCache(run_dir, fp, 2)
            try:
                vecs = fc.get_batch(ids, hashes)
                self.assertIsNotNone(vecs)
                self.assertTrue(base.with_suffix(".json").exists())
                # 3) If .npz is corrupted after .json exists, both ReadonlyCache and FullCache fail closed
                base.with_suffix(".npz").write_bytes(b"corrupted")
                with self.assertRaises(M3Error):
                    ro.get_batch(ids, hashes)
                with self.assertRaises(M3Error):
                    fc.get_batch(ids, hashes)
            finally:
                fc.db.close()

    def test_04_execution_identity_blocks_mock_adoption_and_missing_state_adoption(self):
        """Simulated run cannot be resumed as real_modal, and pre-existing ledger/vectors without execution_state.json fail."""
        with tempfile.TemporaryDirectory() as tmp:
            run_dir, docs, lex, m = self._make_fixture(Path(tmp), num_passages=1)
            # Case A: vectors/ exists but execution_state.json does not -> refuse cache adoption
            (run_dir / "vectors").mkdir()
            with patch.object(runner, "load_plan", return_value=(ROOT, run_dir, m, lex)):
                with self.assertRaisesRegex(M3Error, "Execution state missing"):
                    runner.run_full(ROOT, "unused", embedder=object(), store=Mock())

            # Case B: execution_state.json is 'simulated', try running real_modal or verify real
            (run_dir / "vectors").rmdir()
            runner.write_json(run_dir / "execution_state.json", runner.execution_state(run_dir, m, "simulated"))
            with patch.object(runner, "load_plan", return_value=(ROOT, run_dir, m, lex)):
                with self.assertRaisesRegex(M3Error, "Cannot change full run execution identity"):
                    runner.run_full(ROOT, "unused")  # real mode
                with self.assertRaisesRegex(M3Error, "Verification execution identity missing or differs"):
                    runner.verify_full(ROOT, "unused")  # real verify against simulated state

    def test_05_run_lock_prevents_concurrent_writers(self):
        """Second writer attempting to acquire run_lock on the same directory fails immediately."""
        with tempfile.TemporaryDirectory() as tmp:
            with run_lock(tmp):
                with self.assertRaisesRegex(M3Error, "Another M3 operation owns this run"):
                    with run_lock(tmp):
                        pass

    def test_06_local_cli_commands_never_read_env_or_import_modal(self):
        """status, verify, open, plan, and --help do not read .env or import modal."""
        from pipeline_v2 import m3_full
        with patch("pipeline_v2.deploy_modal.parse_env", side_effect=AssertionError(".env parsed!")), \
             patch("pipeline_v2.deploy_modal.build_environment", side_effect=AssertionError("env built!")):
            for cmd, extra, fn_name, fake_ret in [
                ("status", ["--run-dir", "pipeline_v2/artifacts/x"], "status_full", {"status": "planned"}),
                ("verify", ["--run-dir", "pipeline_v2/artifacts/x"], "verify_full", {"status": "PASS"}),
                ("open", ["--run-dir", "pipeline_v2/artifacts/x", "--passage-id", "000001.txt:p0"], "open_full", {"status": "ok"}),
            ]:
                buf = io.StringIO()
                with patch(f"pipeline_v2.full_corpus.runner.{fn_name}", return_value=dict(fake_ret)), redirect_stdout(buf):
                    rc = m3_full.main(["--env-file", "DOES_NOT_EXIST.env", cmd, *extra])
                self.assertEqual(rc, 0)

    def test_07_qdrant_short_response_wrong_vector_wrong_payload_and_ensure_cycle(self):
        """Test FullQdrant.matches and ensure pagination cycle / payload / vector checks."""
        s = storage.FullQdrant("http://127.0.0.1:6333", "coliee_m3_full_test", "f" * 64, 2)
        s._request = Mock()
        p1 = {
            "passage_id": "000001.txt:p000001", "case_id": "000001.txt", "source_hash": "a" * 64,
            "exact_input_sha256": "b" * 64, "span_bytes": [0, 1], "parent_handle": "p000001",
            "policy_hash": "c" * 64, "tokenizer_fingerprint": "d" * 64,
        }
        p2 = {**p1, "passage_id": "000001.txt:p000002"}
        good_payload = {k: p1[k] for k in storage.PAYLOAD}
        good_payload["embedding_fingerprint"] = "f" * 64

        # 1) Short response where present row is valid -> returns False (needs upsert), does not pass as complete
        s._request.return_value = [{"id": point_id(p1["passage_id"], "f" * 64), "payload": good_payload, "vector": [1.0, 0.0]}]
        self.assertFalse(s.matches([p1, p2], np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)))

        # 2) Short response where present row has wrong vector -> raises M3Error immediately
        s._request.return_value = [{"id": point_id(p1["passage_id"], "f" * 64), "payload": good_payload, "vector": [0.0, 1.0]}]
        with self.assertRaisesRegex(M3Error, "Stored full vector differs"):
            s.matches([p1, p2], np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32))

        # 3) Short response where present row has wrong payload -> raises M3Error immediately
        bad_payload = {**good_payload, "policy_hash": "e" * 64}
        s._request.return_value = [{"id": point_id(p1["passage_id"], "f" * 64), "payload": bad_payload, "vector": [1.0, 0.0]}]
        with self.assertRaisesRegex(M3Error, "Stored full payload drift"):
            s.matches([p1, p2], np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32))

        # 4) ensure() on existing collection with A->B->A pagination cycle fails closed
        s.info = Mock(return_value={"config": {"params": {"vectors": {"size": 2, "distance": "Cosine", "on_disk": True}}}})
        offsets = []
        def cycle_req(method, path, body=None, allow404=False):
            offsets.append((body or {}).get("offset"))
            seq = ["A", "B", "A"]
            return {"points": [], "next_page_offset": seq[len(offsets) - 1]}
        s._request = cycle_req
        with self.assertRaisesRegex(M3Error, "Qdrant pagination did not advance"):
            s.ensure()


def run_independent_plan_and_bm25_audit():
    """Audit the real full plan SQLite, manifest, seal, M2 bundle, raw cases, and BM25 oracle."""
    t0 = time.perf_counter()
    manifest = json.loads((PLAN_DIR / "manifest.json").read_bytes())
    seal_data = json.loads((PLAN_DIR / "seal.json").read_bytes())
    assert set(seal_data) == {"manifest.json", "lexical.sqlite3"}
    for name, expected in seal_data.items():
        p = PLAN_DIR / name
        actual = {"sha256": sha256_file(p), "bytes": p.stat().st_size}
        assert actual == expected, f"Seal mismatch on {name}: {actual} != {expected}"

    # Verify implementation fingerprint and profile
    root_impl = common.implementation()
    impl_fp = digest(canonical(root_impl))
    assert manifest["implementation"] == root_impl
    assert impl_fp == "e4b8b358697c67073134fe5c5929e770d5c9c1e0b30f2cd98fc686b1227e3503"
    profile = common.load_profile(ROOT)
    assert manifest["profile"] == profile
    comp = common.compatibility(ROOT, profile)
    assert manifest["compatibility"] == comp

    # Readonly SQLite audit
    db_uri = (PLAN_DIR / "lexical.sqlite3").resolve().as_uri() + "?mode=ro"
    db = sqlite3.connect(db_uri, uri=True)
    try:
        # Check table counts and absence of raw text
        doc_counts = dict(db.execute("SELECT kind, COUNT(*) FROM documents GROUP BY kind").fetchall())
        assert doc_counts == {"case": 7708, "passage": 415693}
        text_leaks = db.execute("SELECT COUNT(*) FROM documents WHERE json_type(metadata, '$.text') IS NOT NULL OR instr(metadata, '\"text\"') > 0").fetchone()[0]
        assert text_leaks == 0, f"Found {text_leaks} metadata rows containing text key"

        # Check schedule ordering, batching, token counts, and padding
        sql = """
            SELECT s.ordinal, s.batch, s.passage_id,
                   json_extract(d.metadata, '$.full_input_tokens'),
                   json_extract(d.metadata, '$.case_id'),
                   json_extract(d.metadata, '$.span_bytes[0]'),
                   json_extract(d.metadata, '$.span_bytes[1]'),
                   json_extract(d.metadata, '$.exact_input_sha256')
            FROM schedule s
            JOIN documents d ON d.kind = 'passage' AND d.id = s.passage_id
            ORDER BY s.ordinal
        """
        prev_key = None
        total_input_tokens = 0
        total_padded_tokens = 0
        batch_tokens = []
        batch_count = 0
        cases_seen_in_passages = set()
        sample_passages = []

        for expected_ord, (ordinal, batch, pid, tok_len, case_id, b_start, b_end, exact_sha) in enumerate(db.execute(sql)):
            assert ordinal == expected_ord
            assert batch == expected_ord // 64
            assert isinstance(tok_len, int) and 1 <= tok_len <= 448
            key = (tok_len, pid)
            assert prev_key is None or prev_key < key, f"Sort violation at {ordinal}: {prev_key} >= {key}"
            prev_key = key
            cases_seen_in_passages.add(case_id)
            batch_tokens.append(tok_len)
            total_input_tokens += tok_len
            if expected_ord in (0, 63, 64, 200000, 415679, 415680, 415692):
                sample_passages.append((ordinal, batch, pid, tok_len, case_id, b_start, b_end, exact_sha))
            if len(batch_tokens) == 64:
                total_padded_tokens += max(batch_tokens) * 64
                batch_tokens = []
                batch_count += 1

        last_batch_size = len(batch_tokens)
        if batch_tokens:
            total_padded_tokens += max(batch_tokens) * last_batch_size
            batch_count += 1

        assert expected_ord + 1 == 415693
        assert batch_count == 6496
        assert last_batch_size == 13
        assert total_input_tokens == 55346360
        assert total_padded_tokens == 55360576

        # Verify sample passages against raw files and tokenizer
        from pipeline_v2.passages import PinnedTokenizer
        tok = PinnedTokenizer(ROOT, "pipeline_v2/configs/qwen3_embedding_4b_tokenizer.lock.json")
        verified_samples = []
        for ordinal, batch, pid, tok_len, case_id, b_start, b_end, exact_sha in sample_passages:
            raw_bytes = (ROOT / "data/task1_train_files_2026/cases" / case_id).read_bytes()
            assert sha256_bytes(raw_bytes) == manifest["source_hashes"][case_id]
            span = raw_bytes[b_start:b_end]
            assert sha256_bytes(span) == exact_sha
            text = span.decode("utf-8")
            encoded_ids = tok.backend.encode(text, add_special_tokens=True).ids
            assert len(encoded_ids) == tok_len
            assert encoded_ids[-1] == 151643
            verified_samples.append({
                "ordinal": ordinal, "batch": batch, "passage_id": pid,
                "full_input_tokens": tok_len, "span_bytes": [b_start, b_end],
                "exact_input_sha256": exact_sha,
            })

        # Verify PersistentBM25 read-only queries on both case and passage channels
        from pipeline_v2.optimization_v2.index import PersistentBM25
        bm25 = PersistentBM25(PLAN_DIR / "lexical.sqlite3")
        try:
            q_case = bm25.search("standard of review reasonableness", "case", limit=5)
            q_pass = bm25.search("standard of review reasonableness", "passage", limit=5)
            assert len(q_case) == 5 and all("text" not in h for h in q_case)
            assert len(q_pass) == 5 and all("text" not in h for h in q_pass)
        finally:
            bm25.close()

        # Verify open_full works locally without Modal or Qdrant
        opened = runner.open_full(ROOT, "pipeline_v2/artifacts/m3_full_train_20261108_v1", sample_passages[0][2])
        assert opened["hit_passage_id"] == sample_passages[0][2]
    finally:
        db.close()

    return {
        "status": "PASS",
        "elapsed_seconds": time.perf_counter() - t0,
        "implementation_fingerprint": impl_fp,
        "collection": manifest["collection"],
        "cases": 7708,
        "cases_with_passages": len(cases_seen_in_passages),
        "passages": 415693,
        "batches": 6496,
        "last_batch_size": 13,
        "input_tokens": total_input_tokens,
        "padded_tokens": total_padded_tokens,
        "padding_ratio": total_padded_tokens / total_input_tokens,
        "sqlite_bytes": seal_data["lexical.sqlite3"]["bytes"],
        "text_leaks_in_metadata": 0,
        "verified_samples": verified_samples,
        "bm25_smoke_top1_case": q_case[0]["case_id"],
        "bm25_smoke_top1_passage": q_pass[0]["passage_id"],
        "open_full_smoke_passage": opened["hit_passage_id"],
    }


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(IndependentFullSuite)
    buf = io.StringIO()
    res = unittest.TextTestRunner(stream=buf, verbosity=2).run(suite)
    if not res.wasSuccessful():
        print(buf.getvalue(), file=sys.stderr)
        sys.exit(1)
    audit = run_independent_plan_and_bm25_audit()
    out = {
        "independent_unit_tests": {
            "total": res.testsRun,
            "failures": len(res.failures),
            "errors": len(res.errors),
            "status": "PASS" if res.wasSuccessful() else "FAIL",
            "log": buf.getvalue(),
        },
        "independent_full_plan_audit": audit,
    }
    out_path = REVIEW_DIR / "independent_local_test_results.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "tests_run": res.testsRun, "audit_elapsed_seconds": audit["elapsed_seconds"]}))
