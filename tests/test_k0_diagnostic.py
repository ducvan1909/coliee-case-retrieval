"""Local checks for the isolated diagnostic; never calls a provider."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from knowledge_base.pipeline_v1.experiments import k0_diagnostic as d
from knowledge_base.pipeline_v1.k0_authoring import core
from knowledge_base.pipeline_v1.k0_authoring.tools import initial_state
from knowledge_base.pipeline_v1.au_context_paired.__main__ import study_config
import argparse


class DiagnosticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)/'probe'
        d.prepare(cls.root)
        cls.manifest = core.load(cls.root/'input/manifest.json')

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_synthetic_pair_only_differs_by_grammar(self):
        first, second = self.manifest['jobs'][:2]
        payload = copy.deepcopy(first['job']['payload']); payload.pop('ebnf')
        self.assertEqual(payload, second['job']['payload'])

    def test_positive_cpu_examples_also_pass_host(self):
        bundle = core.load(self.root/'input/cpu_bundle.json')
        for row, cpu in zip((self.manifest['jobs'][0], self.manifest['jobs'][2]), bundle['jobs']):
            for example in cpu['positive_examples']:
                self.assertFalse(core.validate_response(json.loads(example), row['job'])['au_errors'])

    def test_real_input_and_caps_preserved(self):
        w = core.load(d.DEFAULT_K0/'input/workload.json')
        cfg, _, _ = study_config(argparse.Namespace())
        old = core.build_job(w, w['cases'][0], initial_state(w['cases'][0]), cfg)
        new = self.manifest['jobs'][2]['job']
        self.assertEqual(old['catalog'], new['catalog'])
        self.assertEqual(old['active_scope_ids'], new['active_scope_ids'])
        self.assertTrue(new['payload']['messages'][0]['content'].startswith(old['payload']['messages'][0]['content']))
        self.assertEqual(old['payload']['max_tokens'], new['payload']['max_tokens'])
        self.assertEqual(old['payload']['chat_template_kwargs'], new['payload']['chat_template_kwargs'])

    def test_cpu_failure_prevents_network(self):
        (self.root/'cpu.json').write_text('{"status":"fail"}', encoding='utf-8')
        with patch.object(d.request, 'urlopen') as opener:
            with self.assertRaises(ValueError):
                d.run(self.root)
            opener.assert_not_called()

    def test_unbound_cpu_pass_prevents_network(self):
        (self.root/'cpu.json').write_text('{"status":"pass","bundle_sha256":"different"}', encoding='utf-8')
        with patch.object(d.request, 'urlopen') as opener:
            with self.assertRaises(ValueError):
                d.run(self.root)
            opener.assert_not_called()


if __name__ == '__main__':
    unittest.main()
