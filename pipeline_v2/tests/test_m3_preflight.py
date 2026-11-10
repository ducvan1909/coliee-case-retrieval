import json
from pathlib import Path
import shutil
import tempfile
import unittest
from contextlib import nullcontext
from unittest.mock import patch

from pipeline_v2.retrieval import pilot
from pipeline_v2.retrieval.common import M3Error


class M3PreflightTests(unittest.TestCase):
    def test_failed_rerun_invalidates_previous_success_and_blocks_pilot(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        run = tmp / "run"
        run.mkdir()
        profile = {"qdrant": {"url": "http://127.0.0.1:6333", "version": "1.20.0"},
                   "embedding": {"dimensions": 3}, "numerics": {"batch_cosine_atol": .001}}
        manifest = {"profile": profile, "collection": "pilot_test", "embedding_fingerprint": "fp",
                    "implementation": {"engine.py": "sha"}, "m2_seal_sha256": "m2-sha"}
        ready = {"status": "PASS", "embedding_fingerprint": "fp",
                 "implementation": manifest["implementation"], "m2_seal_sha256": "m2-sha"}
        preflight_path = run / "preflight.json"
        preflight_path.write_text(json.dumps(ready))

        class Server:
            def server_info(self):
                return {"version": "1.20.0"}

            def ensure(self):
                return {"status": "ok"}

        with patch.object(pilot, "load_run", return_value=(tmp, run, manifest, None, [])), \
             patch.object(pilot, "run_lock", return_value=nullcontext()), \
             patch.object(pilot, "QdrantStore", return_value=Server()), \
             patch.object(pilot, "resources", return_value=(None, None, None, None)), \
             patch.object(pilot, "call_embedding", side_effect=M3Error("simulated parity failure")):
            with self.assertRaises(M3Error):
                pilot.preflight(tmp, "pipeline_v2/artifacts/run")
            current = json.loads(preflight_path.read_bytes())
            self.assertNotEqual(current.get("status"), "PASS")

            with patch.object(pilot, "resources", side_effect=AssertionError("pilot passed invalid preflight")):
                with self.assertRaises(M3Error):
                    pilot.run_pilot(tmp, "pipeline_v2/artifacts/run")


if __name__ == "__main__":
    unittest.main()
