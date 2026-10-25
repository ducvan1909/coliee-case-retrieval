"""Independent offline tests for plan22 once its public API is finalized.

Fixtures here deliberately use synthetic source text and atom maps. They do not
use KOS/AU/gold labels and never open a provider connection.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import tempfile
import unittest
from copy import deepcopy
from contextlib import redirect_stdout
from pathlib import Path


def _sha(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _write_json(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return path


class PairedFixture:
    """Minimal source/block/atom fixture with boundary and padding edge cases."""

    def __init__(self, root: Path):
        self.root = root
        self.source = (
            'Opening context says "quoted\\ntext" & <tag>. '
            "TARGET begins here: A court may act only if condition X applies. "
            "The court must record reasons. TARGET ends here. "
            "Closing context says a party alleged condition Y."
        )
        self.source_hash = _sha(self.source)
        self.target_start = self.source.index("TARGET begins here:")
        self.target_end = self.source.index(" TARGET ends here.") + len(" TARGET ends here.")
        self.case_id = "fixture-case-01"
        self.region_id = "fixture-region-01"
        self.target_id = "fixture-target-01"

        # An atom deliberately crosses the target start. Catalog construction
        # must preserve the full atom while its non-target portion stays padding.
        self.atoms = [
            self._atom("atom-opening-crossing", 0, self.source.index("TARGET begins here:") + 8),
            self._atom("atom-target-core", self.source.index("TARGET begins here:") + 8, self.target_end),
            self._atom("atom-closing", self.target_end, len(self.source)),
        ]
        self.blocks = [
            {"block_id": "block-before", "span": {"start_char": 0, "end_char": self.target_start}},
            {"block_id": "block-target", "span": {"start_char": self.target_start, "end_char": self.target_end}},
            {"block_id": "block-after", "span": {"start_char": self.target_end, "end_char": len(self.source)}},
        ]
        self.target = {
            "target_id": self.target_id,
            "span": {"start_char": self.target_start, "end_char": self.target_end},
            "text": self.source[self.target_start:self.target_end],
            "source_hash": self.source_hash,
        }

    def _atom(self, atom_id: str, start: int, end: int) -> dict:
        return {
            "atom_id": atom_id,
            "case_id": self.case_id,
            "source_hash": self.source_hash,
            "span": {"start_char": start, "end_char": end},
            "text": self.source[start:end],
        }

    def baseline_refs(self) -> list[dict]:
        # Both fixtures keep the same TARGET. G has no added source context.
        return [{"role": "target", **self.target["span"].copy(), "target_ids": [self.target_id]}]

    def selective_refs(self) -> list[dict]:
        # Two overlapping context spans exercise union/deduplication while
        # retaining the full source around TARGET.
        return [
            {"role": "target", **self.target["span"].copy(), "target_ids": [self.target_id]},
            {"role": "context", "start_char": 0, "end_char": self.target_start + 4},
            {"role": "context", "start_char": self.target_end - 3, "end_char": len(self.source)},
        ]

    def source_store(self) -> dict:
        return {
            "artifact_type": "SyntheticSourceStore",
            "schema_version": "fixture-v1",
            "cases": [{
                "case_id": self.case_id,
                "source_hash": self.source_hash,
                "text": self.source,
            }],
        }

    def atom_artifact(self) -> dict:
        return {
            "case_id": self.case_id,
            "source_hash": self.source_hash,
            "atoms": self.atoms,
        }

    def logical_pair(self, *, identical: bool = False) -> dict:
        return {
            "pair_id": "fixture-pair-01",
            "case_id": self.case_id,
            "source_hash": self.source_hash,
            "target": self.target,
            "arms": {
                "G": {"refs": self.baseline_refs(), "messages": [{"role": "user", "content": "same"}]},
                "S": {
                    "refs": self.baseline_refs() if identical else self.selective_refs(),
                    "messages": [{"role": "user", "content": "same" if identical else "added context"}],
                },
            },
        }


class PairedFixtureTests(unittest.TestCase):
    def test_fixture_has_stable_target_and_boundary_padding_cases(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = PairedFixture(Path(folder))
            self.assertEqual(fixture.source_hash, _sha(fixture.source))
            self.assertEqual(
                fixture.target["text"],
                fixture.source[fixture.target_start:fixture.target_end],
            )
            crossing = fixture.atoms[0]
            self.assertLess(crossing["span"]["start_char"], fixture.target_start)
            self.assertGreater(crossing["span"]["end_char"], fixture.target_start)
            self.assertIn('"quoted\\ntext" & <tag>', fixture.source)

    def test_fixture_distinguishes_shared_payload_from_context_delta(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = PairedFixture(Path(folder))
            same = fixture.logical_pair(identical=True)
            changed = fixture.logical_pair()
            self.assertEqual(same["arms"]["G"]["messages"], same["arms"]["S"]["messages"])
            self.assertNotEqual(changed["arms"]["G"]["messages"], changed["arms"]["S"]["messages"])
            self.assertEqual(same["target"], changed["target"])


def _sampling_rows(cases=("case-a", "case-b")):
    rows = []
    for case_index, case_id in enumerate(cases):
        for index in range(12):
            counts = {
                "reporting": int(index % 6 == 2),
                "quote": int(index % 6 == 2),
                "speaker_voice": int(index % 6 == 2),
                "qualification": int(index % 6 == 3),
                "rebuttal": int(index % 6 == 3),
                "citation": int(index % 6 == 4),
            }
            rows.append({
                "case_id": case_id,
                "region_id": f"{case_id}-region-{index:02d}",
                "features": {
                    "lane_scores": {"doctrine": int(index % 6 == 0), "application": int(index % 6 == 1)},
                    "counts": counts,
                },
                "position_stratum": index % 3,
                "target_chars": 1601 if index % 6 == 5 else 500 + case_index,
            })
    return rows


class SourceOnlyControlSelectionTests(unittest.TestCase):
    def test_control_sample_is_deterministic_unique_per_case_and_excludes_changed(self):
        from knowledge_base.pipeline_v1.au_context_paired.build import select_controls

        rows = _sampling_rows()
        changed = {"case-a-region-00", "case-b-region-00"}
        first = select_controls(rows, changed)
        second = select_controls(rows, changed)
        self.assertEqual(first, second)
        for case_id in ("case-a", "case-b"):
            selected = [(rid, stratum) for rid, stratum, _ in first if rid.startswith(case_id)]
            self.assertEqual(len(selected), 6)
            self.assertEqual(len({rid for rid, _ in selected}), 6)
            self.assertEqual({stratum for _, stratum in selected}, {
                "legal_rule", "application", "reporting", "qualification", "no_citation", "middle_tail_long"
            })
        self.assertFalse(changed.intersection(rid for rid, _, _ in first))

    def test_control_selection_fails_when_a_case_cannot_supply_six_unique_targets(self):
        from knowledge_base.pipeline_v1.au_context_paired.build import PairedError, select_controls

        with self.assertRaisesRegex(PairedError, "insufficient distinct controls"):
            select_controls(_sampling_rows(cases=("small-case",))[:5], set())


class CompactCatalogRenderingFixtureTests(unittest.TestCase):
    def test_crossing_atom_is_whole_with_padding_and_target_markup_and_overlap_dedupes(self):
        from unittest.mock import patch
        from knowledge_base.pipeline_v1.au_compact.core import build_evidence_catalog
        from knowledge_base.pipeline_v1.au_compact.runner import _render

        with tempfile.TemporaryDirectory() as folder:
            fixture = PairedFixture(Path(folder))
            request = {
                "case_id": fixture.case_id,
                "source_hash": fixture.source_hash,
                "request_id": "fixture-request",
                "expected_target_ids": [fixture.target_id],
                "source_refs": fixture.selective_refs(),
                "atom_binding": {"case_id": fixture.case_id, "source_hash": fixture.source_hash},
                "hint_payload": {"version": "context-hint-payload-v1", "hint_ids": []},
            }
            atom_map = fixture.atom_artifact()
            with patch("knowledge_base.pipeline_v1.au_compact.core.resolve_atom_binding",
                       return_value=atom_map):
                catalog = build_evidence_catalog(request, request["atom_binding"], fixture.source)
                rendered = _render(request, catalog)
            self.assertEqual(len(catalog["atoms"]), 3)
            self.assertEqual(len(set(catalog["atoms"])), 3)
            self.assertTrue(catalog["atoms"]["atom-opening-crossing"]["target_intersecting"])
            self.assertTrue(catalog["atoms"]["atom-target-core"]["target_intersecting"])
            self.assertFalse(catalog["atoms"]["atom-closing"]["target_intersecting"])
            self.assertIn(
                f"<CONTEXT_PADDING span=0:{fixture.target_start}>", rendered
            )
            target_chunks = [tuple(map(int, match)) for match in re.findall(
                r"<TARGET_BODY span=(\d+):(\d+)>", rendered
            )]
            self.assertEqual(target_chunks, [
                (fixture.target_start, fixture.atoms[0]["span"]["end_char"]),
                (fixture.atoms[1]["span"]["start_char"], fixture.target_end),
            ])
            self.assertEqual(target_chunks[0][0], fixture.target_start)
            self.assertEqual(target_chunks[0][1], target_chunks[1][0])
            self.assertEqual(target_chunks[-1][1], fixture.target_end)
            self.assertIn("&amp; &lt;tag&gt;", rendered)
            self.assertIn("<CONTEXT atom_id=atom-closing", rendered)
            self.assertNotIn("<TARGET_BODY", rendered.split("<CONTEXT atom_id=atom-closing", 1)[1])


class ReviewEvidenceValidationTests(unittest.TestCase):
    def test_decision_validator_rejects_malformed_or_out_of_source_evidence(self):
        from knowledge_base.pipeline_v1.au_context_paired.build import PairedError
        from knowledge_base.pipeline_v1.au_context_paired.review import validate_decisions
        from unittest.mock import patch

        source = "a synthetic source quote"
        packet = {"packet_sha256": "packet-lock", "semantic_gold": False,
                  "source_store": "fixture-source-store",
                  "rows": [{"blind_id": "blind-1", "source_atoms": [
                      {"start_char": 0, "end_char": len(source), "quote": source}
                  ], "case_id": "fixture-case", "source_hash": "fixture-hash"}]}
        valid_shape = {"packet_sha256": "packet-lock", "semantic_gold": False, "rows": [{
            "blind_id": "blind-1", "verdict": "supported", "severity": "none",
            "reviewer": "reviewer-1", "errors": [],
            "evidence_spans": [{"start_char": 1, "end_char": 5, "quote": source[1:5]}],
            "explanation": "Evidence is within the source atom.",
        }]}
        with patch("knowledge_base.pipeline_v1.au_context_paired.review.open_source", return_value=source):
            self.assertIs(validate_decisions(valid_shape, packet), valid_shape)

        malformed = deepcopy(valid_shape)
        malformed["rows"][0]["verdict"] = "gold"
        with patch("knowledge_base.pipeline_v1.au_context_paired.review.open_source", return_value=source):
            with self.assertRaisesRegex(PairedError, "invalid semantic verdict"):
                validate_decisions(malformed, packet)

        impossible = deepcopy(valid_shape)
        impossible["rows"][0]["evidence_spans"] = [
            {"start_char": len(source), "end_char": len(source) + 1, "quote": "x"}
        ]
        with patch("knowledge_base.pipeline_v1.au_context_paired.review.open_source", return_value=source):
            with self.assertRaisesRegex(PairedError, "invalid review evidence span"):
                validate_decisions(impossible, packet)

        wrong_quote = deepcopy(valid_shape)
        wrong_quote["rows"][0]["evidence_spans"][0]["quote"] = "tampered"
        with patch("knowledge_base.pipeline_v1.au_context_paired.review.open_source", return_value=source):
            with self.assertRaisesRegex(PairedError, "quote differs from immutable source"):
                validate_decisions(wrong_quote, packet)


class OfflineCliTests(unittest.TestCase):
    def test_fresh_cli_preflight_writes_offline_report_without_environment_or_network(self):
        from unittest.mock import patch
        from knowledge_base.pipeline_v1.au_context_paired import __main__ as cli

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            workload_path = _write_json(root / "workload.json", {"synthetic": "locked"})
            output = root / "fresh-preflight"
            fake_cfg = {"model": "fixture", "url": "https://fixture.invalid", "token": "ignored"}
            fake_budget = {"max_requests": 1}
            stdout = io.StringIO()
            with patch.object(cli, "study_config", return_value=(fake_cfg, fake_budget, {})), \
                 patch.object(cli, "preflight", return_value={"status": "pass", "failures": [],
                                                              "network_requests": 0,
                                                              "semantic_quality": "not_assessed"}) as check, \
                 redirect_stdout(stdout):
                code = cli.main(["preflight", "--output-root", str(output),
                                 "--workload", str(workload_path),
                                 "--source-store", str(root / "source"),
                                 "--atom-root", str(root / "atoms")])
            self.assertEqual(code, 0)
            check.assert_called_once()
            saved = json.loads((output / "preflight.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["status"], "pass")
            self.assertIn("PAIRED PREFLIGHT PASS", stdout.getvalue())
            self.assertFalse(any(output.rglob("*.env")))

    def test_cli_requires_locked_reference_before_execute(self):
        from unittest.mock import patch
        from knowledge_base.pipeline_v1.au_context_paired import __main__ as cli

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            workload = _write_json(root / "workload.json", {"synthetic": "locked"})
            cfg = {"model": "fixture", "url": "https://fixture.invalid", "token": "ignored"}
            stdout = io.StringIO()
            with patch.object(cli, "study_config", return_value=(cfg, {}, {})), \
                 patch("knowledge_base.pipeline_v1.au_context_paired.runner.run") as execute, \
                 redirect_stdout(stdout):
                code = cli.main(["run", "--execute", "--workload", str(workload),
                                 "--output-root", str(root / "run")])
            self.assertEqual(code, 2)
            execute.assert_not_called()
            self.assertIn("--reference-checklist required", stdout.getvalue())

    def test_cli_run_report_is_current_after_resume(self):
        from unittest.mock import patch
        from knowledge_base.pipeline_v1.au_context_paired import __main__ as cli

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            workload = _write_json(root / "workload.json", {"synthetic": "locked"})
            output = root / "run-output"
            cfg = {"model": "fixture", "url": "https://fixture.invalid", "token": "ignored"}
            responses = [{"status": "incomplete", "generation": 1},
                         {"status": "incomplete", "generation": 2}]
            stdout = io.StringIO()
            with patch.object(cli, "study_config", return_value=(cfg, {}, {})), \
                 patch("knowledge_base.pipeline_v1.au_context_paired.runner.run",
                       side_effect=responses), redirect_stdout(stdout):
                first = cli.main(["run", "--workload", str(workload), "--output-root", str(output)])
                second = cli.main(["run", "--workload", str(workload), "--output-root", str(output)])
            self.assertEqual((first, second), (3, 3))
            canonical = json.loads((output / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(canonical["generation"], 2)


class RunnerAccountingTests(unittest.TestCase):
    def test_job_id_binds_payload_while_local_request_key_binds_endpoint_config(self):
        from urllib.request import Request
        from knowledge_base.pipeline_v1.au_compact import runner as compact
        from knowledge_base.pipeline_v1.au_compact.jobs_client import payload_digest
        from knowledge_base.pipeline_v1.au_context_paired.runner import _Accounting, PairedRunError

        payload = {"model": "fixture", "messages": [{"role": "user", "content": "same payload"}],
                   "max_tokens": 8}
        cfg_a = {"url": "https://fixture-a.invalid/v1", "jobs_url": "https://fixture-a.invalid/jobs",
                 "model": "fixture", "enable_thinking": False, "transport": "jobs",
                 "string_decoder": "host_validated"}
        cfg_b = {**cfg_a, "url": "https://fixture-b.invalid/v1",
                 "jobs_url": "https://fixture-b.invalid/jobs"}
        request = {"request_id": "identity-fixture", "case_id": "fixture-case",
                   "source_hash": "source-hash", "expected_target_ids": ["target"],
                   "atom_binding": {
                       "atom_map_relative_path": "atoms.json", "atom_map_sha256": "atom-hash",
                       "atom_map_cache_key": "cache-key", "case_id": "fixture-case",
                       "source_hash": "source-hash", "segmenter_version": "segmenter-v1",
                       "policy_sha256": "policy-hash",
                   }}
        job_a, job_b = payload_digest(payload), payload_digest(payload)
        self.assertEqual(job_a, job_b)
        self.assertNotEqual(compact._key(request, "workload", cfg_a),
                            compact._key(request, "workload", cfg_b))

        with tempfile.TemporaryDirectory() as folder:
            ledger = {"provider_attempts": 0, "get_polls": 0, "warmup_attempts": 0,
                      "probe_attempts": 0, "reserved_input_tokens": 0,
                      "reserved_output_tokens": 0, "attempts": []}
            counted = _Accounting(Path(folder), ledger,
                                  {"max_provider_attempts": 2, "max_total_input_tokens": 1000,
                                   "max_total_output_tokens": 100},
                                  lambda *args, **kwargs: self.fail("invalid identity reached opener"))
            wrong = {"job_id": "incorrect-job-id", "payload": payload}
            req = Request(cfg_a["jobs_url"], data=json.dumps(wrong).encode(), method="POST")
            with self.assertRaisesRegex(PairedRunError, "payload identity mismatch"):
                counted(req)
            self.assertEqual(ledger["provider_attempts"], 0)
            self.assertEqual(ledger["reserved_output_tokens"], 0)

    def test_post_caps_count_warmup_probe_and_extraction_together(self):
        from urllib.request import Request
        from knowledge_base.pipeline_v1.au_compact.jobs_client import payload_digest
        from knowledge_base.pipeline_v1.au_context_paired.runner import _Accounting, _Response, PairedRunError

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            ledger = {"provider_attempts": 0, "get_polls": 0, "warmup_attempts": 0,
                      "probe_attempts": 0, "reserved_input_tokens": 0,
                      "reserved_output_tokens": 0, "attempts": []}
            budget = {"max_provider_attempts": 3, "max_total_input_tokens": 1000,
                      "max_total_output_tokens": 12}
            calls = []

            def opener(req, **kwargs):
                calls.append(req.get_method())
                saved = json.loads((root / "runtime_ledger.json").read_text(encoding="utf-8"))
                self.assertEqual(saved["provider_attempts"], len(calls))
                self.assertEqual(saved["attempts"][-1]["reserved_output_tokens"], 4)
                return _Response(b'{"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}')

            counted = _Accounting(root, ledger, budget, opener)
            for phase in ("warmup", "probe", "extraction"):
                counted.phase = phase
                payload = {"model": "fixture", "messages": [{"role": "user", "content": phase}],
                           "max_tokens": 4}
                body = {"job_id": payload_digest(payload), "payload": payload}
                req = Request("https://fixture.invalid/jobs", data=json.dumps(body).encode(),
                              headers={"Content-Type": "application/json",
                                       "Authorization": "Bearer ACCOUNTING_TEST_SECRET"}, method="POST")
                with counted(req) as response:
                    json.loads(response.read())

            counted.phase = "extraction"
            payload = {"model": "fixture", "messages": [{"role": "user", "content": "over cap"}],
                       "max_tokens": 1}
            body = {"job_id": payload_digest(payload), "payload": payload}
            req = Request("https://fixture.invalid/jobs", data=json.dumps(body).encode(), method="POST")
            with self.assertRaisesRegex(PairedRunError, "budget exhausted"):
                counted(req)

            self.assertEqual(calls, ["POST", "POST", "POST"])
            self.assertEqual(ledger["provider_attempts"], 3)
            self.assertEqual([a["phase"] for a in ledger["attempts"]],
                             ["warmup", "probe", "extraction"])
            self.assertEqual((ledger["warmup_attempts"], ledger["probe_attempts"]), (1, 1))
            self.assertEqual(ledger["reserved_output_tokens"], 12)
            serialized = "".join(path.read_text(encoding="utf-8") for path in root.rglob("*.json"))
            self.assertNotIn("ACCOUNTING_TEST_SECRET", serialized)

    def test_ambiguous_http_503_or_timeout_never_resubmits_same_job(self):
        from urllib.error import HTTPError
        from urllib.request import Request
        from knowledge_base.pipeline_v1.au_compact.jobs_client import payload_digest
        from knowledge_base.pipeline_v1.au_context_paired.runner import _Accounting, PairedRunError

        for failure_kind in ("plain_503", "timeout"):
            with self.subTest(failure_kind=failure_kind), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                ledger = {"provider_attempts": 0, "get_polls": 0, "warmup_attempts": 0,
                          "probe_attempts": 0, "reserved_input_tokens": 0,
                          "reserved_output_tokens": 0, "attempts": []}
                budget = {"max_provider_attempts": 4, "max_total_input_tokens": 1000,
                          "max_total_output_tokens": 100}
                payload = {"model": "fixture", "messages": [{"role": "user", "content": "uncertain"}],
                           "max_tokens": 5}
                wire = {"job_id": payload_digest(payload), "payload": payload}
                req = Request("https://fixture.invalid/jobs", data=json.dumps(wire).encode(), method="POST")
                calls = []

                def first_opener(request, **kwargs):
                    calls.append(request.get_method())
                    if failure_kind == "plain_503":
                        raise HTTPError(request.full_url, 503, "unclassified", {}, io.BytesIO(b'{"error":"busy"}'))
                    raise TimeoutError("ambiguous timeout")

                first = _Accounting(root, ledger, budget, first_opener)
                with self.assertRaises((HTTPError, TimeoutError)):
                    first(req)
                persisted = json.loads((root / "runtime_ledger.json").read_text(encoding="utf-8"))
                self.assertEqual(persisted["provider_attempts"], 1)
                self.assertEqual(persisted["reserved_output_tokens"], 5)
                self.assertFalse(persisted["attempts"][0].get("provably_not_accepted", False))

                resumed = _Accounting(root, persisted, budget,
                                       lambda request, **kwargs: calls.append(request.get_method()))
                with self.assertRaisesRegex(PairedRunError, "acknowledgement uncertain"):
                    resumed(req)
                self.assertEqual(calls, ["POST"])

    def test_explicit_nonacceptance_503_still_requires_authoritative_recovery_proof(self):
        from urllib.error import HTTPError
        from urllib.request import Request
        from knowledge_base.pipeline_v1.au_compact.jobs_client import payload_digest
        from knowledge_base.pipeline_v1.au_context_paired.runner import _Accounting, _Response, PairedRunError

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            ledger = {"provider_attempts": 0, "get_polls": 0, "warmup_attempts": 0,
                      "probe_attempts": 0, "reserved_input_tokens": 0,
                      "reserved_output_tokens": 0, "attempts": []}
            budget = {"max_provider_attempts": 4, "max_total_input_tokens": 1000,
                      "max_total_output_tokens": 100}
            payload = {"model": "fixture", "messages": [{"role": "user", "content": "retry"}],
                       "max_tokens": 5}
            wire = {"job_id": payload_digest(payload), "payload": payload}
            req = Request("https://fixture.invalid/jobs", data=json.dumps(wire).encode(), method="POST")
            calls = []

            def opener(request, **kwargs):
                calls.append(request.get_method())
                if len(calls) == 1:
                    body = b'{"accepted":false,"error":"provider_unavailable"}'
                    raise HTTPError(request.full_url, 503, "rejected", {}, io.BytesIO(body))
                return _Response(b'{"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}')

            first = _Accounting(root, ledger, budget, opener)
            with self.assertRaises(HTTPError):
                first(req)
            persisted = json.loads((root / "runtime_ledger.json").read_text(encoding="utf-8"))
            self.assertTrue(persisted["attempts"][0]["provably_not_accepted"])

            resumed = _Accounting(root, persisted, budget, opener)
            # The 503 diagnostic alone does not authorize a second POST. A
            # retry needs two fresh, spaced Unknown-job observations with
            # health readiness evidence, bound to this exact job and gateway.
            with self.assertRaisesRegex(PairedRunError, "acknowledgement uncertain"):
                resumed(req)
            self.assertEqual(calls, ["POST"])
            job_id = wire["job_id"]
            job_url = req.full_url.rstrip("/") + "/" + job_id
            resumed.recovery_proof = {
                "job_id": job_id,
                "gateway_url": req.full_url.rstrip("/"),
                "backoff_seconds": 1,
                "observations": [
                    {"job_url": job_url, "http_status": 404, "detail": "Unknown job",
                     "health": {"ready": True}, "observed_monotonic": 10.0},
                    {"job_url": job_url, "http_status": 404, "detail": "Unknown job",
                     "health": {"ready": True}, "observed_monotonic": 11.0},
                ],
            }
            with resumed(req) as response:
                json.loads(response.read())
            self.assertEqual(calls, ["POST", "POST"])
            self.assertEqual(resumed.ledger["provider_attempts"], 2)
            self.assertEqual([row.get("provably_not_accepted", False) for row in resumed.ledger["attempts"]],
                             [True, False])
            with self.assertRaisesRegex(PairedRunError, "acknowledgement uncertain"):
                resumed(req)

    def test_provider_warmup_and_probe_caps_survive_accounting_reinstantiation(self):
        from urllib.request import Request
        from knowledge_base.pipeline_v1.au_compact.jobs_client import payload_digest
        from knowledge_base.pipeline_v1.au_context_paired.runner import _Accounting, PairedRunError

        for phase, cap, counter, provider_count, expected in (
                ("extraction", 100, "provider_attempts", 100, "budget exhausted"),
                ("warmup", 50, "warmup_attempts", 50, "warmup attempt cap exhausted"),
                ("probe", 2, "probe_attempts", 2, "decoder probe cap exhausted")):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                ledger = {"provider_attempts": provider_count, "get_polls": 0,
                          "warmup_attempts": cap if phase == "warmup" else 0,
                          "probe_attempts": cap if phase == "probe" else 0,
                          "reserved_input_tokens": 0, "reserved_output_tokens": 0,
                          "attempts": [{"job_id": f"prior-{i}"} for i in range(provider_count)]}
                _write_json(root / "runtime_ledger.json", ledger)
                restored = json.loads((root / "runtime_ledger.json").read_text(encoding="utf-8"))
                budget = {"max_provider_attempts": 200, "max_total_input_tokens": 1000,
                          "max_total_output_tokens": 1000}
                payload = {"model": "fixture", "messages": [{"role": "user", "content": phase}],
                           "max_tokens": 1}
                wire = {"job_id": payload_digest(payload), "payload": payload}
                req = Request("https://fixture.invalid/jobs", data=json.dumps(wire).encode(), method="POST")
                opener_calls = []
                counted = _Accounting(root, restored, budget,
                                      lambda *args, **kwargs: opener_calls.append(True))
                counted.phase = phase
                with self.assertRaisesRegex(PairedRunError, expected):
                    counted(req)
                self.assertEqual(opener_calls, [])

    def test_lost_ack_resume_polls_same_job_without_new_post_or_billing_reservation(self):
        from urllib.error import HTTPError
        from urllib.request import Request
        from knowledge_base.pipeline_v1.au_compact.jobs_client import complete_job, payload_digest
        from knowledge_base.pipeline_v1.au_context_paired.runner import _Accounting, _Response

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            ledger = {"provider_attempts": 0, "get_polls": 0, "warmup_attempts": 0,
                      "probe_attempts": 0, "reserved_input_tokens": 0,
                      "reserved_output_tokens": 0, "attempts": []}
            budget = {"max_provider_attempts": 4, "max_total_input_tokens": 1000,
                      "max_total_output_tokens": 1000}
            payload = {"model": "fixture", "messages": [{"role": "user", "content": "same request"}],
                       "max_tokens": 8}
            job_id = payload_digest(payload)
            response = {"choices": [{"finish_reason": "stop", "message": {"content": "{}"}}],
                        "usage": {"prompt_tokens": 7, "completion_tokens": 2, "total_tokens": 9}}
            completed = {"job_id": job_id, "payload_sha256": job_id, "status": "completed",
                         "response": response, "response_sha256": payload_digest(response)}
            calls = []
            accepted = False

            def opener(req, **kwargs):
                nonlocal accepted
                method = req.get_method()
                calls.append((method, req.full_url))
                if method == "GET":
                    if not accepted:
                        raise HTTPError(req.full_url, 404, "missing", {}, io.BytesIO(b"{}"))
                    return _Response(json.dumps(completed).encode())
                if method == "POST":
                    accepted = True
                    raise OSError("simulated lost acknowledgement after acceptance")
                self.fail(f"unexpected method {method}")

            counted = _Accounting(root, ledger, budget, opener)
            cfg = {"jobs_url": "https://fixture.invalid/jobs", "token": "not-a-real-token",
                   "job_wait_seconds": 5, "job_poll_seconds": 0.001, "timeout": 1}
            first_body, first_trace = complete_job(cfg, payload, counted, clock=lambda: 1.0,
                                                   sleep=lambda _: None)
            self.assertEqual(first_body, response)
            self.assertEqual(first_trace["job_id"], job_id)
            self.assertEqual(ledger["provider_attempts"], 1)
            self.assertEqual(sum(method == "POST" for method, _ in calls), 1)
            prior_reserved = (ledger["reserved_input_tokens"], ledger["reserved_output_tokens"])

            # A process resume starts with GET for the same content-derived job.
            persisted = json.loads((root / "runtime_ledger.json").read_text(encoding="utf-8"))
            resumed = _Accounting(root, persisted, budget, opener)
            second_body, second_trace = complete_job(cfg, payload, resumed, clock=lambda: 2.0,
                                                     sleep=lambda _: None)
            self.assertEqual(second_body, response)
            self.assertEqual(second_trace["job_id"], job_id)
            self.assertEqual(resumed.ledger["provider_attempts"], 1)
            self.assertEqual(sum(method == "POST" for method, _ in calls), 1)
            self.assertEqual((resumed.ledger["reserved_input_tokens"], resumed.ledger["reserved_output_tokens"]),
                             prior_reserved)
            self.assertEqual(resumed.ledger["attempts"][0]["usage"], None)
            self.assertGreaterEqual(resumed.ledger["get_polls"], 3)


class LockedWorkloadBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from knowledge_base.pipeline_v1.au_context_paired.build import MODEL, build

        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name)
        cls.cfg = {
            "model": MODEL,
            "enable_thinking": False,
            "transport": "jobs",
            "string_decoder": "host_validated",
            "url": "https://fixture.invalid/v1",
            "jobs_url": "https://fixture.invalid/jobs",
            "token": "TEST_SECRET_SENTINEL_DO_NOT_PERSIST",
        }
        cls.workload = build(cls.root / "first", cfg=cls.cfg)
        cls.workload_again = build(cls.root / "second", cfg=cls.cfg)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_locked_build_is_deterministic_and_has_the_expected_sample_shape(self):
        self.assertEqual(self.workload["workload_sha256"], self.workload_again["workload_sha256"])
        self.assertEqual(self.workload["pairs"], self.workload_again["pairs"])
        self.assertEqual(
            self.workload["manifest"]["requests"],
            self.workload_again["manifest"]["requests"],
        )
        self.assertEqual(len(self.workload["pairs"]), 32)
        changed = [p for p in self.workload["pairs"] if p["effective_delta"]]
        controls = [p for p in self.workload["pairs"] if not p["effective_delta"]]
        self.assertEqual(len(changed), 2)
        self.assertEqual(len(controls), 30)
        by_case = {}
        for pair in controls:
            by_case.setdefault(pair["case_id"], []).append(pair)
        self.assertEqual(len(by_case), 5)
        self.assertTrue(all(len(rows) == 6 for rows in by_case.values()))
        for rows in by_case.values():
            self.assertEqual(len({r["control_stratum"] for r in rows}), 6)

    def test_target_and_physical_request_mapping_match_effective_delta(self):
        requests = {r["request_id"]: r for r in self.workload["manifest"]["requests"]}
        for pair in self.workload["pairs"]:
            g_id, s_id = pair["request_ids"]["G"], pair["request_ids"]["S"]
            self.assertEqual(pair["target"]["case_id"], pair["case_id"])
            self.assertEqual(pair["target"]["source_hash"], pair["source_hash"])
            self.assertEqual(set(pair["target"]), {
                "case_id", "source_hash", "start_char", "end_char"
            })
            self.assertEqual(pair["target_id"], requests[g_id]["expected_target_ids"][0])
            self.assertEqual(pair["target_id"], requests[s_id]["expected_target_ids"][0])
            self.assertEqual(requests[g_id]["source_hash"], pair["source_hash"])
            self.assertEqual(requests[s_id]["source_hash"], pair["source_hash"])
            self.assertEqual(
                [r for r in requests[g_id]["source_refs"] if r["role"] == "target"],
                [r for r in requests[s_id]["source_refs"] if r["role"] == "target"],
            )
            self.assertEqual(g_id == s_id, pair["shared_identical_input"])
            if pair["effective_delta"]:
                self.assertNotEqual(g_id, s_id)
                self.assertNotEqual(
                    self.workload["rendered_fingerprints"][g_id]["prompt_sha256"],
                    self.workload["rendered_fingerprints"][s_id]["prompt_sha256"],
                )
            else:
                self.assertEqual(g_id, s_id)
        ids = [r["request_id"] for r in self.workload["manifest"]["requests"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(ids), 34)

    def test_inventory_audit_separates_raw_catalog_and_effective_changes(self):
        audit = json.loads((self.root / "first" / "inventory_audit.json").read_text(encoding="utf-8"))
        effective = {row["region_id"] for row in audit if row["effective_delta"]}
        self.assertEqual(len(effective), 2)
        for row in audit:
            self.assertEqual(
                row["effective_context_noop"],
                bool(row["raw_delta"] and not row["effective_delta"]),
            )
            if row["effective_delta"]:
                self.assertTrue(row["raw_delta"])

    def test_build_refuses_overwrite_and_does_not_write_runtime_secret(self):
        from knowledge_base.pipeline_v1.au_context_paired.build import PairedError, build

        with self.assertRaisesRegex(PairedError, "nonempty build output"):
            build(self.root / "first", cfg=self.cfg)
        output = (self.root / "first").read_text(encoding="utf-8") if (self.root / "first").is_file() else ""
        serialized = "".join(
            p.read_text(encoding="utf-8") for p in (self.root / "first").rglob("*") if p.is_file()
        )
        self.assertNotIn(self.cfg["token"], output + serialized)

    def test_source_binding_tamper_is_rejected(self):
        from knowledge_base.pipeline_v1.au_context_paired.build import PairedError, binding, verify_bindings

        fixture = self.root / "binding_fixture.json"
        fixture.write_text('{"locked":true}\n', encoding="utf-8")
        locked = binding(fixture)
        verify_bindings([locked])
        fixture.write_text('{"locked":false}\n', encoding="utf-8")
        with self.assertRaisesRegex(PairedError, "changed input/code binding"):
            verify_bindings([locked])

    def test_preflight_accepts_locked_workload_and_reports_full_reservations(self):
        from knowledge_base.pipeline_v1.au_context_paired.preflight import preflight, validate_workload

        self.assertIs(validate_workload(self.workload, cfg=self.cfg), self.workload)
        report = preflight(self.workload, cfg=self.cfg)
        self.assertEqual(report["status"], "pass", report["failures"])
        self.assertEqual(report["physical_request_count"], 34)
        self.assertEqual(report["required_caps"]["max_requests"], 34)
        self.assertEqual(report["required_caps"]["max_provider_attempts"], 100)
        self.assertEqual(
            report["required_caps"]["max_total_input_tokens"],
            sum(r["input_tokens"] for r in self.workload["manifest"]["requests"]),
        )
        self.assertTrue(report["source_only_http_grammar_bytes_are_not_model_tokens"])
        self.assertEqual(report["semantic_quality"], "not_assessed")

    def test_preflight_rejects_payload_and_binding_tamper_even_if_outer_hash_is_recomputed(self):
        from knowledge_base.pipeline_v1.au_context_paired.build import fingerprint
        from knowledge_base.pipeline_v1.au_context_paired.preflight import validate_workload
        from knowledge_base.pipeline_v1.au_context_paired.build import PairedError

        stale = deepcopy(self.workload)
        stale["manifest"]["requests"][0]["request_id"] += "-tampered"
        with self.assertRaisesRegex(PairedError, "workload identity hash mismatch"):
            validate_workload(stale, cfg=self.cfg)

        payload_tampered = deepcopy(self.workload)
        request = payload_tampered["manifest"]["requests"][0]
        context = next(r for r in request["source_refs"] if r["role"] == "context")
        context["start_char"] += 1
        unsigned = {k: v for k, v in payload_tampered.items() if k != "workload_sha256"}
        payload_tampered["workload_sha256"] = fingerprint(unsigned)
        with self.assertRaises((PairedError, KeyError, OSError)):
            validate_workload(payload_tampered, cfg=self.cfg)

        binding_tampered = deepcopy(self.workload)
        binding_tampered["bindings"][0]["sha256"] = "0" * 64
        unsigned = {k: v for k, v in binding_tampered.items() if k != "workload_sha256"}
        binding_tampered["workload_sha256"] = fingerprint(unsigned)
        with self.assertRaisesRegex(PairedError, "changed input/code binding"):
            validate_workload(binding_tampered, cfg=self.cfg)

    def test_runner_dry_run_validates_without_calling_injected_transport(self):
        from knowledge_base.pipeline_v1.au_context_paired.runner import run

        def forbidden_transport(*args, **kwargs):
            raise AssertionError("dry-run unexpectedly touched the transport")

        result = run(
            self.workload,
            source_store=self.workload["source_store"],
            atom_root=self.workload["atom_root"],
            cfg=self.cfg,
            budget={},
            output_root=self.root / "dry-run",
            execute=False,
            opener=forbidden_transport,
        )
        self.assertEqual(result["status"], "not_executed")
        self.assertEqual(result.get("workload_sha256"), self.workload["workload_sha256"])
        self.assertFalse(result["semantic_quality_claim"])
        self.assertEqual(result["request_ledger"], [])

    def test_valid_json_with_length_finish_is_unresolved_and_fails_smoke(self):
        from knowledge_base.pipeline_v1.au_context_paired import runner
        from unittest.mock import patch

        workload = deepcopy(self.workload)
        requests = [r for r in workload["manifest"]["requests"]
                    if r["request_id"] in workload["smoke_request_ids"]][:2]
        workload["manifest"]["requests"] = requests
        workload["smoke_request_ids"] = [r["request_id"] for r in requests]
        budget = {"max_requests": 34, "max_provider_attempts": 100,
                  "max_total_input_tokens": 10**9, "max_total_output_tokens": 10**6}
        cfg = {**self.cfg, "expected_model_revision": "c202236235762e1c871ad0ccb60c8ee5ba337b9a",
               "timeout": 1, "job_wait_seconds": 1, "job_poll_seconds": 1}

        def fake_warmup(cfg, policy, path, counted):
            value = {"status": "success", "attempts": []}
            runner.compact._atomic(Path(path) / "warmup.json", value)
            return value

        def fake_probe(cfg, root, counted):
            value = {"status": "supported", "usage_state": "unknown"}
            counted.ledger["probe"] = value
            counted.save()
            runner._immutable(Path(root) / "probe_receipts" / "00.json", value)
            return value

        def fake_call(cfg, request, rendered, counted, catalog=None):
            compact_value = {
                "request_id": request["request_id"],
                "target_id": request["expected_target_ids"][0],
                "decision": "hard_negative", "coverage_status": "complete", "aus": [],
                "hard_negative_reason": "other", "unresolved_reason": None,
            }
            receipt = {"usage": {"input_tokens": 5, "output_tokens": 3, "total_tokens": 8},
                       "usage_state": "provider",
                       "finish_reason": "length" if request["request_id"] == requests[0]["request_id"] else "stop",
                       "transport_trace": {"transport": "jobs", "job_id": "fixture-" + request["request_id"]}}
            return compact_value, receipt

        def ready_health(request, **_kwargs):
            self.assertEqual(request.get_method(), "GET")
            self.assertTrue(request.full_url.endswith("/health"))
            return runner._Response(b'{"ready":true}')

        with patch("knowledge_base.pipeline_v1.au_context_paired.preflight.validate_workload"), \
             patch("knowledge_base.pipeline_v1.au_context_paired.preflight.preflight",
                   return_value={"status": "pass", "failures": []}), \
             patch.object(runner, "warmup", side_effect=fake_warmup), \
             patch.object(runner, "_probe", side_effect=fake_probe), \
             patch.object(runner.compact, "_call", side_effect=fake_call):
            result = runner.run(workload, source_store=self.workload["source_store"],
                                atom_root=self.workload["atom_root"], cfg=cfg, budget=budget,
                                output_root=self.root / "length-smoke", execute=True, smoke=True,
                                opener=ready_health, clock=lambda: 0.0, sleep=lambda _seconds: None)
        self.assertEqual(result["request_ledger"][0]["status"], "unresolved")
        self.assertEqual(result["request_ledger"][0]["receipt"]["finish_reason"], "length")
        self.assertEqual(result["request_ledger"][1]["status"], "protocol_verified")
        self.assertEqual(result["smoke_gate"], "fail")
        self.assertFalse(result["semantic_quality_claim"])

    def test_review_artifacts_stay_pending_and_do_not_claim_gold(self):
        from knowledge_base.pipeline_v1.au_context_paired.review import (
            reference_checklist, review_packet, validate_checklist,
        )

        checklist = reference_checklist(self.workload)
        self.assertEqual(checklist["status"], "pending")
        self.assertFalse(checklist["semantic_gold"])
        self.assertEqual(checklist["reference_kind"], "model_assisted_reference")
        with self.assertRaisesRegex(ValueError, "not reviewed/locked"):
            validate_checklist(checklist, self.workload, require_locked=True)
        locked = deepcopy(checklist)
        locked["status"] = "locked"
        for row in locked["rows"]:
            row.update(status="reviewed", reviewer="independent-reviewer")
        self.assertIs(validate_checklist(locked, self.workload, require_locked=True), locked)

        run = {"workload_sha256": self.workload["workload_sha256"], "status": "incomplete",
               "request_ledger": []}
        packet, host_mapping = review_packet(self.workload, run)
        self.assertFalse(packet["semantic_gold"])
        self.assertEqual(packet["status"], "pending")
        self.assertFalse(any("arm" in row for row in packet["rows"]))
        self.assertEqual(len(host_mapping["rows"]), len(packet["rows"]))
        self.assertTrue(all(row["semantic_verdict"] is None for row in packet["rows"]))

    def test_compare_counts_shared_receipt_once_and_leaves_semantics_pending(self):
        from knowledge_base.pipeline_v1.au_context_paired.compare import compare

        shared = next(p for p in self.workload["pairs"] if p["shared_identical_input"])
        request_id = shared["request_ids"]["G"]
        request = next(r for r in self.workload["manifest"]["requests"]
                       if r["request_id"] == request_id)
        run = {"workload_sha256": self.workload["workload_sha256"], "status": "incomplete",
               "request_ledger": [{
                   "request": request, "status": "protocol_verified", "compact_response": None,
                   "receipt": {"usage": {"input_tokens": 10, "output_tokens": 3, "total_tokens": 13}},
               }]}
        report = compare(self.workload, run)
        self.assertEqual(report["executed_extraction_cost"]["unique_extraction_receipts"], 1)
        self.assertEqual(report["executed_extraction_cost"]["known_total_tokens"], 13)
        self.assertEqual(report["executed_extraction_cost"]["usage_attribution"],
                         "observed provider usage; not verified new billing")
        self.assertEqual(report["executed_extraction_cost"]["server_recovered_without_POST"], 0)
        self.assertEqual(report["shared_control_count"], 30)
        self.assertFalse(report["semantic_gold"])
        self.assertFalse(report["retrieval_quality_claim"])
        self.assertEqual(report["semantic_review_status"], "pending_or_partial")
        pair_row = next(p for p in report["pairs"] if p["pair_id"] == shared["pair_id"])
        self.assertEqual(pair_row["semantic_comparison"], "not_assessed")

    def test_runtime_report_marks_previously_recovered_usage_as_observed_not_new_billing(self):
        from knowledge_base.pipeline_v1.au_compact import runner as compact
        from knowledge_base.pipeline_v1.au_context_paired.runner import _execute, runtime_identity, receipt_key

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            request = {
                "request_id": "fixture-recovered-request", "case_id": "fixture-case",
                "source_hash": "source-hash", "expected_target_ids": ["fixture-target"],
                "atom_binding": {
                    "atom_map_relative_path": "atoms.json", "atom_map_sha256": "atom-hash",
                    "atom_map_cache_key": "cache-key", "case_id": "fixture-case",
                    "source_hash": "source-hash", "segmenter_version": "segmenter-v1",
                    "policy_sha256": "policy-hash",
                },
            }
            workload = {"workload_sha256": "locked-fixture-hash",
                        "smoke_request_ids": [request["request_id"]]}
            cfg = {"url": "https://fixture.invalid/v1", "jobs_url": "https://fixture.invalid/jobs",
                   "model": "fixture-model", "enable_thinking": False, "transport": "jobs",
                   "string_decoder": "host_validated"}
            identity = runtime_identity(workload, cfg)
            key = receipt_key(request, identity, cfg)
            usage = {"input_tokens": 7, "output_tokens": 2, "total_tokens": 9}
            row = {"cache_key": key, "request": request, "status": "protocol_verified",
                   "compact_response": {}, "response": {}, "catalog_metrics": {},
                   "receipt": {"usage": usage, "usage_state": "provider",
                               "transport_trace": {"job_id": "server-recovered-job"},
                               "provider_POST_attempts_for_job": 0,
                               "server_recovered_without_POST": True}}
            row["row_sha256"] = compact._hash(row)
            _write_json(root / "receipts" / f"{key}.json", row)
            ledger = {"identity": identity, "workload_sha256": workload["workload_sha256"],
                      "provider_attempts": 0, "get_polls": 0, "warmup_attempts": 0,
                      "probe_attempts": 0, "requests": 1, "reserved_input_tokens": 0,
                      "reserved_output_tokens": 800, "attempts": [], "reservations": {},
                      "terminal": {request["request_id"]: key}, "smoke_gate": "pending",
                      "warmup": {"status": "success"}, "probe": {"status": "supported"}}
            _write_json(root / "runtime_ledger.json", ledger)

            def forbidden_opener(*args, **kwargs):
                self.fail("pre-existing recovered receipt must not submit a provider request")

            result = _execute(workload, [request], None, None, cfg,
                              {"max_requests": 34, "max_provider_attempts": 100,
                               "max_total_input_tokens": 10**9,
                               "max_total_output_tokens": 10**6}, root, True,
                              forbidden_opener, None)
            self.assertEqual(result["status"], "complete")
            self.assertEqual(result["current_run_provider_POST_attempts"], 0)
            self.assertEqual(result["server_recovered_jobs_without_POST"], 1)
            self.assertEqual(result["known_total_tokens"], 9)
            self.assertEqual(result["actual_total_tokens"], 9)
            self.assertEqual(result["usage_attribution"],
                             "observed_provider_usage; not verified new billing")


if __name__ == "__main__":
    unittest.main()
