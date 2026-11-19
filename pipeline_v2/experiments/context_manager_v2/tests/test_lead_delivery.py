"""Regression for the live read-neighbor / pending-assessment loop."""
from hashlib import sha256
from tempfile import TemporaryDirectory
import unittest

from jsonschema import Draft202012Validator
from pipeline_v2.experiments.context_manager_v2.tests.view_helpers import wire_ref

from pipeline_v2.agent_harness import RunIdentity, SourceExcerpt, ToolResult
from pipeline_v2.experiments.context_manager_v2.engine import Engine
from pipeline_v2.experiments.context_manager_v2.cli import choose
from pipeline_v2.m6 import AdaptiveConfig
from pipeline_v2.tests.test_m6_adaptive import Tools


class LeadTools(Tools):
    def __init__(self):
        super().__init__()
        raw = b'Neighbor context. ' * 60 + b'Actual procedural reply affidavit lead. ' * 70
        self.b = SourceExcerpt('B', sha256(raw).hexdigest(), (0, len(raw)), raw.decode(), sha256(raw).hexdigest())
        self.opens = 0

    def search_corpus(self, args):
        return ToolResult({'hits': [{'case_id': 'B', 'rank': 1, 'span_bytes': [1100, 1200],
            'open_ref': {'case_id': 'B', 'source_hash': self.b.source_hash, 'passage_ids': ['B-hit']}}]}, candidates=('B',))

    def open_source(self, args):
        self.opens += 1
        return ToolResult({'case_id': 'B', 'source_hash': self.b.source_hash,
            'hit_refs': [{'kind': 'passage', 'ref': 'B-hit', 'span_bytes': [1100, 1200],
                          'delivered_spans': [[1100, 1200]]}]},
            (self.b.slice(0, 300), self.b.slice(1000, 1600)), ('B',))


def count(body):
    return len(body) // 6 + 100


class LeadDeliveryTests(unittest.TestCase):
    def make(self, path):
        tools = LeadTools()
        identity = RunIdentity('lead-delivery', 'A', tools.a.source_hash, 'c', 'i', 'p', 'm', 'p', 't', 'z')
        kwargs = dict(identity=identity, tools=tools, count_tokens=count,
            raw_reader=lambda case: {'A': tools.a, 'B': tools.b}[case].text.encode(),
            config=AdaptiveConfig(channel='case_bm25'))
        e = Engine(path, **kwargs)
        e.step(lambda p: choose(p, 'search_cases_by_issue', issue='procedural fairness',
                               source_proposition='A needs the source of a procedural rule.'))
        e.step(lambda p: choose(p, 'open_retrieved_passage'))
        return e, tools, kwargs

    def test_first_B_window_is_requested_hit_and_neighbor_stays_reachable(self):
        with TemporaryDirectory() as d:
            e, tools, kwargs = self.make(d)
            p = e.prepare(admit=False)
            b = next(r for r in p['payload']['excerpts'] if r['case_id'] == 'B')
            self.assertLessEqual(b['span_bytes'][0], 1100)
            self.assertGreaterEqual(b['span_bytes'][1], 1200)
            self.assertNotEqual(tuple(b['span_bytes']), (0, 300))
            self.assertEqual(b['text'].encode(), tools.b.text.encode()[b['span_bytes'][0]:b['span_bytes'][1]])
            roots = [r for r in e.state().catalog.values() if r['case_id'] == 'B']
            self.assertEqual({tuple(r['span_bytes']) for r in roots}, {(0, 300), (1000, 1600)})
            self.assertTrue(any(v['kind'] == 'continuation' and e.state().catalog[v['ref']]['case_id'] == 'B'
                                and e.state().catalog[v['ref']]['span_bytes'][0] == 0
                                for v in p['manifest']['handles'].values()))
            reopened = Engine(d, **kwargs)
            q = reopened.prepare(admit=False)
            self.assertEqual(p['payload']['excerpts'], q['payload']['excerpts'])

    def test_missing_feedback_preserves_reported_request_and_avoids_same_B_reopen(self):
        with TemporaryDirectory() as d:
            e, tools, _ = self.make(d)
            missing = 'Need later raw paragraphs of A to determine whether it cites B.'
            e.step(lambda p: choose(p, 'assess_case_link', case_relation='unknown',
                passage_location='unresolved', reason='The current A excerpt is incomplete.', missing_evidence=[missing]))
            self.assertEqual(e.context()['stage'], 'missing_evidence')
            p = e.prepare(admit=False)
            feedback = p['payload']['last_action_feedback']
            self.assertIn(missing, str(feedback))
            self.assertTrue(feedback.get('guidance'))
            self.assertNotEqual(feedback.get('missing_reason'), 'reported_missing_evidence')
            names = [t['name'] for t in p['payload']['available_tools']]
            self.assertIn('continue_raw_evidence', names)
            self.assertIn('show_context_page', names)
            self.assertIn('finish_case_review', names)
            self.assertNotIn('read_case_passages', names)  # Only known-open B is on this page.
            self.assertEqual(tools.opens, 1)
            validator = Draft202012Validator(p['manifest']['schema'])
            for option in feedback['evidence_options'] + feedback['navigation_options']:
                self.assertTrue(validator.is_valid({'action': option['tool'], 'args': option['args']}))
            self.assertTrue(any(option['side'] == 'candidate case' and option['tool'] == 'continue_raw_evidence'
                                for option in feedback['evidence_options']))
            # Continue to the queued neighbor through its issued handle, no new source call.
            def neighbor(p):
                ref = next(k for k, v in p['manifest']['handles'].items() if v['kind'] == 'continuation'
                    and e.state().catalog[v['ref']]['case_id'] == 'B'
                    and e.state().catalog[v['ref']]['span_bytes'][0] == 0)
                return choose(p, 'continue_raw_evidence', context_ref=wire_ref(p, ref))
            e.step(neighbor)
            q = e.prepare(admit=False)
            b = next(r for r in q['payload']['excerpts'] if r['case_id'] == 'B')
            self.assertEqual(b['span_bytes'][0], 0)
            self.assertEqual(tools.opens, 1)


if __name__ == '__main__':
    unittest.main()
