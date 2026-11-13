"""Hermetic checks that a paid-query handoff cannot accidentally replay."""
from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock


SCRIPT = Path(__file__).with_name('run_real_query.py')
SPEC = importlib.util.spec_from_file_location('m3_acceptance_query', SCRIPT)
COMMAND = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COMMAND)


class QueryCommandTests(unittest.TestCase):
    def manifest(self):
        return {'source': {'case_id': '000001.txt'}, 'query': 'fixture query'}

    def test_default_only_previews_without_creating_admission(self):
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name)
            with patch.object(COMMAND, 'HERE', folder), patch.object(COMMAND, 'ROOT', folder):
                with patch.object(COMMAND, 'load_manifest', return_value=(self.manifest(), 'fixture')):
                    with patch.object(COMMAND.subprocess, 'run') as run:
                        with patch.object(COMMAND.sys, 'argv', ['run_real_query.py']):
                            with redirect_stdout(io.StringIO()):
                                self.assertEqual(COMMAND.main(), 0)
            run.assert_not_called()
            self.assertFalse((folder / 'real_query_execution').exists())

    def test_failed_execution_keeps_admission_and_blocks_replay(self):
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name)
            with patch.object(COMMAND, 'HERE', folder), patch.object(COMMAND, 'ROOT', folder):
                with patch.object(COMMAND, 'load_manifest', return_value=(self.manifest(), 'fixture')):
                    with patch.object(COMMAND.subprocess, 'run', return_value=Mock(returncode=2)) as run:
                        with patch.object(COMMAND.sys, 'argv', ['run_real_query.py', '--execute']):
                            with redirect_stdout(io.StringIO()):
                                self.assertEqual(COMMAND.main(), 2)
                                with self.assertRaises(FileExistsError):
                                    COMMAND.main()
            self.assertEqual(run.call_count, 1)
            receipt = json.loads((folder / 'real_query_execution/command_receipt.json').read_text())
            self.assertEqual(receipt['status'], 'failed')
            self.assertEqual(receipt['exit_code'], 2)
            self.assertEqual(receipt['new_runtime_usage'], {})

    def test_interrupted_execution_keeps_unknown_outcome_receipt(self):
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name)
            with patch.object(COMMAND, 'HERE', folder), patch.object(COMMAND, 'ROOT', folder):
                with patch.object(COMMAND, 'load_manifest', return_value=(self.manifest(), 'fixture')):
                    with patch.object(COMMAND.subprocess, 'run', side_effect=KeyboardInterrupt):
                        with patch.object(COMMAND.sys, 'argv', ['run_real_query.py', '--execute']):
                            with redirect_stdout(io.StringIO()):
                                with self.assertRaises(KeyboardInterrupt):
                                    COMMAND.main()
            receipt = json.loads((folder / 'real_query_execution/command_receipt.json').read_text())
            self.assertEqual(receipt['status'], 'interrupted_or_failed')
            self.assertEqual(receipt['error_type'], 'KeyboardInterrupt')
            self.assertTrue((folder / 'real_query_execution/admission.json').exists())

    def test_manifest_drift_stops_before_child_process(self):
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name)
            (folder / 'real_query_manifest.json').write_text('{}', encoding='utf-8')
            (folder / 'real_query_manifest.sha256').write_text('invalid', encoding='utf-8')
            with patch.object(COMMAND, 'HERE', folder):
                with patch.object(COMMAND.subprocess, 'run') as run:
                    with self.assertRaisesRegex(ValueError, 'manifest hash'):
                        COMMAND.load_manifest()
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
