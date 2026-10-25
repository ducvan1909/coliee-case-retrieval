"""CLI gates for the source-free constraint suite; never calls an endpoint."""
import tempfile
import unittest
import io
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch

from knowledge_base.pipeline_v1.au_compact import __main__ as cli


class ConstraintSuiteCLITests(unittest.TestCase):
    def invoke(self, args, cfg, report):
        with patch("sys.argv", ["au_compact", "constraint-suite-probe", *args]), \
             redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), \
             patch.object(cli, "settings", return_value={}), \
             patch.object(cli, "load_au_runtime_config", return_value=(cfg, {}, {})), \
             patch.object(cli, "constraint_suite_probe", return_value=report) as probe:
            result = cli.main()
        return result, probe

    def test_offline_requires_no_endpoint_and_no_execute(self):
        with tempfile.TemporaryDirectory() as root:
            result, probe = self.invoke(["--output-root", root], {"url": "", "token": "", "model": ""}, {"status": "planned"})
        self.assertEqual(result, 0)
        self.assertFalse(probe.call_args.kwargs["execute"])

    def test_live_incomplete_is_nonzero_and_cap_forwarded(self):
        result, probe = self.invoke(["--execute", "--max-requests", "2"], {"url": "https://fake", "token": "secret", "model": "m"}, {"status": "incomplete"})
        self.assertEqual(result, 3)
        self.assertTrue(probe.call_args.kwargs["execute"])
        self.assertEqual(probe.call_args.kwargs["max_requests"], 2)

    def test_execute_requires_credentials_before_dispatch(self):
        with self.assertRaises(SystemExit) as caught:
            self.invoke(["--execute"], {"url": "", "token": "", "model": ""}, {"status": "pass"})
        self.assertEqual(caught.exception.code, 2)

    def test_nonpositive_cap_rejected(self):
        with self.assertRaises(SystemExit) as caught:
            self.invoke(["--max-requests", "0"], {}, {"status": "pass"})
        self.assertEqual(caught.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
