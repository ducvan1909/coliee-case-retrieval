"""Offline regressions for the survey queue and bounded A decisions."""
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from pipeline_v2.experiments.context_manager_v2 import source_gate
from pipeline_v2.experiments.context_manager_v2.tests import test_passage_review
from pipeline_v2.experiments.context_manager_v2.tests.test_source_gate import screen
from pipeline_v2.experiments.context_manager_v2.cli import choose
from pipeline_v2.tests.test_m6_adaptive import source
from jsonschema import Draft202012Validator
from pipeline_v2.agent_harness.contracts import TransportError


class SurveyFirstTests(unittest.TestCase):
    def test_real_hargrave_spans_group_and_next_distinct_quote_stays_separate(self):
        case = '021095.txt'
        path = Path('data/task1_train_files_2026/cases') / case
        if not path.exists():
            self.skipTest('Original pilot source is unavailable')
        raw = path.read_bytes()
        digest = sha256(raw).hexdigest()

        def row(handle, start, end, paragraph_span):
            return {'status': 'approved', 'decision': 'search_needed', 'paragraph_handle': handle,
                    'paragraph_span_bytes': paragraph_span, 'visible_span_bytes': [start, end],
                    'source_hash': digest, 'source_ref': f'ref-{start}-{end}',
                    'proposition': {'span_bytes': [start, end], 'text': raw[start:end].decode('utf-8')}}

        reference = b'315 N.R. 175'
        cite_at = raw.index(reference, 7580)
        block_at = raw.rfind(b'\n', 7580, cite_at) + 1
        marks = {
            'hargrave-1': row('5', 3005, 3152, [3005, 3584]),
            'hargrave-2': row('5', 3152, 3205, [3005, 3584]),
            'hargrave-3': row('5', 3205, 3584, [3005, 3584]),
            'first-quote': row('18', 7580, block_at, [7580, 8574]),
            'second-quote': row('18', block_at, 8574, [7580, 8574]),
        }
        marks['second-quote']['a_supports'] = [{
            'role': 'citation', 'case_id': case, 'source_hash': digest,
            'span_bytes': [cite_at, cite_at + len(reference)], 'text': reference.decode()}]
        ctx = {'source_gate': marks}
        paragraphs = [{'handle': '5', 'span_bytes': [3005, 3584]},
                      {'handle': '18', 'span_bytes': [7580, 8574]}]
        source_gate.group_exact_citations(ctx, paragraphs, case, lambda _: raw)
        self.assertEqual(marks['first-quote']['status'], 'approved')
        self.assertEqual(marks['second-quote']['status'], 'approved')
        refs = ['hargrave-1', 'hargrave-2', 'hargrave-3']
        source_gate.group_needs(ctx, refs, 'These three spans refer to the Hargrave order of 10 February.', paragraphs)
        self.assertEqual(marks['hargrave-1']['group_members'], refs)
        self.assertEqual([marks[ref]['status'] for ref in refs], ['approved', 'grouped', 'grouped'])
        self.assertTrue(source_gate.survey_ready(ctx, paragraphs))

    def test_terminal_length_retries_smaller_batch_without_committing(self):
        with TemporaryDirectory() as directory:
            engine, _ = test_passage_review.PassageReviewTests().make_engine(directory)
            engine.survey_first = True
            previous = None
            for limit in (3, 2, 1):
                admitted = engine.prepare()
                branches = admitted['manifest']['schema']['anyOf']
                fields = next(b['properties']['args']['properties'] for b in branches
                              if b['properties']['action']['const'] == 'assess_source_needs')
                self.assertEqual(fields['items']['maxItems'], limit)
                request = engine.state().requests[admitted['request_id']]
                self.assertEqual(request['retry_of'], previous)
                previous = admitted['request_id']
                error = TransportError('modal_incomplete_generation', input_tokens=admitted['input_tokens'],
                                       output_tokens=request['output_token_cap'], latency_ms=1)
                engine.reply(previous, status='error', telemetry=error, error=str(error),
                             transport_metadata={'submission_attempted': True, 'finish_reason': 'length', 'call_id': 'fc-test'})
                self.assertFalse(engine.context().get('source_gate'))
                self.assertEqual(engine.state().actions, 0)
                if limit > 1:
                    self.assertIsNone(engine.state().final)
            self.assertEqual(engine.state().retries, 2)
            self.assertEqual(engine.state().final['stop_reason'], 'failure')

    def test_approved_first_paragraph_keeps_survey_open_until_second_is_screened(self):
        tools = test_passage_review.PassageTools()
        first = 'The Court applied the notice fairness rule in this dispute.'
        tools.a = source('A', first + '\nThe applicant filed a motion.')
        cut = len(first.encode())
        tools.query_paragraphs = ({'handle': 'p000001', 'span_bytes': [0, cut]},
                                  {'handle': 'p000002', 'span_bytes': [cut + 1, len(tools.a.text.encode())]})
        with TemporaryDirectory() as directory:
            engine, _ = test_passage_review.PassageReviewTests().make_engine(directory, tools=tools)
            engine.survey_first = True
            engine.step(lambda p: screen(p, first))
            p = engine.prepare(admit=False)
            self.assertEqual(p['payload']['m6']['source_survey']['phase'], 'survey')
            self.assertNotIn('search_cases_by_issue', [t['name'] for t in p['payload']['available_tools']])
            action = choose(p, 'assess_source_needs')
            action['args'] = {'items': [screen(p, tools.a.text)['args']] * 4}
            self.assertFalse(Draft202012Validator(p['manifest']['schema']).is_valid(action))
            engine.step(lambda q: choose(q, 'assess_source_need', decision='no_search_needed',
                                         paragraph_ref='p000002', proposition_ref='p000002.remaining_visible',
                                         attribution='court', context_complete=True, reason_code='facts',
                                         reason='This span gives procedural history.'))
            self.assertEqual(engine.prepare(admit=False)['payload']['m6']['source_survey']['phase'], 'retrieval')
            self.assertEqual(tools.hybrid.queries, [])

    def test_batch_survey_records_need_then_exposes_search_without_executing_it(self):
        fixture = test_passage_review.PassageReviewTests()
        with TemporaryDirectory() as directory:
            engine, tools = fixture.make_engine(directory)
            engine.survey_first = True
            prepared = engine.prepare(admit=False)
            self.assertEqual(prepared['payload']['m6']['source_survey']['phase'], 'survey')
            self.assertNotIn('search_cases_by_issue', [t['name'] for t in prepared['payload']['available_tools']])
            args = screen(prepared, tools.a.text)['args']
            engine.step({'action': 'assess_source_needs', 'args': {'items': [args]}})
            after = engine.prepare(admit=False)
            self.assertEqual(after['payload']['m6']['source_survey']['phase'], 'retrieval')
            self.assertEqual(tools.hybrid.queries, [])
            self.assertIn('search_cases_by_issue', [t['name'] for t in after['payload']['available_tools']])
            engine.step(lambda p: choose(p, 'search_cases_by_issue'))
            self.assertTrue(tools.hybrid.queries)


if __name__ == '__main__':
    unittest.main()
