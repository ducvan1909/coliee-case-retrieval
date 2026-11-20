"""Model screening decisions are bound to source spans without semantic overrides."""
import unittest

from pipeline_v2.experiments.context_manager_v2.source_gate import evaluate, segments
from pipeline_v2.tests.test_m6_adaptive import source


class SourceGroundingTests(unittest.TestCase):
    def assess(self, text, *, decision='search_needed', adjacent=None, complete=True):
        raw = source('A', text + ('\n' + adjacent if adjacent else ''))
        row = raw.to_record()
        cut = len(text.encode('utf-8'))
        spans = [[0, cut]] + ([[cut + 1, raw.span_bytes[1]]] if adjacent else [])
        paragraphs = {f'p{i}': {'paragraph_handle': f'p{i}', 'source_ref': row['ref'],
                               'source_hash': raw.source_hash, 'span_bytes': span,
                               'paragraph_span_bytes': span, 'paragraph_coverage': 'full'}
                      for i, span in enumerate(spans, 1)}
        payload = {'query_id': 'A', 'query_source_hash': raw.source_hash, 'excerpts': [row],
                   'current_payload_source_refs': [row['ref']], 'm6': {'a_paragraphs': paragraphs}}
        payload['m6']['source_gate_segments'] = segments(payload)
        issued = payload['m6']['source_gate_segments']
        args = dict(paragraph_ref='p1', decision=decision, attribution='court',
                    reason_code='masked_authority' if decision == 'search_needed' else 'procedural_history',
                    reason='The paragraph reports an earlier source.', context_complete=complete,
                    proposition_ref=next(iter(issued)), signal_ref=list(issued)[-1])
        return evaluate(payload, args, [{'handle': ref} for ref in paragraphs])

    def test_local_order_keeps_model_decision(self):
        text = 'The earlier order in this case resolved costs: <FRAGMENT_SUPPRESSED> para.31;'
        for proposed, expected in (('search_needed', 'approved'), ('no_search_needed', 'screened')):
            with self.subTest(proposed=proposed):
                result = self.assess(text, decision=proposed)
                self.assertEqual(result['status'], expected)
                self.assertEqual(result['decision'], proposed)
                self.assertEqual(result['proposed_decision'], proposed)
        self.assertEqual(self.assess(text, complete=False)['status'], 'unresolved')

    def test_weak_signal_keeps_positive_decision(self):
        result = self.assess('The applicant filed a motion on Monday.')
        self.assertEqual(result['decision'], 'search_needed')
        self.assertEqual(result['status'], 'approved')

    def test_citation_keeps_negative_decision(self):
        result = self.assess('The fairness rule in 2010 FC 413 applies.', decision='no_search_needed')
        self.assertEqual(result['decision'], 'no_search_needed')
        self.assertEqual(result['status'], 'screened')

    def test_adjacent_signal_remains_bound_to_issued_span(self):
        local = 'The earlier order in this case resolved costs.'
        result = self.assess(local, adjacent='The fairness rule in 2010 FC 413 applies.')
        self.assertEqual(result['status'], 'approved')
        self.assertEqual(result['signal']['text'], 'The fairness rule in 2010 FC 413 applies.')


if __name__ == '__main__':
    unittest.main()
