"""Regression for PowerShell location differing from .NET CurrentDirectory.

Only parse the entrypoint or execute its final JSON writer; never run inference.
"""
import base64
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "knowledge_base/pipeline_v1/experiments/run_primary_support.ps1"


def ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


class PrimarySupportReportPathTests(unittest.TestCase):
    def run_powershell(self, source, cwd=None):
        shell = shutil.which("pwsh") or shutil.which("powershell")
        if not shell:
            self.skipTest("PowerShell unavailable")
        encoded = base64.b64encode(source.encode("utf-16le")).decode("ascii")
        completed = subprocess.run(
            [shell, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            cwd=cwd, capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)

    def test_writer_uses_provider_location_for_relative_and_absolute_roots(self):
        source = SCRIPT.read_text(encoding="utf-8-sig")
        writer = "\n".join(line for line in source.splitlines()
                           if line.startswith("$comparisonPath =")
                           or line.startswith("[System.IO.File]::WriteAllText("))
        self.assertIn("Resolve-Path -LiteralPath $OutputRoot", writer)
        self.assertNotIn("GetFullPath", writer)
        for absolute in (False, True):
            with self.subTest(absolute=absolute), tempfile.TemporaryDirectory(prefix="primary-report-path-") as folder:
                base = Path(folder)
                provider = base / "provider's working folder"
                process = base / "process working folder"
                output = provider / "relative reports"
                output.mkdir(parents=True)
                process.mkdir()
                output_arg = output if absolute else "relative reports"
                snippet = (
                    "$ErrorActionPreference='Stop'\n"
                    f"Set-Location -LiteralPath {ps_quote(provider)}\n"
                    f"[Environment]::CurrentDirectory={ps_quote(process)}\n"
                    f"$OutputRoot={ps_quote(output_arg)}\n"
                    "$comparisonJson='{\"status\":\"complete\"}'\n"
                    + writer
                )
                self.run_powershell(snippet, cwd=process)
                data = (output / "comparison.json").read_bytes()
                self.assertEqual(data, b'{"status":"complete"}')
                self.assertFalse((process / "relative reports/comparison.json").exists())

    def test_entrypoint_retains_utf8_bom_and_parses_without_execution(self):
        self.assertTrue(SCRIPT.read_bytes().startswith(b"\xef\xbb\xbf"))
        self.run_powershell(
            "$tokens=$null; $parseErrors=$null\n"
            f"[System.Management.Automation.Language.Parser]::ParseFile({ps_quote(SCRIPT)},"
            "[ref]$tokens,[ref]$parseErrors) | Out-Null\n"
            "if($parseErrors.Count){throw 'PowerShell parse failed'}"
        )


if __name__ == "__main__":
    unittest.main()
