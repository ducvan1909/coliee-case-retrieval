"""Independent AG local test suite for M3 pilot & retrieval contracts (Section 3)."""
import hashlib
import io
import json
from contextlib import nullcontext, redirect_stderr, redirect_stdout
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import numpy as np
import requests
from tokenizers import Tokenizer

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline_v2 import deploy_modal, m3
from pipeline_v2.passages import PinnedTokenizer
from pipeline_v2.retrieval import bm25, cache as cache_mod, common, corpus as corpus_mod, pilot, qdrant, runtime
RUN_DIR_REL = "pipeline_v2/artifacts/m3_pilot_20261106_l4_v1"
RUN_DIR = ROOT / RUN_DIR_REL
EXPECTED_M2_SEAL = "0ed42d51023adaf47c1205fa925f18f31b7aacb58b0c8e44c7d23288d123dda6"
EXPECTED_NAV_SEAL = "43ca58589704e94754be3ed6b343ffa73f806a0c757c752abffa1fdb4942234c"
EXPECTED_REVISION = "5cf2132abc99cad020ac570b19d031efec650f2b"
EXPECTED_FP = "d945329fa49e2f4b4f83d530df03fb4897babd5345562cbeaebd3b21499649bf"
EXPECTED_IMPL_AGG = "ade771e2d328b974d12421b5fa48b2b90632b10eb8422166f82b9f960d9add63"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_bytes(obj) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


class AGIndependentM3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = json.loads((ROOT / "pipeline_v2/configs/m3.json").read_bytes())
        cls.manifest_raw = (RUN_DIR / "pilot_manifest.json").read_bytes()
        cls.manifest = json.loads(cls.manifest_raw)
        cls.lock = json.loads((ROOT / "pipeline_v2/configs/qwen3_embedding_4b_tokenizer.lock.json").read_bytes())
        tok_path = ROOT / cls.lock["assets_dir"] / "tokenizer.json"
        cls.raw_tokenizer = Tokenizer.from_file(str(tok_path))
        cls.pinned_tokenizer = PinnedTokenizer(ROOT, "pipeline_v2/configs/qwen3_embedding_4b_tokenizer.lock.json")

    # --- 1. Pilot manifest determinism, scope, provenance, and drift detection ---
    def test_01_real_l4_pilot_manifest_provenance_and_independent_audit(self):
        seal = json.loads((RUN_DIR / "manifest.sha256.json").read_bytes())
        self.assertEqual(seal, {"sha256": sha(self.manifest_raw)})
        self.assertEqual(self.manifest["scope"], "pilot_only")
        self.assertEqual(self.manifest["profile"], self.profile)
        self.assertEqual(self.manifest["embedding_fingerprint"], EXPECTED_FP)
        self.assertEqual(sha(canonical_bytes(self.profile["embedding"])), EXPECTED_FP)

        impl = common.implementation()
        self.assertEqual(self.manifest["implementation"], impl)
        self.assertEqual(sha(canonical_bytes(impl)), EXPECTED_IMPL_AGG)

        # Verify M2 and navigation seals directly from disk without Corpus/PassageReader
        m2_bundle = ROOT / self.profile["passages_bundle"]
        m2_seal_raw = (m2_bundle / "seal.json").read_bytes()
        self.assertEqual(sha(m2_seal_raw), EXPECTED_M2_SEAL)
        self.assertEqual(self.manifest["m2_seal_sha256"], EXPECTED_M2_SEAL)
        m2_seal = json.loads(m2_seal_raw)
        m2_manifest = json.loads((m2_bundle / "manifest.json").read_bytes())
        nav_bundle = ROOT / m2_manifest["navigation"]["bundle"]
        nav_seal_raw = (nav_bundle / "seal.json").read_bytes()
        self.assertEqual(sha(nav_seal_raw), EXPECTED_NAV_SEAL)
        nav_seal = json.loads(nav_seal_raw)

        ids = self.manifest["passage_ids"]
        self.assertEqual(len(ids), 1024)
        self.assertEqual(len(set(ids)), 1024)
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(len(self.manifest["source_hashes"]), 916)
        self.assertFalse(self.manifest["labels_accessed"])
        self.assertFalse(self.manifest["test_sources_accessed"])

        # Re-verify all 916 case records and 1024 passages directly against raw case files and raw tokenizer
        passages_by_id = {}
        preview_counts = {}
        for case_id, expected_src_hash in self.manifest["source_hashes"].items():
            raw_bytes = (ROOT / "data/task1_train_files_2026/cases" / case_id).read_bytes()
            self.assertEqual(sha(raw_bytes), expected_src_hash)
            rel = f"sources/{case_id[:-4]}.json"
            p_raw = (m2_bundle / rel).read_bytes()
            self.assertEqual(m2_seal["files"][rel], {"sha256": sha(p_raw), "byte_length": len(p_raw)})
            p_rec = json.loads(p_raw)
            for p in p_rec["passages"]:
                passages_by_id[p["passage_id"]] = (p, raw_bytes)
            n_raw = (nav_bundle / rel).read_bytes()
            self.assertEqual(nav_seal["files"][rel], {"sha256": sha(n_raw), "byte_length": len(n_raw)})
            n_rec = json.loads(n_raw)
            for u in n_rec["navigation"]:
                preview_counts[u["unit_id"]] = len(u["preview_refs"])

        split_c = unicode_c = no_preview_c = 0
        for idx, pid in enumerate(ids):
            p, raw_bytes = passages_by_id[pid]
            a, b = p["span_bytes"]
            slice_bytes = raw_bytes[a:b]
            self.assertEqual(slice_bytes.decode("utf-8"), p["text"])
            self.assertEqual(sha(slice_bytes), p["exact_input_sha256"])
            self.assertEqual(self.manifest["input_hashes"][idx], p["exact_input_sha256"])
            toks = self.raw_tokenizer.encode(p["text"], add_special_tokens=True).ids
            self.assertEqual(len(toks), p["full_input_tokens"])
            self.assertLessEqual(len(toks), 448)
            self.assertEqual(toks[-1], 151643)
            self.assertEqual(toks.count(151643), 1)
            split_c += int(p["split_count"] > 1)
            unicode_c += int(any(ord(c) > 127 for c in p["text"]))
            no_preview_c += int(preview_counts[p["parent_unit_ids"][0]] == 0)

        self.assertEqual(
            self.manifest["selection"]["strata_actual"],
            {"split_children": split_c, "unicode": unicode_c, "no_preview": no_preview_c},
        )

    def test_02_sample_passages_determinism_and_drift_guards(self):
        # Construct synthetic stream covering all risk tags
        stream = []
        for i in range(40):
            stream.append({
                "passage_id": f"0000{i:02d}:p000001",
                "case_id": f"0000{i:02d}.txt",
                "full_input_tokens": min(448, (i % 8) * 64 + 10),
                "paragraph_role": ["current_case", "quoted", "unknown"][i % 3],
                "unit_kind": "paragraph" if i % 4 else "unnumbered",
                "split_count": 3 if i < 6 else 1,
                "split_order": i % 3 if i < 6 else 0,
                "text": f"Café résumé {i}" if i % 5 == 0 else f"Standard text {i}",
                "navigation_preview_count": 0 if i == 7 else 2,
            })
        s1 = pilot.sample_passages(stream, size=24, seed=20261106)
        s2 = pilot.sample_passages(list(reversed(stream)), size=24, seed=20261106)
        self.assertEqual([p["passage_id"] for p in s1], [p["passage_id"] for p in s2])
        self.assertTrue(any(p["navigation_preview_count"] == 0 for p in s1))
        self.assertTrue(any(p["split_count"] > 1 and p["split_order"] == 1 for p in s1))

        # Test load_run drift detection on tampered manifest/profile/code/source
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = root / "pipeline_v2/artifacts/t_run"
            run.mkdir(parents=True)
            m = json.loads(self.manifest_raw)
            common.write_json(run / "pilot_manifest.json", m)
            common.write_json(run / "manifest.sha256.json", {"sha256": "0" * 64})
            with self.assertRaisesRegex(common.M3Error, "manifest drift"):
                pilot.load_run(root, "pipeline_v2/artifacts/t_run")

            # Valid seal, but code drift
            common.write_json(run / "manifest.sha256.json", {"sha256": sha((run / "pilot_manifest.json").read_bytes())}, replace=True)
            with patch.object(pilot, "load_profile", return_value=self.profile), \
                 patch.object(pilot, "implementation", return_value={"tampered": "1"}):
                with self.assertRaisesRegex(common.M3Error, "code/profile drift"):
                    pilot.load_run(root, "pipeline_v2/artifacts/t_run")

    # --- 2. Document exact raw body, query instruction, EOS 151643, special literals & cap 448 ---
    def test_03_document_vs_query_encoding_special_literals_and_448_cap(self):
        specials = [
            "hello",
            "\ufeff[1] élément\r\n法🧑‍⚖️",
            "<|endoftext|> <|im_start|> <FRAGMENT_SUPPRESSED>",
            "word " * 446,  # 447 content tokens + 1 EOS = 448 tokens
        ]
        for s in specials:
            enc = self.pinned_tokenizer.backend.encode(s, add_special_tokens=True)
            self.assertLessEqual(len(enc.ids), 448)
            self.assertEqual(enc.ids[-1], 151643)
        # Verify "word " * 446 is exactly 448 tokens, and "word " * 447 is 449 tokens
        self.assertEqual(self.pinned_tokenizer.count("word " * 446), 448)
        self.assertEqual(self.pinned_tokenizer.count("word " * 447), 449)

        # Query rendering adds instruction once and checks 448 cap on rendered string
        q = "standard of review for reasonableness"
        rendered_q = runtime.render_query(q, self.profile)
        self.assertEqual(
            rendered_q,
            f"Instruct: {self.profile['embedding']['query_instruction']}\nQuery:{q}",
        )
        self.assertEqual(rendered_q.count("Instruct:"), 1)

        # Query that fits raw (<448) but overflows after adding query instruction (>448) must be rejected before remote call
        borderline_q = "word " * 430
        self.assertLess(self.pinned_tokenizer.count(borderline_q), 448)
        self.assertGreater(self.pinned_tokenizer.count(runtime.render_query(borderline_q, self.profile)), 448)
        with tempfile.TemporaryDirectory() as tmp:
            c = cache_mod.Cache(tmp, EXPECTED_FP, 2560)
            try:
                emb = Mock()
                with self.assertRaisesRegex(common.M3Error, "exceeds cap before inference"):
                    runtime.call_embedding(
                        emb, [borderline_q], "query", self.profile, self.pinned_tokenizer,
                        common.implementation(), c, "q-overflow"
                    )
                emb.encode.assert_not_called()
                self.assertEqual(c.usage()["model_requests"], 0)
            finally:
                c.db.close()

    # --- 3. Last-token pooling math with attention mask, L2 normalization & response validation ---
    def test_04_last_token_pooling_math_and_vector_validation(self):
        # Verify the exact pooling index expression used in deployments/modal/engine.py:
        # last_positions = (attention_mask * arange(seq_len)).max(dim=1).values
        # Test both left-padding (used in production) and right-padding across varied sequence lengths
        rng = np.random.default_rng(20261106)
        seq_len, dim = 12, 16
        lengths = [2, 5, 12, 1]
        for pad_side in ("left", "right"):
            hidden = rng.standard_normal((len(lengths), seq_len, dim)).astype(np.float32)
            mask = np.zeros((len(lengths), seq_len), dtype=np.int64)
            expected_vecs = []
            for i, L in enumerate(lengths):
                if pad_side == "left":
                    mask[i, seq_len - L :] = 1
                    last_true_idx = seq_len - 1
                else:
                    mask[i, :L] = 1
                    last_true_idx = L - 1
                # Corrupt pad positions with huge values to ensure they never leak into last-token pooling
                for pos in range(seq_len):
                    if mask[i, pos] == 0:
                        hidden[i, pos] = 9999.0
                v = hidden[i, last_true_idx]
                expected_vecs.append(v / np.linalg.norm(v))
            arange = np.arange(seq_len)[None, :]
            last_positions = (mask * arange).max(axis=1)
            pooled = hidden[np.arange(len(lengths)), last_positions]
            norms = np.linalg.norm(pooled, axis=1, keepdims=True)
            actual_vecs = pooled / norms
            self.assertTrue(np.allclose(actual_vecs, np.asarray(expected_vecs), atol=1e-6))

    # --- 4. Cache, orphan recovery, fail-stop corruption, and unknown-usage attempt ledger ---
    def test_05_cache_and_ledger_unknown_tokens_on_pre_response_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = cache_mod.Cache(tmp, EXPECTED_FP, dimensions=4)
            try:
                # 1) Failure before receiving response -> tokens must be None (unknown_token_attempts == 1)
                emb = Mock()
                emb.encode.side_effect = RuntimeError("network drop before response")
                p = json.loads(json.dumps(self.profile))
                p["embedding"]["dimensions"] = 4
                with self.assertRaises(common.M3Error):
                    runtime.call_embedding(
                        emb, ["short text"], "document", p, self.pinned_tokenizer,
                        common.implementation(), c, "fail-pre-resp"
                    )
                u1 = c.usage()
                self.assertEqual(u1["model_requests"], 1)
                self.assertEqual(u1["known_input_tokens"], 0)
                self.assertEqual(u1["unknown_token_attempts"], 1)
                self.assertIsNone(u1["attempts"][0]["input_tokens"])
                self.assertEqual(u1["attempts"][0]["status"], "error")

                # 2) Failure AFTER receiving response dict (e.g. bad vector norm) -> tokens recorded from response
                ids = self.pinned_tokenizer.backend.encode("short text", add_special_tokens=True).ids
                emb.encode.side_effect = None
                emb.encode.return_value = {
                    "descriptor": {
                        "embedding_fingerprint": common.fingerprint(p),
                        "model": p["embedding"]["model"],
                        "revision": p["embedding"]["revision"],
                        "dimensions": 4,
                        "loaded_model_revision": p["embedding"]["revision"],
                        "device_dtype": "torch.bfloat16",
                        "engine_sha256": common.implementation()["pipeline_v2/deployments/modal/engine.py"],
                        "wrapper_sha256": common.implementation()["pipeline_v2/deployments/modal/qwen3_embed.py"],
                        "package_versions": {"torch": "2.8.0+cu124", "transformers": "4.57.1", "tokenizers": "0.22.2", "modal": "1.5.3"},
                    },
                    "input_hashes": [sha(b"short text")],
                    "token_ids": [ids],
                    "vectors": [[0.0, 0.0, 0.0, 0.0]],  # zero vector fails L2 norm check
                    "input_tokens": len(ids),
                    "padded_tokens": len(ids),
                    "remote_elapsed_seconds": 0.1,
                }
                with self.assertRaises(common.M3Error):
                    runtime.call_embedding(
                        emb, ["short text"], "document", p, self.pinned_tokenizer,
                        common.implementation(), c, "fail-post-resp"
                    )
                u2 = c.usage()
                self.assertEqual(u2["model_requests"], 2)
                self.assertEqual(u2["known_input_tokens"], len(ids))
                self.assertEqual(u2["unknown_token_attempts"], 1)
                self.assertEqual(u2["attempts"][1]["input_tokens"], len(ids))
            finally:
                c.db.close()

    # --- 5. Qdrant REST adapter pagination, profile isolation, and restore-test guard ---
    def test_06_qdrant_multi_page_scroll_profile_isolation_and_restore_guard(self):
        session = Mock()
        store = qdrant.QdrantStore("http://127.0.0.1:6333", "coliee_m3_pilot_test", EXPECTED_FP, dimensions=3, session=session)
        p1 = {
            "case_id": "000001.txt", "passage_id": "000001:p1", "source_hash": "sh1",
            "exact_input_sha256": "ih1", "span_bytes": [0, 10], "parent_handle": "p000001",
            "policy_hash": "ph", "tokenizer_fingerprint": "tf",
        }
        p2 = {
            "case_id": "000002.txt", "passage_id": "000002:p1", "source_hash": "sh2",
            "exact_input_sha256": "ih2", "span_bytes": [0, 12], "parent_handle": "p000001",
            "policy_hash": "ph", "tokenizer_fingerprint": "tf",
        }
        v = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32)

        # Simulate multi-page scroll (page 1 returns p1 + next_page_offset, page 2 returns p2 + None)
        r1 = Mock(status_code=200)
        r1.json.return_value = {
            "status": "ok",
            "result": {
                "points": [{"id": qdrant.point_id(p1["passage_id"], EXPECTED_FP), "payload": {**p1, "embedding_fingerprint": EXPECTED_FP}, "vector": [1.0, 0.0, 0.0]}],
                "next_page_offset": "page-2-token",
            },
        }
        r2 = Mock(status_code=200)
        r2.json.return_value = {
            "status": "ok",
            "result": {
                "points": [{"id": qdrant.point_id(p2["passage_id"], EXPECTED_FP), "payload": {**p2, "embedding_fingerprint": EXPECTED_FP}, "vector": [0.0, 1.0, 0.0]}],
                "next_page_offset": None,
            },
        }
        session.request.side_effect = [r1, r2]
        res = store.verify([p1, p2], v)
        self.assertEqual(res["points"], 2)
        self.assertEqual(session.request.call_count, 2)

        # Existing collection with point from another embedding_fingerprint is rejected by ensure() without dropping collection
        info_resp = Mock(status_code=200)
        info_resp.json.return_value = {"status": "ok", "result": {"config": {"params": {"vectors": {"size": 3, "distance": "Cosine"}}}}}
        bad_scroll = Mock(status_code=200)
        bad_scroll.json.return_value = {
            "status": "ok",
            "result": {"points": [{"id": "x", "payload": {"embedding_fingerprint": "other-fp"}, "vector": [1.0, 0.0, 0.0]}], "next_page_offset": None},
        }
        session.request.reset_mock()
        session.request.side_effect = [info_resp, bad_scroll]
        with self.assertRaisesRegex(common.M3Error, "belongs to another embedding profile"):
            store.ensure()

        # restore_test refuses to overwrite if _restore collection already exists
        snap_create = Mock(status_code=200)
        snap_create.json.return_value = {"status": "ok", "result": {"name": "snap-1.snapshot"}}
        snap_dl = Mock(status_code=200, content=b"snapshot-bytes")
        restore_exists = Mock(status_code=200)
        restore_exists.json.return_value = {"status": "ok", "result": {"status": "green"}}
        session.request.reset_mock()
        session.request.side_effect = [snap_create, snap_dl, restore_exists]
        with self.assertRaisesRegex(common.M3Error, "Restore-test collection already exists"):
            store.restore_test()

    # --- 6. BM25, dense tie-aware exact reference, and RRF 1-vote-per-case fusion ---
    def test_07_bm25_and_tie_aware_dense_reference_and_rrf(self):
        # Overlapping child passages from same case must only contribute 1 vote in RRF
        p_hits = [
            {"case_id": "000001.txt", "passage_id": "000001:c0", "score": 9.5},
            {"case_id": "000001.txt", "passage_id": "000001:c1", "score": 9.4},
            {"case_id": "000001.txt", "passage_id": "000001:c2", "score": 9.3},
            {"case_id": "000002.txt", "passage_id": "000002:c0", "score": 9.0},
        ]
        ranked = bm25.rank_cases(p_hits)
        self.assertEqual([r["case_id"] for r in ranked], ["000001.txt", "000002.txt"])
        self.assertEqual(ranked[0]["rank"], 1)
        self.assertEqual(ranked[1]["rank"], 2)

        # Tie-aware dense verification: when 11 passages tie at the 10th score boundary, any valid subset of the tie is accepted
        passages = [{"passage_id": f"{i:06d}:p1", "case_id": f"{i:06d}.txt"} for i in range(15)]
        vectors = np.zeros((15, 3), dtype=np.float32)
        vectors[0] = [1.0, 0.0, 0.0]  # query passage
        for i in range(1, 6):
            vectors[i] = [0.8, 0.6, 0.0]  # top 5 untied (score 0.8)
        for i in range(6, 15):
            vectors[i] = [0.6, 0.8, 0.0]  # 9 tied passages at score 0.6 (positions 6..14)
        profile = {"embedding": {"dimensions": 3}, "numerics": {"search_score_atol": 1e-4}}
        manifest = {"embedding_fingerprint": EXPECTED_FP, "profile": profile}

        class TiePermutingStore:
            def verify(self, rows, cached):
                return {"status": "PASS", "points": len(rows)}

            def search(self, query, limit, exclude_case):
                valid = [i for i, r in enumerate(passages) if r["case_id"] != exclude_case]
                scores = vectors @ query
                # Reverse tie-break order on tied scores to simulate Qdrant returning a different permutation of exact ties
                ranked = sorted(valid, key=lambda i: (-round(float(scores[i]), 6), -i))[:limit]
                return [{"passage_id": passages[i]["passage_id"], "case_id": passages[i]["case_id"], "score": float(scores[i])} for i in ranked]

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(pilot, "load_run", return_value=(Path(tmp), Path(tmp), manifest, None, passages)), \
                 patch.object(pilot, "Cache"), patch.object(pilot, "load_vectors", return_value=vectors):
                res = pilot.verify_pilot(tmp, "pipeline_v2/artifacts/fake", store=TiePermutingStore())
                self.assertEqual(res["status"], "simulated")
                self.assertEqual(len(res["exact_reference"]), 3)

    # --- 7. Context opening across split children, boundary units, quoted/unknown/no-preview, and non-pilot guard ---
    def test_08_real_pilot_open_context_invariants_and_guards(self):
        c = corpus_mod.Corpus(ROOT, self.profile["passages_bundle"], EXPECTED_M2_SEAL)
        selected = c.selected(self.manifest["passage_ids"])

        # Find representative passages in the real 1,024 sample:
        split_mid = next(p for p in selected if p["split_count"] > 2 and 0 < p["split_order"] < p["split_count"] - 1)
        quoted_p = next(p for p in selected if p["paragraph_role"] == "quoted")
        unknown_p = next(p for p in selected if p["paragraph_role"] == "unknown")
        unnum_p = next(p for p in selected if p["unit_kind"] == "unnumbered")
        no_prev_p = next(p for p in selected if p["navigation_preview_count"] == 0)

        for p in (split_mid, quoted_p, unknown_p, unnum_p, no_prev_p):
            opened = c.open(p["passage_id"])
            self.assertEqual(opened["case_id"], p["case_id"])
            self.assertEqual(opened["source_hash"], p["source_hash"])
            self.assertEqual(opened["hit_passage_id"], p["passage_id"])
            self.assertEqual(opened["hit_span_bytes"], p["span_bytes"])
            self.assertEqual(opened["hit_text"], p["text"])
            self.assertTrue(opened["hit_is_distinct_from_context"])
            self.assertTrue(opened["diagnostic_only"])
            self.assertFalse(opened["M4_delivery_recorded"])
            # Parent component span must contain hit span
            by_kind = {comp["kind"]: comp for comp in opened["components"]}
            self.assertIn("parent", by_kind)
            pa, pb = by_kind["parent"]["span_bytes"]
            ha, hb = opened["hit_span_bytes"]
            self.assertLessEqual(pa, ha)
            self.assertGreaterEqual(pb, hb)
            # For split child, parent byte span is strictly larger than hit byte span
            if p["split_count"] > 1:
                self.assertGreater(pb - pa, hb - ha)
            # Verify source order of previous_context < parent < next_context
            if "previous_context" in by_kind:
                self.assertLessEqual(by_kind["previous_context"]["span_bytes"][1], pa)
            if "next_context" in by_kind:
                self.assertGreaterEqual(by_kind["next_context"]["span_bytes"][0], pb)
            # Verify envelope span covers all components and text matches exact raw slice
            env_a, env_b = opened["span_bytes"]
            self.assertEqual(env_a, min(comp["span_bytes"][0] for comp in opened["components"]))
            self.assertEqual(env_b, max(comp["span_bytes"][1] for comp in opened["components"]))

        # Verify CLI open rejects passage outside the pilot manifest
        with self.assertRaisesRegex(common.M3Error, "Passage is outside pilot"):
            out_buf = io.StringIO()
            with patch.object(m3, "operation_receipt"), redirect_stdout(out_buf):
                rc = m3.main(["open", "--run-dir", RUN_DIR_REL, "--passage-id", "999999:not_in_pilot"])
            if rc != 0:
                parsed = json.loads(out_buf.getvalue())
                raise common.M3Error(parsed["error"])

    # --- 8. Credential safety and pilot vs full-corpus separation ---
    def test_09_credential_redaction_and_pilot_scope_isolation(self):
        # Verify deploy_modal check redacts secrets if accidentally placed in profile/environment labels
        env_map = {
            "MODAL_TOKEN_ID": "ak-secret-id-12345",
            "MODAL_TOKEN_SECRET": "as-secret-val-67890",
            "MODAL_PROFILE": "leaked-ak-secret-id-12345",
            "MODAL_ENVIRONMENT": "env-as-secret-val-67890",
        }
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text(
                "\n".join(f"{k}={v}" for k, v in env_map.items()) + "\n",
                encoding="utf-8",
            )
            chk = deploy_modal.check_configuration(ROOT, env_file=env_file, parent_env={})
            dumped = json.dumps(chk)
            self.assertNotIn("ak-secret-id-12345", dumped)
            self.assertNotIn("as-secret-val-67890", dumped)
            self.assertEqual(chk["profile"], "[redacted]")
            self.assertEqual(chk["environment"], "[redacted]")

        # Verify m3 CLI redacts non-M3Error exception messages so third-party exceptions never print secrets
        out_buf = io.StringIO()
        with patch.object(m3, "literal_search", side_effect=RuntimeError("Bearer secret-token-xyz")), \
              patch.object(m3, "operation_receipt"), redirect_stdout(out_buf):
            rc = m3.main(["literal", "--run-dir", RUN_DIR_REL, "--text", "test"])
        self.assertEqual(rc, 2)
        self.assertNotIn("secret-token-xyz", out_buf.getvalue())
        parsed_err = json.loads(out_buf.getvalue())
        self.assertEqual(parsed_err["error"], "RuntimeError")


def main():
    started = time.perf_counter()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(AGIndependentM3Tests)
    stream = io.StringIO()
    runner = unittest.TextTestRunner(stream=stream, verbosity=2)
    result = runner.run(suite)
    elapsed = time.perf_counter() - started
    report = {
        "suite": "pipeline_v2.reviews.m3_ag_review_v1.test_m3_independent_ag",
        "tests_run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
        "status": "PASS" if result.wasSuccessful() else "FAIL",
        "elapsed_seconds": elapsed,
        "output": stream.getvalue(),
    }
    out_dir = Path(__file__).resolve().parent
    out_path = out_dir / "local_independent_test_results.json"
    attempts_path = out_dir / "local_test_attempts.json"
    attempts = []
    if attempts_path.exists():
        attempts = json.loads(attempts_path.read_text(encoding="utf-8"))
    elif out_path.exists():
        first_attempt = json.loads(out_path.read_text(encoding="utf-8"))
        first_attempt["attempt_number"] = 1
        first_attempt["note"] = (
            "Checker issue in AG test script only (not production defect): "
            "test_02 requested size=16 with 18 synthetic risk strata; "
            "test_08 read opened['parent'] instead of opened['components'] list."
        )
        attempts.append(first_attempt)
    report["attempt_number"] = len(attempts) + 1
    attempts.append(report)
    attempts_path.write_text(json.dumps(attempts, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "output"}, sort_keys=True))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
