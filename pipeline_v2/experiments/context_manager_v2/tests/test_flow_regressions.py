"""End-to-end regressions for CM4 review completion, reading, and duplicate focus."""
from hashlib import sha256
import json
from tempfile import TemporaryDirectory
import unittest

from pipeline_v2.agent_harness import RunIdentity, SourceExcerpt, ToolResult
from pipeline_v2.agent_harness.ledger import RunState
from pipeline_v2.experiments.context_manager_v2.cli import choose
from pipeline_v2.experiments.context_manager_v2.engine import Engine
from pipeline_v2.experiments.context_manager_v2.read_options import next_unread_expansion
from pipeline_v2.experiments.context_manager_v2.tests import test_engine, test_search_reuse
from pipeline_v2.experiments.context_manager_v2.tests.view_helpers import wire_ref
from pipeline_v2.tests.test_m6_adaptive import Tools, source

ISSUE = test_search_reuse.ISSUE
choose_wire_action = test_search_reuse.choose


def action_names(prepared):
    return {branch['properties']['action']['const']
            for branch in prepared['manifest']['schema']['anyOf']}


def finish_reasons(prepared):
    branch = next(branch for branch in prepared['manifest']['schema']['anyOf']
                  if branch['properties']['action']['const'] == 'finish_case_review')
    return branch['properties']['args']['properties']['reason']['enum']


class MergedLeadTools(Tools):
    """Return one B source root whose actual retrieval lead lies near its tail."""

    def __init__(self, lead_span):
        super().__init__()
        raw = b''.join(bytes([65 + (index % 26)]) for index in range(1024))
        self.b = SourceExcerpt('B', sha256(raw).hexdigest(), (0, len(raw)),
                               raw.decode('ascii'), sha256(raw).hexdigest())
        self.lead_span = tuple(lead_span)
        self.opens = 0

    def search_corpus(self, args):
        return ToolResult({'hits': [{
            'case_id': 'B',
            'rank': 1,
            'span_bytes': list(self.lead_span),
            'open_ref': {'case_id': 'B', 'source_hash': self.b.source_hash,
                         'passage_ids': ['B-lead']},
        }]}, candidates=('B',))

    def open_source(self, args):
        self.opens += 1
        start, end = self.lead_span
        return ToolResult({'case_id': 'B', 'source_hash': self.b.source_hash,
                           'hit_refs': [{'kind': 'passage', 'ref': 'B-lead',
                                         'span_bytes': [start, end],
                                         'delivered_spans': [[start, end]]}]},
                          (self.b,), ('B',))


class PagedLeadTools(MergedLeadTools):
    """Fetch one target across two reader pages before the payload is fitted."""

    def __init__(self):
        super().__init__((100, 900))

    def page(self, left, right, pending, continuation=None):
        start, end = self.lead_span
        text = self.b.text[left:right]
        excerpt = SourceExcerpt('B', self.b.source_hash, (left, right), text,
                                sha256(text.encode()).hexdigest())
        observation = {'case_id': 'B', 'source_hash': self.b.source_hash,
                       'hit_refs': [{'kind': 'passage', 'ref': 'B-lead', 'span_bytes': [start, end],
                                     'delivered_spans': [[max(left, start), min(right, end)]],
                                     'pending_spans': pending}]}
        if continuation:
            observation['continuation'] = continuation
        self.opens += 1
        return ToolResult(observation, (excerpt,), ('B',))

    def open_source(self, args):
        return self.page(0, 512, [[512, 900]], {**args, 'cursor': 'next-lead-page'})

    def expand_source(self, args):
        if args['cursor'] != 'next-lead-page':
            raise ValueError('Unexpected reader cursor')
        return self.page(512, 1024, [])


class OverlappingPageTools(PagedLeadTools):
    def __init__(self, has_unread_tail):
        super().__init__()
        self.has_unread_tail = has_unread_tail

    def preview_expansion(self, args):
        return self.expand_source(args)

    def expand_source(self, args):
        if args['cursor'] == 'next-lead-page':
            next_page = {**args, 'cursor': 'unread-tail'} if self.has_unread_tail else None
            return self.page(128, 512, [[512, 900]] if next_page else [], next_page)
        if args['cursor'] != 'unread-tail':
            raise ValueError('Unexpected reader cursor')
        return self.page(400, 1024, [])


def make_lead_engine(directory, lead_span, max_b_bytes, tools=None):
    tools = tools or MergedLeadTools(lead_span)

    def count_tokens(body):
        payload = json.loads(body)
        candidate = next((row for row in payload['excerpts'] if row['case_id'] == 'B'), None)
        if candidate and len(candidate['text'].encode('utf-8')) > max_b_bytes:
            return 9000
        return len(body) // 6 + 100

    identity = RunIdentity('lead-window-regression', 'A', tools.a.source_hash,
                           'corpus', 'index', 'profile', 'model', 'prompt',
                           'tools', 'tokenizer')
    engine = Engine(directory, identity=identity, tools=tools, count_tokens=count_tokens,
                    raw_reader=lambda case: {'A': tools.a.text.encode(),
                                             'B': tools.b.text.encode()}[case])
    engine.step(lambda prepared: choose(prepared, 'search_cases_by_issue',
        issue='procedural affidavit reply',
        source_proposition='The query case needs the source for a reply affidavit rule.'))
    engine.step(lambda prepared: choose(prepared, 'open_retrieved_passage'))
    return engine, tools


def continue_candidate(prepared, engine, offset):
    ref = next(key for key, handle in prepared['manifest']['handles'].items()
               if handle['kind'] == 'continuation'
               and engine.state().catalog[handle['ref']]['case_id'] == 'B'
               and handle['offset'] == offset)
    return choose(prepared, 'continue_raw_evidence', context_ref=wire_ref(prepared, ref))


class FlowRegressionTests(unittest.TestCase):
    def test_expansion_skips_new_separator_and_keeps_reachable_text(self):
        original = source('B', 'First passage.\r\nSecond passage.')
        first = len('First passage.')
        second = first + 2
        state = RunState()
        shown = original.slice(0, first).to_record()
        state.catalog[shown['ref']] = shown
        separator = original.slice(first, second)
        text = original.slice(second, original.span_bytes[1])
        next_page = {'cursor': 'text'}
        pages = {'separator': ToolResult({'continuation': next_page}, (separator,)),
                 'text': ToolResult({}, (text,))}
        read = lambda binding: pages[binding['cursor']]
        self.assertEqual(next_unread_expansion(read, state, {'cursor': 'separator'}, {}), pages['text'])
        pages['separator'] = ToolResult({}, (separator,))
        self.assertIsNone(next_unread_expansion(read, state, {'cursor': 'separator'}, {}))

    def test_deferred_pair_can_resume_at_unseen_bytes_already_fetched(self):
        with TemporaryDirectory() as directory:
            engine, _ = make_lead_engine(directory, (0, 400), max_b_bytes=256)
            first = engine.prepare(admit=False)
            before = next(row['span_bytes'] for row in first['payload']['excerpts'] if row['case_id'] == 'B')
            engine.step(lambda p: choose(p, 'record_missing_evidence', reason='The lead continues beyond the visible window.'))
            engine.step(lambda p: choose(p, 'defer_case_pair', reason='The lead continues beyond the visible window.'))
            engine.step(lambda p: choose(p, 'show_context_page',
                page_ref=p['payload']['m6']['cm_page']['controls']['parked']))
            engine.step(lambda p: choose(p, 'resume_pair_evidence'))
            after = next(row['span_bytes'] for row in engine.prepare(admit=False)['payload']['excerpts'] if row['case_id'] == 'B')
            self.assertEqual(after[0], before[1])
            self.assertFalse(engine.context()['deferred_pairs'])

    def test_duplicate_native_pages_are_hidden_or_advanced_to_new_raw(self):
        for has_unread_tail in (False, True):
            with self.subTest(has_unread_tail=has_unread_tail), TemporaryDirectory() as directory:
                tools = OverlappingPageTools(has_unread_tail)
                engine, _ = make_lead_engine(directory, tools.lead_span, max_b_bytes=1024, tools=tools)
                before = engine.events()
                prepared = engine.prepare(admit=False)
                self.assertEqual(engine.events(), before, 'Preview must not admit or execute an action')
                self.assertEqual('read_more_context' in action_names(prepared), has_unread_tail)
                self.assertEqual(bool(prepared['manifest']['dispatch_m6']['expansions']), has_unread_tail)
                if has_unread_tail:
                    engine.step(lambda turn: choose(turn, 'read_more_context'))
                    result = engine.events()[-1]['result']
                    self.assertEqual([row['span_bytes'] for row in result['excerpts']], [[512, 1024]])

    def test_reader_cursor_and_payload_continuations_deliver_complete_lead(self):
        with TemporaryDirectory() as directory:
            tools = PagedLeadTools()
            engine, _ = make_lead_engine(directory, tools.lead_span, max_b_bytes=256, tools=tools)
            first = engine.prepare(admit=False)
            self.assertNotIn('assess_case_link', action_names(first))
            self.assertIn('read_more_context', action_names(first))
            self.assertNotIn('read_case_passages', action_names(first))
            engine.step(lambda prepared: choose(prepared, 'read_more_context'))
            self.assertNotIn('assess_case_link', action_names(engine.prepare(admit=False)))
            for _ in range(4):
                if 'assess_case_link' in action_names(engine.prepare(admit=False)):
                    break
                engine.step(lambda prepared: choose(prepared, 'continue_raw_evidence'))
            else:
                self.fail('Lead did not reach assessment after its reader and payload continuations')
            self.assertEqual(tools.opens, 2)

    def test_completion_tracks_each_retrieved_need_candidate_pair(self):
        helper = test_search_reuse.SearchReuseTests()
        reader = test_engine.EngineTests()
        with TemporaryDirectory() as directory:
            engine, _, _ = helper.make(directory)

            helper.search(engine, 'p000001')
            engine.step(lambda prepared: choose_wire_action(
                prepared, 'read_case_passages', focus=ISSUE))
            engine.step(lambda prepared: reader.action(prepared, 'assess_case_link'))

            # A second A anchor creates a distinct need and reuses the committed
            # retrieval result, so B now requires an assessment for each need.
            engine.step(lambda prepared: choose_wire_action(
                prepared, 'show_context_page',
                page_ref=prepared['payload']['m6']['cm_page']['controls']['query']))
            engine.step(lambda prepared: choose_wire_action(prepared, 'read_more_context'))
            helper.search(engine, 'p000002')

            pending = engine.prepare(admit=False)
            progress = pending['payload']['last_action_feedback']['review_progress']
            self.assertEqual(progress['retrieved_pairs'], 2)
            self.assertEqual(progress['accepted_pairs'], 1)
            self.assertEqual(progress['unreviewed_pairs'], 1)
            self.assertFalse(progress['complete_policy_allowed'])
            self.assertNotIn('complete_policy', finish_reasons(pending))

            engine.step(lambda prepared: choose_wire_action(
                prepared, 'read_case_passages', focus=ISSUE))
            engine.step(lambda prepared: reader.action(prepared, 'assess_case_link'))

            completed = engine.prepare(admit=False)
            progress = completed['payload']['last_action_feedback']['review_progress']
            self.assertEqual(progress['retrieved_pairs'], 2)
            self.assertEqual(progress['accepted_pairs'], 2)
            self.assertEqual(progress['unreviewed_pairs'], 0)
            self.assertTrue(progress['complete_policy_allowed'])
            self.assertIn('complete_policy', finish_reasons(completed))

    def test_initial_read_window_contains_the_retrieval_lead(self):
        with TemporaryDirectory() as directory:
            engine, tools = make_lead_engine(directory, (800, 900), max_b_bytes=512)
            prepared = engine.prepare(admit=False)
            candidate = next(row for row in prepared['payload']['excerpts']
                             if row['case_id'] == 'B')
            left, right = candidate['span_bytes']
            self.assertLessEqual(left, 800)
            self.assertGreaterEqual(right, 900)
            self.assertEqual(candidate['text'].encode('utf-8'),
                             tools.b.text.encode('utf-8')[left:right])
            self.assertIn('assess_case_link', action_names(prepared))
            self.assertEqual(tools.opens, 1)

    def test_partial_long_lead_stays_unassessable_and_earlier_bytes_remain_reachable(self):
        with TemporaryDirectory() as directory:
            engine, tools = make_lead_engine(directory, (300, 900), max_b_bytes=512)
            prepared = engine.prepare(admit=False)
            candidate = next(row for row in prepared['payload']['excerpts']
                             if row['case_id'] == 'B')
            left, right = candidate['span_bytes']
            self.assertLessEqual(left, 300)
            self.assertGreater(right, 300)
            self.assertLess(right, 900)
            self.assertNotIn('assess_case_link', action_names(prepared))
            self.assertIn('continue_raw_evidence', action_names(prepared))

            engine.step(lambda current: continue_candidate(current, engine, right))
            tail = engine.prepare(admit=False)
            tail_excerpt = next(row for row in tail['payload']['excerpts']
                                if row['case_id'] == 'B')
            self.assertEqual(tail_excerpt['span_bytes'][0], right)
            self.assertEqual(tail_excerpt['text'].encode('utf-8'),
                             tools.b.text.encode('utf-8')[right:tail_excerpt['span_bytes'][1]])
            self.assertIn('continue_raw_evidence', action_names(tail))
            prefix = next(handle['offset'] for handle in tail['manifest']['handles'].values()
                          if handle['kind'] == 'continuation'
                          and engine.state().catalog[handle['ref']]['case_id'] == 'B'
                          and handle['offset'] < 300)
            self.assertEqual(prefix, 0)
            engine.step(lambda current: continue_candidate(current, engine, prefix))
            earlier = engine.prepare(admit=False)
            earlier_excerpt = next(row for row in earlier['payload']['excerpts']
                                   if row['case_id'] == 'B')
            self.assertEqual(earlier_excerpt['span_bytes'][0], 0)
            self.assertEqual(earlier_excerpt['text'].encode('utf-8'), tools.b.text.encode('utf-8')[
                :earlier_excerpt['span_bytes'][1]])
            self.assertEqual(tools.opens, 1)

    def test_duplicate_focus_is_suppressed_without_blocking_a_new_focus(self):
        helper = test_search_reuse.SearchReuseTests()
        reader = test_engine.EngineTests()
        with TemporaryDirectory() as directory:
            engine, backend, _ = helper.make(directory)
            tools = engine.harness.m3
            helper.search(engine)
            first_need = engine.context()['need_id']

            engine.step(lambda prepared: choose_wire_action(
                prepared, 'read_case_passages', focus='procedural fairness'))
            opens_after_first_read = len([row for row in tools.reads if row[0] == 'open'])
            engine.step(lambda prepared: choose_wire_action(
                prepared, 'read_case_passages', focus='  procedural   fairness  '))

            result = engine.events()[-1]
            self.assertEqual(result['status'], 'duplicate')
            self.assertEqual(len([row for row in tools.reads if row[0] == 'open']),
                             opens_after_first_read)

            recovered = engine.prepare(admit=False)
            names = action_names(recovered)
            self.assertTrue(names & {'open_retrieved_passage', 'continue_raw_evidence',
                                     'read_more_context', 'show_context_page'})
            self.assertNotIn('read_case_passages', names)
            self.assertIn('read_more_context', names)
            engine.step(lambda prepared: reader.action(prepared, 'read_more_context'))
            ready = engine.prepare(admit=False)
            self.assertIn('read_case_passages', action_names(ready))
            engine.step(lambda prepared: choose_wire_action(
                prepared, 'read_case_passages', focus='different legal standard'))
            self.assertNotEqual(engine.events()[-1].get('reason'), 'duplicate_action')

            # A second need may use the same candidate and focus independently.
            helper.missing(engine)
            helper.search(engine, 'p000002')
            self.assertNotEqual(engine.context()['need_id'], first_need)
            self.assertEqual(backend.calls, 1)
            second_need = engine.prepare(admit=False)
            self.assertIn('read_case_passages', action_names(second_need))
            engine.step(lambda prepared: choose_wire_action(
                prepared, 'read_case_passages', focus='procedural fairness'))
            self.assertEqual(engine.events()[-1]['status'], 'success')
            self.assertTrue(engine.events()[-2]['executes_tool'])


if __name__ == '__main__':
    unittest.main()
