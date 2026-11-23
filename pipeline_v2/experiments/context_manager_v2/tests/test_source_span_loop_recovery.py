"""Independent regressions for CM4's source-span recovery contract.

The main fixture uses the real 021095 query source when it is present in the
checkout.  These tests cover protocol and byte provenance; they do not measure
whether a model makes the right legal judgment.
"""
from hashlib import sha256
from pathlib import Path
import unittest

from pipeline_v2.agent_harness.contracts import HarnessError
from pipeline_v2.agent_harness import RunIdentity
from pipeline_v2.experiments.context_manager_v2.cli import choose
from pipeline_v2.experiments.context_manager_v2.engine import Engine
from pipeline_v2.experiments.context_manager_v2 import source_gate
from pipeline_v2.experiments.context_manager_v2.tests import test_engine
from pipeline_v2.tests.test_m6_adaptive import Tools, source


QUERY_CASE = '021095.txt'
FIRST_PARAGRAPH_END = 927


def _query_bytes():
    path = Path(__file__).resolve().parents[4] / 'data' / 'task1_train_files_2026' / 'cases' / QUERY_CASE
    if path.exists():
        return path.read_bytes()
    # Portable fallback preserves the same behaviors where the private corpus
    # is not installed. The primary checkout path above exercises original text.
    return (b'[1]\r\nThe Court considered the Order and the motion for leave. '
            b'The applicants then filed a reply affidavit. The Court set out '
            b'the procedural history and the requested relief.\r\n'
            b'Failure to Consider\r\n[21]\r\n')


def _payload(raw, span=None, *, handle='p000001', coverage='full'):
    if span is None:
        span = [0, len(raw)]
    excerpt = source('A', raw.decode('utf-8')).to_record()
    left, right = span
    paragraph = {
        'paragraph_handle': handle,
        'source_ref': excerpt['ref'],
        'source_hash': excerpt['source_hash'],
        'span_bytes': [left, right],
        'paragraph_span_bytes': [left, right],
        'paragraph_coverage': coverage,
    }
    return {
        'query_id': 'A',
        'query_source_hash': excerpt['source_hash'],
        'excerpts': [excerpt],
        'current_payload_source_refs': [excerpt['ref']],
        'm6': {
            'a_paragraphs': {handle: paragraph},
            'source_gate_segments': {},
        },
    }, excerpt


def _args(**overrides):
    args = {
        'paragraph_ref': 'p000001',
        'decision': 'no_search_needed',
        'attribution': 'unknown',
        'reason_code': 'procedural_history',
        'reason': 'The selected words describe procedural history.',
        'context_complete': True,
        'sufficient_for_search': True,
    }
    args.update(overrides)
    return args


def _bound_engine(directory, raw):
    tools = Tools()
    tools.a = source('A', raw.decode('utf-8'))
    tools.query_paragraphs = ({'handle': 'p000001', 'span_bytes': [0, FIRST_PARAGRAPH_END]},)
    identity = RunIdentity('source-span-recovery', 'A', tools.a.source_hash, 'corpus', 'index',
                           'profile', 'model', 'prompt', 'tools', 'seed')
    engine = Engine(directory, identity=identity, tools=tools, count_tokens=test_engine.count,
                    raw_reader=lambda case: raw if case == 'A' else tools.b.text.encode('utf-8'),
                    gate_enabled=True, dual_search=object())
    return engine


def _negative_ref_action(prepared, ref):
    return choose(prepared, 'assess_source_need', decision='no_search_needed',
                  proposition_ref=ref, attribution='unknown', reason_code='procedural_history',
                  reason='The selected span does not need a source case.', context_complete=True)


class SourceSpanLoopRecoveryTests(unittest.TestCase):
    def test_real_lettered_grounds_keep_individual_refs_without_bulk_negative(self):
        if not self.has_real_corpus:
            self.skipTest('Requires the original pilot case')
        for paragraph, span in (('p000001', [0, 927]), ('p000002', [929, 2551])):
            payload, _ = _payload(self.raw, span, handle=paragraph)
            refs = source_gate.segments(payload, {}, bound=True)
            self.assertEqual(f'{paragraph}.remaining_visible' in refs, paragraph == 'p000001')
            if paragraph == 'p000002':
                self.assertTrue(any(row['preview'].startswith('(a)') for row in refs.values()))
                self.assertTrue(any(row['preview'].startswith('(b)') for row in refs.values()))

    @classmethod
    def setUpClass(cls):
        cls.raw = _query_bytes()
        cls.has_real_corpus = len(cls.raw) == 48635 and sha256(cls.raw).hexdigest() == (
            'a2d761afdaad90294cd8cc595dee8c3d2229902c8b0b0570beea04b6be2da3bf')

    def test_schema_variants_require_one_selector_except_context_request(self):
        payload, _ = _payload(self.raw[:FIRST_PARAGRAPH_END], [0, FIRST_PARAGRAPH_END])
        segments = source_gate.segments(payload, bound=True)
        variants = source_gate.bound_assessment_variants(['p000001'], segments)
        self.assertTrue(variants)

        for fields, required in variants:
            selectors = [key for key in ('proposition_ref', 'proposition_quote') if key in fields]
            decision = fields['decision']['enum'][0]
            with self.subTest(decision=decision, selectors=selectors):
                self.assertFalse({'proposition_ref', 'proposition_quote'} <= set(fields))
                if decision in ('search_needed', 'no_search_needed'):
                    self.assertEqual(len(selectors), 1)
                    self.assertIn(selectors[0], required)
                else:
                    # Reading more may retain an unresolved draft without making
                    # an assessment decision for a span.
                    self.assertLessEqual(len(selectors), 1)
                    if selectors:
                        self.assertIn(selectors[0], required)

    def test_host_rejects_missing_or_competing_span_selectors(self):
        raw = self.raw[:FIRST_PARAGRAPH_END]
        payload, _ = _payload(raw, [0, len(raw)])
        payload['m6']['source_gate_segments'] = source_gate.segments(payload, bound=True)
        with self.assertRaisesRegex(HarnessError, 'Choose one offered proposition_ref'):
            source_gate.evaluate_bound(payload, _args(), [{'handle': 'p000001', 'span_bytes': [0, len(raw)]}])
        ref = next(iter(payload['m6']['source_gate_segments']))
        with self.assertRaisesRegex(HarnessError, 'Choose exactly one'):
            source_gate.evaluate_bound(payload, _args(proposition_ref=ref,
                proposition_quote='The Court considered this sentence.'),
                [{'handle': 'p000001', 'span_bytes': [0, len(raw)]}])
        valid_ref = next(iter(payload['m6']['source_gate_segments']))
        accepted = source_gate.evaluate_bound(payload,
            _args(proposition_ref=valid_ref),
            [{'handle': 'p000001', 'span_bytes': [0, len(raw)]}])
        self.assertEqual(accepted['status'], 'screened')
        self.assertIsNotNone(accepted['proposition'])

    def test_engine_missing_span_retries_with_refs_then_settles_only_remaining_bytes(self):
        # The test itself owns a short-lived directory through the engine's
        # temporary DB, and never calls a model or retrieval provider.
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as directory:
            engine = _bound_engine(directory, self.raw)
            engine.prepare(admit=False)
            missing = {'action': 'assess_source_need', 'args': {
                'paragraph_ref': 'p000001', 'decision': 'no_search_needed',
                'attribution': 'unknown', 'reason_code': 'procedural_history',
                'reason': 'This paragraph describes procedure.', 'context_complete': True}}
            engine.step(lambda _: missing)

            receipt = engine.state().last_receipt
            self.assertEqual(receipt['status'], 'malformed')
            self.assertEqual(receipt['cm_tool_repair']['code'], 'source_span_required')
            self.assertEqual(engine.context().get('source_gate', {}), {})
            recovered = engine.prepare(admit=False)
            self.assertTrue(recovered['payload']['m6']['source_gate_segments'])
            first_ref = next(ref for ref, row in recovered['payload']['m6']['source_gate_segments'].items()
                             if row.get('proposition_selectable', True)
                             and row['span_bytes'] == [0, 239])
            engine.step(lambda p: _negative_ref_action(p, first_ref))

            second = engine.prepare(admit=False)
            second_ref = next(ref for ref, row in second['payload']['m6']['source_gate_segments'].items()
                              if row.get('proposition_selectable', True)
                              and row['span_bytes'] == [239, 285])
            engine.step(lambda p: _negative_ref_action(p, second_ref))

            remaining = engine.prepare(admit=False)
            remaining_ref = 'p000001.remaining_visible'
            entry = remaining['payload']['m6']['source_gate_segments'][remaining_ref]
            self.assertEqual(entry['selected_spans'], [[285, FIRST_PARAGRAPH_END]])
            engine.step(lambda p: _negative_ref_action(p, remaining_ref))

            final = engine.prepare(admit=False)
            internal_payload = {**final['payload'], 'm6': final['manifest']['dispatch_m6']}
            self.assertNotIn('p000001', source_gate.screening_choices(internal_payload, engine.context()))
            rows = list(engine.context()['source_gate'].values())
            self.assertEqual(len(rows), 3)
            self.assertEqual(rows[-1]['settled_spans'], [[285, FIRST_PARAGRAPH_END]])

    def test_quote_mismatch_returns_bounded_confirmable_source_refs(self):
        raw = self.raw[:FIRST_PARAGRAPH_END]
        payload, excerpt = _payload(raw, [0, len(raw)])
        payload['m6']['source_gate_segments'] = source_gate.segments(payload, bound=True)
        visible = raw.decode('utf-8')
        # The quote is based on the real opening paragraph when available and
        # intentionally changes a source word, as in the pilot's bad quote.
        if self.has_real_corpus:
            quote = 'This motion by the Respondent is an appeal of the Order by way of Endorsement'
            quote = quote.replace('Order', '(Order)')
        else:
            quote = 'The Court considered the Order and the motion for leave'.replace('Order', '(Order)')
        self.assertNotIn(quote, visible)

        outcome = source_gate.evaluate_bound(payload,
            _args(decision='search_needed', proposition_quote=quote),
            [{'handle': 'p000001', 'span_bytes': [0, len(raw)]}])
        choices = outcome['resolution_choices']
        self.assertEqual(outcome['decision'], 'need_more_context')
        self.assertGreaterEqual(len(choices), 1)
        self.assertLessEqual(len(choices), 3)
        for choice in choices:
            start, end = choice['span_bytes']
            origin = excerpt['span_bytes'][0]
            self.assertGreaterEqual(start, origin)
            self.assertLess(end, origin + len(excerpt['text'].encode('utf-8')) + 1)
            self.assertEqual(choice['text'], excerpt['text'].encode('utf-8')[start-origin:end-origin].decode('utf-8'))
            self.assertGreater(end, start)

        # Confirm a literal source suggestion. A long quote may produce a span
        # that crosses sentence refs, so the controller exposes a dedicated
        # choice_ref instead of pretending it equals one initial segment.
        confirmed = source_gate.evaluate_bound(payload,
            _args(decision='search_needed', proposition_quote=choices[0]['text']),
            [{'handle': 'p000001', 'span_bytes': [0, len(raw)]}])
        self.assertEqual(confirmed['status'], 'approved')
        self.assertEqual(confirmed['proposition']['span_bytes'], choices[0]['span_bytes'])
        self.assertEqual(confirmed['proposition']['text'], choices[0]['text'])

    def test_literal_quote_recovery_survives_public_tool_filter(self):
        from tempfile import TemporaryDirectory
        from pipeline_v2.experiments.context_manager_v2.cli import choose

        if not self.has_real_corpus:
            self.skipTest('Requires the original case used in the pilot')
        quote = self.raw[:FIRST_PARAGRAPH_END].decode('utf-8').replace('("Order")', '(Order)')
        with TemporaryDirectory() as directory:
            engine = _bound_engine(directory, self.raw)
            engine.step({'action': 'assess_source_need', 'args': _args(proposition_quote=quote)})
            self.assertTrue(all(row['status'] == 'unresolved' for row in engine.context()['source_gate'].values()))
            engine.step(lambda p: choose(p, 'choose_source_span'))
            self.assertTrue(any(row['status'] == 'screened' for row in engine.context()['source_gate'].values()))

    def test_remaining_visible_decision_covers_only_unsettled_bytes(self):
        raw = self.raw[:FIRST_PARAGRAPH_END]
        payload, _ = _payload(raw, [0, len(raw)])
        settled = [[0, 239], [239, 285]]
        context = {'source_gate': {
            'T005': {'status': 'screened', 'source_hash': payload['query_source_hash'],
                     'paragraph_handle': 'p000001', 'settled_spans': [settled[0]]},
            'T021': {'status': 'screened', 'source_hash': payload['query_source_hash'],
                     'paragraph_handle': 'p000001', 'settled_spans': [settled[1]]},
        }}
        issued = source_gate.segments(payload, context, bound=True)
        ref = 'p000001.remaining_visible'
        self.assertIn(ref, issued)
        expected_gap = [[285, len(raw)]]
        self.assertEqual(issued[ref]['selected_spans'], expected_gap)
        self.assertEqual(issued[ref]['byte_count'], len(raw) - 285)
        # The selected spans must not fill the already reviewed bytes or run
        # past paragraph [1] into whitespace / paragraph [2].
        self.assertTrue(all(left >= 285 and right <= FIRST_PARAGRAPH_END
                            for left, right in issued[ref]['selected_spans']))

        payload['m6']['source_gate_segments'] = issued
        result = source_gate.evaluate_bound(payload,
            _args(proposition_ref=ref, decision='no_search_needed'),
            [{'handle': 'p000001', 'span_bytes': [0, len(raw)]}])
        self.assertEqual(result['status'], 'screened')
        self.assertEqual(result['settled_spans'], expected_gap)

    def test_heading_quote_cannot_authorize_search(self):
        # The title is taken from 021095 [20], immediately before [21].
        raw = self.raw
        title_start = raw.find(b'Failure to Consider')
        self.assertGreaterEqual(title_start, 0)
        title_end = title_start + len(b'Failure to Consider')
        left = max(0, title_start - 10)
        right = min(len(raw), title_end + 30)
        payload, _ = _payload(raw, [left, right])
        payload['m6']['known_heading_spans'] = [[title_start, title_end]]
        payload['m6']['source_gate_segments'] = source_gate.segments(payload, bound=True)
        query_paragraphs = [{'handle': 'p000001', 'span_bytes': [left, right]}]

        result = source_gate.evaluate_bound(payload,
            _args(decision='search_needed', proposition_quote='Failure to Consider'), query_paragraphs)
        self.assertIn('heading alone cannot authorize', result['validation_message'])
        self.assertNotEqual(result['status'], 'approved')
        self.assertIsNone(result.get('proposition'))

    def test_legacy_unbound_gate_still_accepts_paragraph_level_negative(self):
        raw = b'The applicant filed a motion and requested an extension.'
        payload, _ = _payload(raw)
        args = _args(decision='no_search_needed')
        result = source_gate.evaluate(payload, args, [{'handle': 'p000001', 'span_bytes': [0, len(raw)]}])
        self.assertEqual(result['status'], 'screened')
        self.assertEqual(result['decision'], 'no_search_needed')
        self.assertIsNone(result['proposition'])


if __name__ == '__main__':
    unittest.main()
