"""Test the M4 adapter against sealed M3 source fixtures."""

import hashlib

from pipeline_v2.agent_harness import SourceDrift
from pipeline_v2.m4 import M3Tools
from pipeline_v2.tests.test_m3_source_tools import SourceToolsFixture


class LexicalFixture:
    index_binding = {'manifest.json': 'sparse'}
    binding = {'manifest.json': 'full'}

    def search(self, text, kind, limit, exclude_case, unique_cases):
        raise AssertionError('Expected recorded replay')


class M4ToolsTests(SourceToolsFixture):
    def setUp(self):
        super().setUp()
        self.query = '000001.txt'
        self.case = '000002.txt'
        self.text = 'Début\nMilieu\nFin'
        self.raw = self.text.encode('utf-8')
        for case in (self.query, self.case):
            self.add_case(case, self.text, [{'span_bytes': [0, 6]}, {'span_bytes': [7, 13]},
                                            {'span_bytes': [14, 17]}])
        self.reader = self.make_session()
        self.addCleanup(self.reader.close)

    def adapter(self, **kwargs):
        return M3Tools(self.reader, LexicalFixture(), self.query, byte_budget=7, map_limit=1, **kwargs)

    def test_query_map_keeps_navigation_and_whole_query_has_raw_provenance(self):
        tools = self.adapter()
        first, whole = tools.query_start()
        self.assertEqual(first.observation['total'], 3)
        self.assertEqual(first.observation['next_offset'], 1)
        self.assertTrue(first.excerpts)
        self.assertTrue(first.observation['priority_open']['continuation'])
        self.assertEqual(whole.text.encode('utf-8'), self.raw)
        self.assertEqual(whole.source_hash, whole.text_sha256)
        second = tools.open_query({'offset': first.observation['next_offset']})
        self.assertEqual(second.observation['items'][0]['handle'], 'u0001')

    def test_replayed_lead_expands_with_checked_raw_bytes_and_continuation(self):
        lead = {'case_id': self.case, 'source_hash': self.sources[self.case],
                'passage_id': '000002:passage:1', 'score': 1.0}
        response = {'status': 'ok', 'request_id': 'prior-run', 'query_case': self.query,
                    'query_sha256': hashlib.sha256(b'query').hexdigest(),
                    'sparse_manifest_sha256': 'sparse', 'full_manifest_sha256': 'full',
                    'hits': [{'case_id': self.case, 'channels': {'dense_passage': lead}}]}
        tools = self.adapter(recorded_search=response)
        response['hits'].clear()
        result = tools.search_corpus({'channel': 'hybrid', 'text': 'query', 'limit': 1})
        self.assertEqual(result.candidates, (self.case,))
        self.assertEqual(result.observation['recorded_request_id'], 'prior-run')
        ref = result.observation['hits'][0]['channels']['dense_passage']['open_ref']
        page = tools.open_source(ref)
        self.assertTrue(page.source_requests[0]['pending_spans'])
        second = tools.expand_source({**ref, 'cursor': page.observation['next_cursor']})
        self.assertTrue(second.excerpts)
        for excerpt in (*page.excerpts, *second.excerpts):
            a, b = excerpt.span_bytes
            self.assertEqual(excerpt.text.encode('utf-8'), self.raw[a:b])
        with self.assertRaises(ValueError):
            tools.search_corpus({'channel': 'hybrid', 'text': 'changed query', 'limit': 1})

    def test_open_translates_source_drift_for_assessment_invalidation(self):
        tools = self.adapter()
        source_hash = self.sources[self.case]
        request = {'case_id': self.case, 'source_hash': source_hash, 'handles': ['u0001']}
        tools.open_source(request)
        self.assertTrue(tools.verify_source(self.case, source_hash))
        (self.case_dir / self.case).write_bytes(b'drift')
        with self.assertRaises(SourceDrift) as error:
            tools.open_source(request)
        self.assertEqual(error.exception.case_id, self.case)
