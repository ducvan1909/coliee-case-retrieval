"""Independent portability and integrity tests for the K0 portable handoff.

These tests cover the protocol and migration boundary only. Mock runs do not
call a provider and do not establish AU semantic quality or human gold.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path, PurePosixPath, PureWindowsPath

from knowledge_base.pipeline_v1.k0_portable import core, paths


REPO = Path(__file__).resolve().parents[1]
BUNDLE = core.DEFAULT_BUNDLE
MANIFEST_REL = BUNDLE + "/manifest.json"
RUN_ROOT = "research_bundle/k0_portable_runs/current"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_posix_relative(value: str) -> None:
    assert isinstance(value, str) and value and "\\" not in value and ":" not in value
    posix = PurePosixPath(value)
    assert not posix.is_absolute()
    assert not PureWindowsPath(value).is_absolute()
    assert all(part not in ("", ".", "..") for part in value.split("/"))


REQUIRED_CLOSURE_PACKAGES = (
    "au_only", "kos_comparison", "region_priority_offline",
    "region_priority_variants", "selective_context_offline",
    "sentence_atoms", "structural_prepass",
)


class K0PortableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source_manifest_path = REPO / MANIFEST_REL
        if not cls.source_manifest_path.is_file():
            raise AssertionError(
                f"Main/implementer portable export is required before tests: {cls.source_manifest_path}"
            )
        cls.source_manifest = read_json(cls.source_manifest_path)
        cls.bound_paths = {row["path"] for row in cls.source_manifest["code_bindings"]}
        cls.assert_code_binding_closure()

    @classmethod
    def assert_code_binding_closure(cls, _unused=None):
        required_files = {
            "knowledge_base/__init__.py",
            "knowledge_base/config.py",
            "knowledge_base/pipeline_v1/__init__.py",
        }
        for package in REQUIRED_CLOSURE_PACKAGES:
            directory = REPO / "knowledge_base/pipeline_v1" / package
            required_files.update(p.relative_to(REPO).as_posix()
                                  for p in directory.glob("*.py"))
        required_files.update(p.relative_to(REPO).as_posix()
                              for p in (REPO / "knowledge_base/pipeline_v1/contracts").glob("*.json"))
        missing = required_files - cls.bound_paths
        if missing:
            raise AssertionError(f"portable code binding closure is incomplete: {sorted(missing)}")

    def clone_portable_tree(self, root: Path) -> None:
        """Copy only manifest-bound code plus the complete immutable bundle."""
        manifest = self.source_manifest
        rel_files = {MANIFEST_REL}
        rel_files.update(binding["path"] for binding in manifest["code_bindings"])
        rel_files.update(binding["path"] for binding in manifest["archive"].values())
        rel_files.update(("knowledge_base/__init__.py", "knowledge_base/config.py",
                          "knowledge_base/pipeline_v1/__init__.py"))
        rel_files.update(p.relative_to(REPO).as_posix()
                         for p in (REPO / "knowledge_base/pipeline_v1/contracts").glob("*.json"))
        for rel in sorted(rel_files):
            source = REPO.joinpath(*PurePosixPath(rel).parts)
            self.assertTrue(source.is_file(), f"missing manifest-bound file: {rel}")
            destination = root.joinpath(*PurePosixPath(rel).parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)

    @staticmethod
    def invoke(root: Path, cwd: Path, *args: str, expect=(0,)):
        env = os.environ.copy()
        # Never inherit an original checkout path. Filter it again at startup in
        # case site configuration or an editable install added it to sys.path.
        env["PYTHONPATH"] = str(root)
        env["PYTHONUTF8"] = "1"
        startup = f'''\
import builtins, io, os, pathlib, runpy, sys
repo = pathlib.Path({str(REPO)!r}).resolve()
root = pathlib.Path({str(root)!r}).resolve()
venv = repo / ".venv"
def guard(original):
    def checked(file, *args, **kwargs):
        if isinstance(file, (str, bytes, os.PathLike)):
            try:
                candidate = pathlib.Path(os.fsdecode(file)).resolve()
                if candidate.is_relative_to(repo) and not candidate.is_relative_to(venv):
                    raise RuntimeError("portable relocation attempted old checkout access: " + str(candidate))
            except (OSError, ValueError):
                pass
        return original(file, *args, **kwargs)
    return checked
builtins.open = guard(builtins.open)
io.open = guard(io.open)
os.open = guard(os.open)
sys.path = [str(root)] + [p for p in sys.path
    if (not pathlib.Path(p or ".").resolve().is_relative_to(repo)
        or pathlib.Path(p or ".").resolve().is_relative_to(venv))]
sys.argv = ["knowledge_base.pipeline_v1.k0_portable", *sys.argv[2:]]
runpy.run_module("knowledge_base.pipeline_v1.k0_portable", run_name="__main__")
'''
        command = [sys.executable, "-c", startup, str(root), *args,
                   "--repo-root", str(root), "--bundle", BUNDLE,
                   "--output-root", RUN_ROOT]
        result = subprocess.run(command, cwd=cwd, env=env, text=True,
                                encoding="utf-8", capture_output=True, check=False,
                                timeout=180)
        if result.returncode not in expect:
            raise AssertionError(
                f"command exit={result.returncode}, expected={expect}: {command!r}\n"
                f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            )
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        try:
            payload = json.loads(lines[-1])
        except (IndexError, json.JSONDecodeError) as exc:
            raise AssertionError(f"CLI did not return JSON: {result.stdout!r}") from exc
        return result, payload

    def snapshot_bundle(self, root: Path) -> dict[str, str]:
        bundle = root / BUNDLE
        return {p.relative_to(bundle).as_posix(): sha256(p)
                for p in bundle.rglob("*") if p.is_file()}

    def test_path_resolution_rejects_absolute_traversal_and_symlink_escape(self):
        with tempfile.TemporaryDirectory(prefix="k0 Ω root ") as temp:
            base = Path(temp) / "根 with spaces"
            base.mkdir()
            self.assertEqual(paths.resolve(base, "input/workload.json"),
                             (base / "input/workload.json").resolve())
            for invalid in ("../outside", "a/../../outside", "/etc/passwd",
                            "C:/outside", "C:\\outside", "\\\\server\\share", "a\\b"):
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    paths.resolve(base, invalid)

            outside = Path(temp) / "outside"
            outside.mkdir()
            link = base / "escape"
            try:
                os.symlink(outside, link, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"directory symlinks unavailable in this environment: {exc}")
            with self.assertRaises(ValueError):
                paths.resolve(base, "escape/secret.json")

    def test_relocated_code_and_bundle_work_offline_from_unrelated_unicode_cwd(self):
        with tempfile.TemporaryDirectory(prefix="k0 portable relocation ") as temp:
            parent = Path(temp)
            root_a = parent / "origin A"
            root_b = parent / "目标 B with spaces"
            cwd = parent / "第三个工作目录 Ω"
            root_a.mkdir()
            cwd.mkdir()
            self.clone_portable_tree(root_a)

            # Run initial offline lifecycle at A, then move code, bundle, and run.
            _, inspected_a = self.invoke(root_a, cwd, "inspect", expect=(0,))
            self.assertEqual(inspected_a["status"], "pass")
            self.invoke(root_a, cwd, "prepare", expect=(0,))
            _, preflight_a = self.invoke(root_a, cwd, "preflight", expect=(0,))
            self.assertEqual(preflight_a["status"], "pass")
            _, dryrun = self.invoke(root_a, cwd, "run", expect=(0,))
            self.assertEqual(dryrun["mode"], "dryrun")
            self.assertEqual(dryrun["network_requests"], 0)

            shutil.copytree(root_a, root_b)
            shutil.rmtree(root_a)
            self.assertFalse(root_a.exists(), "the old portable root must be unavailable")

            _, inspected_b = self.invoke(root_b, cwd, "inspect", "--check-runtime", expect=(0,))
            self.assertEqual(inspected_b["status"], "pass")
            self.assertTrue(inspected_b["offline"])
            self.assertEqual(inspected_b["network_requests"], 0)
            self.assertEqual(inspected_b["history_policy"], "archive_only_not_resumable_as_new_run")
            self.assertEqual(inspected_b["semantic_quality"], "not_assessed")
            self.assertEqual(inspected_b["history"]["status"], "complete")

            manifest = read_json(root_b / MANIFEST_REL)
            workload = read_json(root_b / RUN_ROOT / "input/workload.json")
            active_refs = [manifest[k] for k in ("history_root", "controls_root", "source_store",
                                                   "original_workload")]
            active_refs += [b["path"] for b in manifest["archive"].values()]
            active_refs += [b["path"] for b in manifest["code_bindings"]]
            active_refs += [workload[k] for k in ("bundle", "source_store")]
            active_refs += [b["path"] for key in ("source_bindings", "parent_bindings", "code_bindings")
                            for b in workload.get(key, [])]
            for ref in active_refs:
                with self.subTest(path=ref):
                    require_posix_relative(ref)

            # Historical origin metadata may record its environment. It must not
            # be a runtime binding: current runtime checks passed from B above.
            origin = manifest["origin_verification"]
            self.assertIn("executable", origin)
            self.assertIn("platform", origin)
            self.assertNotIn(str(root_a), json.dumps(workload, ensure_ascii=False))

    def test_source_code_receipt_and_tokenizer_tampering_fail_runtime_inspection(self):
        with tempfile.TemporaryDirectory(prefix="k0 portable tamper ") as temp:
            root = Path(temp) / "repo Ω"
            root.mkdir()
            cwd = Path(temp) / "cwd"
            cwd.mkdir()
            self.clone_portable_tree(root)
            manifest = read_json(root / MANIFEST_REL)

            source_rel = next((b["path"] for key, b in manifest["archive"].items()
                               if "/source_store_v1/" in key.replace("\\", "/")
                               and key.endswith("source.txt")), None)
            receipt_rel = next((b["path"] for key, b in manifest["archive"].items()
                                if "/live/receipts/" in key.replace("\\", "/")
                                and key.endswith(".json")), None)
            code_rel = next(b["path"] for b in manifest["code_bindings"]
                            if b["path"].endswith("/k0_portable/core.py"))
            tokenizer_rel = next((b["path"] for b in manifest["code_bindings"]
                                  if "tokenizer" in b["path"].lower()), None)
            self.assertIsNotNone(source_rel, "export must preserve a source-store byte binding")
            self.assertIsNotNone(receipt_rel, "export must preserve a raw controls receipt binding")
            self.assertIsNotNone(tokenizer_rel, "runtime bindings must include tokenizer revision assets")

            for label, rel in (("source", source_rel), ("code", code_rel),
                               ("receipt", receipt_rel), ("tokenizer", tokenizer_rel)):
                path = root.joinpath(*PurePosixPath(rel).parts)
                original = path.read_bytes()
                with self.subTest(tamper=label):
                    try:
                        suffix = b"\n# portable-tamper\n" if label == "code" else b"\nportable-tamper"
                        path.write_bytes(original + suffix)
                        _, result = self.invoke(root, cwd, "inspect", "--check-runtime", expect=(1,))
                        self.assertEqual(result["status"], "blocked")
                        self.assertNotEqual(result.get("status"), "pass")
                    finally:
                        path.write_bytes(original)

            manifest_path = root / MANIFEST_REL
            original_manifest_bytes = manifest_path.read_bytes()
            changed_manifest = read_json(manifest_path)
            changed_manifest["input_counter"]["revision"] = "different-tokenizer-revision"
            changed_manifest["sha256"] = core.fingerprint(
                {k: v for k, v in changed_manifest.items() if k != "sha256"})
            try:
                manifest_path.write_text(json.dumps(changed_manifest, ensure_ascii=False),
                                         encoding="utf-8")
                _, revision_result = self.invoke(root, cwd, "inspect", "--check-runtime", expect=(1,))
                self.assertEqual(revision_result["status"], "blocked")
            finally:
                manifest_path.write_bytes(original_manifest_bytes)

    def test_mock_backpressure_resume_after_relocation_does_not_replay_or_claim_usage(self):
        with tempfile.TemporaryDirectory(prefix="k0 portable resume ") as temp:
            parent = Path(temp)
            root_a = parent / "root A"
            root_b = parent / "résumé B with spaces"
            cwd = parent / "unrelated CWD"
            root_a.mkdir()
            cwd.mkdir()
            self.clone_portable_tree(root_a)
            self.invoke(root_a, cwd, "prepare", expect=(0,))
            self.invoke(root_a, cwd, "preflight", expect=(0,))

            # A one-request admission bound creates a durable incomplete mock
            # checkpoint without contacting a provider.
            _, partial = self.invoke(root_a, cwd, "run", "--mock", "--max-new-requests", "1",
                                     expect=(3,))
            self.assertEqual(partial["status"], "incomplete")
            self.assertEqual(partial["pauses"].get("011904") or partial["pauses"].get("045155")
                             or partial["pauses"].get("099980"), "invocation_limit")
            mock_root_a = root_a / RUN_ROOT / "mock"
            ledger_a = read_json(mock_root_a / "runtime_ledger.json")
            initial_receipts = {
                entry["job"]["request_id"]: entry["receipt_sha256"]
                for entry in ledger_a["jobs"].values() if entry.get("receipt_sha256")
            }
            self.assertTrue(initial_receipts, "bounded mock run must persist a receipt")
            archived_before = self.snapshot_bundle(root_a)

            shutil.copytree(root_a, root_b)
            shutil.rmtree(root_a)
            self.assertFalse(root_a.exists())
            _, resumed_bounded = self.invoke(root_b, cwd, "run", "--mock",
                                             "--max-new-requests", "1", expect=(3,))
            self.assertEqual(resumed_bounded["status"], "incomplete")
            ledger_bounded = read_json(root_b / RUN_ROOT / "mock/runtime_ledger.json")
            self.assertEqual(len(ledger_bounded["attempts"]) - len(ledger_a["attempts"]), 1,
                             "resume must admit one new attempt while reusing the old receipt")
            _, resumed = self.invoke(root_b, cwd, "run", "--mock", expect=(0, 3))
            self.assertEqual(resumed["mode"], "mock")
            self.assertEqual(resumed["network_requests"], 0)
            self.assertEqual(resumed["provider_POST_attempts"], 0)
            self.assertIsNone(resumed["known_provider_usage_observed_subtotal"])
            self.assertIsNone(resumed["total_provider_usage"])
            self.assertFalse(resumed["usage_is_complete"])

            mock_root_b = root_b / RUN_ROOT / "mock"
            ledger_b = read_json(mock_root_b / "runtime_ledger.json")
            self.assertGreaterEqual(len(ledger_b["attempts"]), len(ledger_a["attempts"]))
            for request_id, digest in initial_receipts.items():
                receipt = mock_root_b / "receipts" / f"{request_id}.json"
                self.assertTrue(receipt.is_file(), f"resumed receipt missing: {request_id}")
                self.assertEqual(read_json(receipt)["receipt_sha256"], digest,
                                 f"existing receipt replayed/rewritten: {request_id}")
            self.assertEqual(self.snapshot_bundle(root_b), archived_before,
                             "portable export and original receipts/provenance must remain byte-identical")


if __name__ == "__main__":
    unittest.main()
