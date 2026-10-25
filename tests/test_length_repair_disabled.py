import contextlib
import io
import json
import unittest
from unittest.mock import Mock

from knowledge_base.pipeline_v1.au_claim_recovery.__main__ import main
from knowledge_base.pipeline_v1.au_claim_recovery.runner import run


class LengthRepairDisabledTests(unittest.TestCase):
    def test_cli_execute_stops_before_config_or_workload(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(['run', '--execute', '--output-root', 'nonexistent-length-repair-root'])
        self.assertEqual(code, 1)
        result = json.loads(output.getvalue())
        self.assertEqual(result['status'], 'disabled')
        self.assertFalse(result['network_executed'])

    def test_python_execution_stops_before_dispatch(self):
        opener = Mock(side_effect=AssertionError('must not call provider'))
        with self.assertRaises(ValueError):
            run('nonexistent-length-repair-root', execute=True, opener=opener)
        opener.assert_not_called()


if __name__ == '__main__':
    unittest.main()
