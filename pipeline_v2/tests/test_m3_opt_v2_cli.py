"""Local CLI commands must not read credentials, initialize Modal, or infer."""
import builtins
from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pipeline_v2 import m3_opt_v2 as cli


class LocalCLIIsolationTests(unittest.TestCase):
    def test_build_verify_open_and_help_do_not_read_env_or_import_modal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            calls = []

            class Session:
                initialization_seconds = .01

                def __init__(self, root_arg, index_arg):
                    calls.append(("open-session", str(root_arg), str(index_arg)))

                def verify(self, full_db=False):
                    calls.append(("verify", full_db))
                    return {"status": "verified", "full_db_verified": bool(full_db)}

                def open(self, ident):
                    calls.append(("open-evidence", ident))
                    return {"passage_id": ident, "text": "synthetic evidence"}

                def close(self):
                    calls.append(("close",))

            original_import = builtins.__import__

            def no_modal_import(name, *args, **kwargs):
                if name == "modal":
                    raise AssertionError("local CLI attempted to import Modal")
                return original_import(name, *args, **kwargs)

            with patch.object(cli, "ROOT", root), \
                 patch("pipeline_v2.deploy_modal.parse_env", side_effect=AssertionError("local command read .env")), \
                 patch("pipeline_v2.deploy_modal.build_environment", side_effect=AssertionError("local command built Modal env")), \
                 patch("pipeline_v2.optimization_v2.index.build_index", return_value={"status": "built"}) as build, \
                 patch("pipeline_v2.optimization_v2.index.FastSession", side_effect=Session), \
                 patch("builtins.__import__", side_effect=no_modal_import):
                for argv in (
                    ["--env-file", str(root / "missing.env"), "build", "--output", "pipeline_v2/artifacts/build"],
                    ["--env-file", str(root / "missing.env"), "verify", "--index-dir", "pipeline_v2/artifacts/index"],
                    ["--env-file", str(root / "missing.env"), "open", "--index-dir", "pipeline_v2/artifacts/index", "--passage-id", "p1"],
                ):
                    with self.subTest(argv=argv), redirect_stdout(io.StringIO()):
                        self.assertEqual(cli.main(argv), 0)
                self.assertEqual(build.call_count, 1)
                self.assertIn(("verify", False), calls)
                self.assertIn(("open-evidence", "p1"), calls)
                self.assertEqual(calls.count(("close",)), 2)
                with self.assertRaises(SystemExit) as exit_info, redirect_stdout(io.StringIO()):
                    cli.main(["--env-file", str(root / "missing.env"), "--help"])
                self.assertEqual(exit_info.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
