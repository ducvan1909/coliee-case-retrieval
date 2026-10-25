import json
from pathlib import Path
import tempfile
import unittest

from knowledge_base.pipeline_v1.experiments.escape_length_repro import fixtures, main


class EscapeReproTests(unittest.TestCase):
    def test_decoded_lengths_and_expected(self):
        data = fixtures()
        self.assertEqual(len(data['cases']), 36)
        for row in data['cases']:
            self.assertEqual(len(json.loads(row['json'])['text']), row['decoded_length'])
            self.assertEqual(row['expected'], row['decoded_length'] <= 8)

    def test_equivalent_serializations(self):
        rows = fixtures()['cases']
        for left, right in zip(rows[::2], rows[1::2]):
            self.assertEqual(json.loads(left['json']), json.loads(right['json']))
            self.assertEqual(left['expected'], right['expected'])
        bmp = [r for r in rows if r['name'].startswith('bmp_8')]
        self.assertNotEqual(bmp[0]['serialized_string_content_length'], bmp[1]['serialized_string_content_length'])

    def test_prepare_no_optional_imports_or_network(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'case.json'
            self.assertEqual(main(['--output', str(path)]), 0)
            self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['status'], 'prepared')
            with self.assertRaises(SystemExit):
                main(['--output', str(path)])

    def test_invalid_caps(self):
        for cap in (0, 33, True):
            with self.assertRaises(ValueError):
                fixtures(cap)


if __name__ == '__main__':
    unittest.main()
