"""Independent regression tests for shared readiness and Stage 2 grammar.

Only synthetic inputs are used. No provider, inference, or deployment is called.
"""
from __future__ import annotations

import unittest
import json
import tempfile
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from urllib.request import Request
from urllib.error import HTTPError
from unittest.mock import patch

from knowledge_base.pipeline_v1.au_target_context.grammar import build_grammar
from knowledge_base.pipeline_v1.au_target_context.readiness import ReadinessDeadlineError, ReadinessGate
from knowledge_base.pipeline_v1.au_target_context import recovery, runner
from knowledge_base.pipeline_v1.au_target_context import kos_aligned as kos


def _terminal(value):
    import json
    return json.dumps(json.dumps(value))


def _stage2_job(anchors=None):
    if anchors is None:
        anchors = [{"anchor_id": "locked-a"}, {"anchor_id": "locked-b"}]
    return {"stage": 2, "request_id": "request-fixture", "target_id": "target-fixture",
            "locked_anchors": anchors,
            "catalog": {"context_refs": {"context-a": {"ref_id": "context-a"}}}}


class Stage2CrossFieldGrammarTests(unittest.TestCase):
    def test_complete_requires_all_locked_anchors_resolved(self):
        grammar = build_grammar(_stage2_job())
        root = next(line for line in grammar.splitlines() if line.startswith("root ::= "))
        complete = next(part for part in root.split(" | ") if _terminal("complete") in part)
        self.assertIn("anchors-complete", complete)
        resolved = next(line for line in grammar.splitlines()
                        if line.startswith("anchors-complete ::= "))
        self.assertIn("locked-0-keep", resolved)
        self.assertIn("locked-0-reject", resolved)
        self.assertIn("locked-1-keep", resolved)
        self.assertIn("locked-1-reject", resolved)
        self.assertNotIn("-unresolved", resolved)

    def test_global_unresolved_requires_an_unresolved_anchor_when_anchors_exist(self):
        grammar = build_grammar(_stage2_job())
        root = next(line for line in grammar.splitlines() if line.startswith("root ::= "))
        unresolved = next(part for part in root.split(" | ") if _terminal("unresolved") in part)
        self.assertIn("anchors-unresolved", unresolved)
        unresolved_rule = next(line for line in grammar.splitlines()
                               if line.startswith("anchors-unresolved ::= "))
        alternatives = unresolved_rule.split(" ::= ", 1)[1].split(" | ")
        self.assertTrue(alternatives)
        for choice in alternatives:
            self.assertIn("-unresolved", choice,
                          "each global unresolved branch must leave at least one anchor unresolved")

    def test_global_revisit_may_preserve_resolved_locked_anchor_decisions(self):
        grammar = build_grammar(_stage2_job())
        root = next(line for line in grammar.splitlines() if line.startswith("root ::= "))
        revisit = next(part for part in root.split(" | ") if _terminal("revisit_target") in part)
        self.assertIn("anchors-revisit_target", revisit)
        self.assertIn("locked-0", next(line for line in grammar.splitlines()
                                       if line.startswith("anchors ::= ")))

    def test_empty_stage2_job_cannot_claim_complete(self):
        job = _stage2_job(anchors=[])
        grammar = build_grammar(job)
        root = next(line for line in grammar.splitlines() if line.startswith("root ::= "))
        self.assertNotIn(_terminal("complete"), root)
        self.assertIn(_terminal("unresolved"), root)
        self.assertIn(_terminal("revisit_target"), root)
        unresolved = next(line for line in grammar.splitlines()
                          if line.startswith("anchors-unresolved ::= "))
        self.assertEqual(unresolved.split(" ::= ", 1)[1], '"[]"')


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def _prepare_current_workload(root):
    old_root = Path(__file__).resolve().parents[1] / "knowledge_base/pipeline_v1/outputs/kos_same_source_20261018_ready"
    old = json.loads((old_root / "input/workload.json").read_text(encoding="utf-8"))
    ledger = json.loads((old_root / "live/runtime_ledger.json").read_text(encoding="utf-8"))
    cfg = recovery._cfg_from_binding(old, ledger["binding"])
    workload = kos.prepare(root / "input", kos_root=old["kos_root"],
                           selected_kos_manifest=old["selected_kos_manifest"],
                           source_store=old["source_store"], atom_root=old["atom_root"],
                           parent=old["parent_workload"], cfg=cfg)
    return workload, cfg, root / "input/workload.json"


class SharedReadinessGateTests(unittest.TestCase):
    def test_timeout_persists_finite_diagnostic_and_blocks_future_dispatch(self):
        clock = _Clock()
        persisted, calls = [], []

        def unavailable(request, **_kwargs):
            calls.append(request.get_method())
            raise HTTPError(request.full_url, 503, "unavailable", {},
                            BytesIO(b'{"error":"secret provider body"}'))

        gate = ReadinessGate({"jobs_url": "https://fixture.invalid/jobs", "token": "fixture",
                              "readiness_seconds": 4, "retrieval_readiness_seconds": 2,
                              "job_poll_seconds": 2}, unavailable, clock, clock.sleep, persisted.append)
        gate.warmup(True)

        state = gate.snapshot()
        self.assertEqual(state["status"], "deadline_exhausted")
        self.assertEqual(state["http_status"], 503)
        self.assertEqual(state["error_class"], "ReadinessDeadlineError")
        self.assertEqual(state["count"], state["warmup_count"])
        self.assertLessEqual(state["elapsed_ms"], 4000)
        self.assertNotIn("secret provider body", repr(state))
        self.assertTrue(persisted)
        dispatched = []
        shared = SimpleNamespace(readiness=gate,
                                 dispatch=lambda req, proof=None, **kwargs: dispatched.append(req))
        for _worker in range(2):
            worker = runner.JobAccounting(shared)
            with self.assertRaises(ReadinessDeadlineError):
                worker(Request("https://fixture.invalid/jobs", method="POST", data=b"{}"))
        self.assertEqual(dispatched, [], "stopped shared readiness must prevent worker POST dispatch")
        self.assertEqual(calls, ["GET", "GET"])

    def test_fully_verified_resume_skips_health_warmup(self):
        calls = []

        def forbidden(request, **_kwargs):
            calls.append((request.get_method(), request.full_url))
            raise AssertionError("readiness must not poll for an all-terminal resume")

        clock = _Clock()
        gate = ReadinessGate({"jobs_url": "https://fixture.invalid/jobs", "token": "fixture"},
                             forbidden, clock, clock.sleep, lambda _snapshot: None)
        gate.warmup(False)
        self.assertEqual(gate.snapshot()["status"], "not_needed")
        self.assertEqual(calls, [])

    def test_runner_shared_timeout_blocks_all_worker_posts_and_persists_diagnostics(self):
        with tempfile.TemporaryDirectory(prefix="au-runner-readiness-timeout-") as temp:
            base = Path(temp)
            workload, cfg, workload_path = _prepare_current_workload(base / "prepared")
            target_ids = [row["target_id"] for row in workload["rows"][:2]]
            cfg.update(token="local-fixture", readiness_seconds=4,
                       retrieval_readiness_seconds=2, job_poll_seconds=2)
            clock, calls = _Clock(), []

            def unavailable(request, **_kwargs):
                calls.append((request.get_method(), request.full_url))
                raise HTTPError(request.full_url, 503, "fixture unavailable", {},
                                BytesIO(b'{"error":"must not be persisted"}'))

            report = runner.run(workload_path, output_root=base / "live", cfg=cfg,
                                execute=True, concurrency=2, target_ids=target_ids,
                                opener=unavailable, clock=clock, sleep=clock.sleep)
            ledger = json.loads((base / "live/runtime_ledger.json").read_text(encoding="utf-8"))
            diagnostic = json.loads((base / "live/readiness.json").read_text(encoding="utf-8"))
            self.assertEqual(report["protocol_counts"]["pending"], 2)
            self.assertEqual(ledger["provider_attempts"], 0)
            self.assertEqual(ledger["attempts"], [])
            self.assertEqual([method for method, _ in calls], ["GET", "GET"])
            self.assertTrue(all(url.endswith("/health") for _, url in calls))
            self.assertEqual(diagnostic["status"], "deadline_exhausted")
            self.assertEqual(diagnostic["http_status"], 503)
            self.assertEqual(diagnostic["error_class"], "ReadinessDeadlineError")
            self.assertLessEqual(diagnostic["elapsed_ms"], 4000)
            self.assertNotIn("must not be persisted", repr(diagnostic))

    def test_runner_all_verified_mock_resume_skips_health_and_new_posts(self):
        with tempfile.TemporaryDirectory(prefix="au-runner-cache-resume-") as temp:
            base = Path(temp)
            workload, cfg, workload_path = _prepare_current_workload(base / "prepared")
            target_ids = [workload["rows"][0]["target_id"]]
            live = base / "live"
            first = runner.run(workload_path, output_root=live, cfg=cfg, mock=True,
                               concurrency=1, target_ids=target_ids)
            first_ledger = json.loads((live / "runtime_ledger.json").read_text(encoding="utf-8"))
            before = (first_ledger["provider_attempts"], first_ledger["get_polls"],
                      first_ledger["reserved_input_tokens"], first_ledger["reserved_output_tokens"])
            self.assertEqual(first["status"], "complete")
            self.assertEqual(set(e["status"] for e in first_ledger["jobs"].values()), {"verified"})

            calls = []
            real_gate = runner.ReadinessGate

            class ObservedGate(real_gate):
                def warmup(self, needed):
                    calls.append(needed)
                    return super().warmup(needed)

            with patch.object(runner, "ReadinessGate", ObservedGate):
                second = runner.run(workload_path, output_root=live, cfg=cfg, mock=True,
                                    concurrency=1, target_ids=target_ids)
            after_ledger = json.loads((live / "runtime_ledger.json").read_text(encoding="utf-8"))
            after = (after_ledger["provider_attempts"], after_ledger["get_polls"],
                     after_ledger["reserved_input_tokens"], after_ledger["reserved_output_tokens"])
            diagnostic = json.loads((live / "readiness.json").read_text(encoding="utf-8"))
            self.assertEqual(second["status"], "complete")
            self.assertEqual(calls, [False])
            self.assertEqual(diagnostic["status"], "not_needed")
            self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
