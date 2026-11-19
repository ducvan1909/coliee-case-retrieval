"""Offline integrated source/assessment/recovery regressions."""
import json
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from jsonschema import Draft202012Validator

from pipeline_v2.experiments.context_manager_v2.tests.view_helpers import canonical_ref, wire_ref
from pipeline_v2.experiments.context_manager_v2.cli import quote_for_paragraph

from pipeline_v2.agent_harness import RunIdentity
from pipeline_v2.agent_harness.contracts import HarnessError
from pipeline_v2.experiments.context_manager_v2.engine import Engine
from pipeline_v2.experiments.context_manager_v2.evidence import EvidenceStore
from pipeline_v2.tests.test_m6_adaptive import Tools, source
from pipeline_v2.agent_harness import SourceExcerpt, ToolResult


def count(body):
    return len(body) // 6 + 100


def tools_with_quoted_query():
    tools = Tools()
    tools.a = replace(tools.a, provenance={'components': [{
        'unit_id': 'quote', 'span_bytes': list(tools.a.span_bytes), 'unit_kind': 'paragraph', 'paragraph_role': 'quoted'
    }]})
    return tools


class EngineTests(unittest.TestCase):
    def make(self, directory, tools=None):
        tools = tools or Tools()
        identity = RunIdentity('cm23', 'A', tools.a.source_hash, 'c', 'i', 'p', 'm', 'p', 't', 'z')
        raw = {'A': tools.a.text.encode(), 'B': tools.b.text.encode()}
        engine = Engine(directory, identity=identity, tools=tools, count_tokens=count,
                        raw_reader=lambda case: raw[case], counter_binding='fixture-count-v1')
        return engine, raw

    def action(self, prepared, name):
        body = prepared['payload']
        branch = next(b for b in prepared['manifest']['schema']['anyOf'] if b['properties']['action']['const'] == name)
        fields = branch['properties']['args']['properties']
        required = branch['properties']['args']['required']
        args = {}
        for key in required:
            schema = fields[key]
            if key == 'anchor_quote':
                args[key] = quote_for_paragraph(body)
            else:
                args[key] = schema['enum'][0] if 'enum' in schema else 'procedural fairness' if key in ('issue', 'focus') else 'The notice requirement needs a source.'
        if name == 'assess_case_link':
            args.update(case_relation='unknown', passage_location='bounded')
        if name == 'read_case_passages':
            candidate_ref = args.get('candidate_ref')
            candidates = body['m6'].get('candidates', {})
            lead_ref = next((ref for ref, lead in body['m6'].get('retrieved_passages', {}).items()
                             if lead['description']['candidate_ref'] == candidate_ref), None)
            if lead_ref:
                return {'action': 'open_retrieved_passage', 'args': {'lead_ref': lead_ref}}
        return {'action': name, 'args': args}

    def search_read(self, e):
        e.step(lambda p: self.action(p, 'search_cases_by_issue'))
        e.step(lambda p: self.action(p, 'read_case_passages'))

    def test_search_read_assess_actual_m4_validator_and_reload(self):
        with TemporaryDirectory() as d:
            e, _ = self.make(d)
            self.search_read(e)
            p = e.step(lambda p: self.action(p, 'assess_case_link'))
            self.assertEqual({r['case_id'] for r in p['payload']['excerpts']}, {'A', 'B'})
            s = e.state()
            self.assertEqual(len(s.active_assessments), 1)
            self.assertEqual(next(iter(s.assessments.values()))['case_relation'], 'unknown')
            original = deepcopy(s.catalog)
            self.assertNotIn('reload_pair_evidence', {
                branch['properties']['action']['const'] for branch in p['manifest']['schema']['anyOf']})
            q = e.prepare()
            self.assertTrue(e.state().active_assessments)
            for row in q['manifest']['excerpts']:
                self.assertEqual(row, original[row['ref']])

    def test_unknown_response_and_crash_recovery_never_resend(self):
        for explicit in (False, True):
            with self.subTest(explicit=explicit), TemporaryDirectory() as d:
                e, _ = self.make(d)
                p = e.prepare()
                if explicit:
                    e.reply(p['request_id'], status='unknown')
                else:
                    self.assertEqual(e.prepare()['status'], 'blocked_unknown')
                with self.assertRaises(HarnessError):
                    e.prepare()
                self.assertEqual(e.state().usage()['requests'], 1)
                self.assertFalse(e.state().delivered)

    def test_malformed_reply_is_recorded_and_terminal(self):
        with TemporaryDirectory() as d:
            e, _ = self.make(d)
            p = e.prepare()
            e.reply(p['request_id'], {'action': 'invented', 'args': {}})
            self.assertEqual(e.state().last_receipt['status'], 'malformed')
            self.assertEqual(e.state().final['stop_detail'], 'scripted_response_rejected')
            self.assertTrue(e.state().delivered)

    def test_manifest_tamper_rejected(self):
        with TemporaryDirectory() as d:
            e, _ = self.make(d)
            p = e.prepare()
            path = Path(d) / 'manifests' / (p['request_id'] + '.json')
            path.write_text('{}')
            with self.assertRaises(HarnessError):
                e.reply(p['request_id'], self.action(p, 'search_cases_by_issue'))

    def test_source_drift_invalidates_existing_assessment(self):
        with TemporaryDirectory() as d:
            e, raw = self.make(d)
            self.search_read(e)
            e.step(lambda p: self.action(p, 'assess_case_link'))
            self.assertTrue(e.state().active_assessments)
            raw['B'] += b' changed'
            self.assertEqual(e.prepare()['status'], 'source_drift')
            self.assertFalse(e.state().active_assessments)

    def test_search_not_offered_during_reading_and_missing_releases_focus(self):
        with TemporaryDirectory() as d:
            e, _ = self.make(d)
            self.search_read(e)
            p = e.prepare()
            names = {b['properties']['action']['const'] for b in p['manifest']['schema']['anyOf']}
            self.assertNotIn('search_cases_by_issue', names)
            self.assertNotIn('find_citation_matches', names)
            e.reply(p['request_id'], self.action(p, 'record_missing_evidence'))
            e.execute_pending()
            q = e.prepare()
            self.assertIn('search_cases_by_issue', {b['properties']['action']['const'] for b in q['manifest']['schema']['anyOf']})

    def test_actual_validator_preserves_pending_attribution_instead_of_accepting_claim(self):
        with TemporaryDirectory() as d:
            e, _ = self.make(d, tools_with_quoted_query())
            self.search_read(e)
            def assess(p):
                action = self.action(p, 'assess_case_link')
                action['args']['speaker'] = {'role': 'quoted_source', 'type': 'quotation', 'side': 'query case'}
                action['args']['speaker_evidence_refs'] = [next(row['ref'] for row in p['payload']['excerpts'] if row['case_id'] == 'A')]
                action['args']['missing_evidence'] = ['Need attribution cue and complete quoted container.']
                return action
            e.step(assess)
            state = e.state()
            self.assertFalse(state.active_assessments)
            row = next(iter(state.pending_assessments.values()))
            self.assertEqual(row['case_relation'], 'unknown')
            self.assertEqual(row['status'], 'pending_evidence')
            self.assertIn('quote_chain_refs', row['missing_evidence'])
            self.assertEqual(e.context()['stage'], 'missing_evidence')

    def test_pending_quote_without_optional_missing_note_commits_and_offers_feedback(self):
        with TemporaryDirectory() as d:
            e, _ = self.make(d, tools_with_quoted_query())
            self.search_read(e)

            def assess(p):
                action = self.action(p, 'assess_case_link')
                action['args']['speaker'] = {'role': 'quoted_source', 'type': 'quotation', 'side': 'query case'}
                action['args']['speaker_evidence_refs'] = [next(row['ref'] for row in p['payload']['excerpts'] if row['case_id'] == 'A')]
                return action

            e.step(assess)
            state = e.state()
            self.assertIsNone(state.active_action)
            self.assertIsNone(state.final)
            row = next(iter(state.pending_assessments.values()))
            self.assertIsNone(row['reported_missing_evidence'])
            self.assertEqual(row['missing_evidence'], ['container_refs', 'quote_chain_refs'])
            followup = e.prepare(admit=False)
            self.assertEqual(followup['status'], 'ready')
            feedback = followup['payload']['last_action_feedback']
            self.assertEqual(feedback['reported_missing_evidence'], [])
            self.assertEqual(feedback['validation_missing_codes'], ['container_refs', 'quote_chain_refs'])

    def test_complete_policy_requires_no_retrieval_only_candidates_or_pending_pairs(self):
        with TemporaryDirectory() as d:
            e, _ = self.make(d)
            e.step(lambda p: self.action(p, 'search_cases_by_issue'))
            complete = {'action': 'finish_case_review', 'args': {'reason': 'complete_policy'}}
            early_stop = {'action': 'finish_case_review', 'args': {'reason': 'no_progress'}}

            def check(allowed, unread, pending):
                p = e.prepare(admit=False)
                validator = Draft202012Validator(p['manifest']['schema'])
                self.assertEqual(validator.is_valid(complete), allowed)
                self.assertFalse(validator.is_valid(early_stop))
                finish = next(tool for tool in p['payload']['available_tools']
                              if tool['name'] == 'finish_case_review')
                self.assertNotIn('no_progress', finish['parameters']['properties']['reason']['enum'])
                progress = p['payload']['last_action_feedback']['review_progress']
                self.assertEqual(progress['retrieval_only_candidates'], unread)
                self.assertEqual(progress['pending_pairs'], pending)

            check(False, 1, 0)
            e.step(lambda p: self.action(p, 'read_case_passages'))

            def assess_pending(p):
                action = self.action(p, 'assess_case_link')
                action['args']['missing_evidence'] = ['Need the context surrounding the citation.']
                return action

            e.step(assess_pending)
            check(False, 0, 1)
            e.step(lambda p: self.action(p, 'assess_case_link'))
            check(True, 0, 0)
            e.step(complete)
            self.assertEqual(e.state().final['stop_reason'], 'complete')

    def test_ten_thousand_candidates_stay_outside_model_context(self):
        class ManyTools(Tools):
            def query_start(self):
                initial, whole = super().query_start()
                return ToolResult(initial.observation, initial.excerpts,
                                  tuple(f'{number:06}.txt' for number in range(10000))), whole
        with TemporaryDirectory() as d:
            e, _ = self.make(d, ManyTools())
            p = e.step(lambda p: {'action': 'show_context_page', 'args': {'page_ref': p['payload']['m6']['cm_page']['controls']['pool']}})
            q = e.prepare()
            self.assertEqual(q['payload']['candidate_count'], 10000)
            self.assertLessEqual(len(q['payload']['m6']['candidates']), 5)
            self.assertLessEqual(q['input_tokens'], 8500)
            self.assertEqual(len(e.state().candidates), 10000)

    def test_reviewed_results_page_offers_next_instead_of_reopening_reviewed_case(self):
        class PagedTools(Tools):
            def search_corpus(self, args):
                return ToolResult({'hits': [
                    {'case_id': 'B', 'rank': 1, 'open_ref': {
                        'case_id': 'B', 'source_hash': self.b.source_hash, 'passage_ids': ['B-1']}},
                    {'case_id': 'C', 'rank': 2},
                ]}, candidates=('B', 'C'))

        with TemporaryDirectory() as d:
            e, _ = self.make(d, PagedTools())
            e.page_size = 1
            self.search_read(e)
            e.step(lambda p: self.action(p, 'assess_case_link'))
            e.step(lambda p: {'action': 'show_context_page',
                              'args': {'page_ref': p['payload']['m6']['cm_page']['controls']['results']}})
            reviewed_page = e.prepare(admit=False)
            payload = reviewed_page['payload']
            page = payload['m6']['cm_page']
            self.assertEqual([(card['case_id'], card['read_allowed']) for card in page['candidates']], [('B', False)])
            self.assertFalse({'read_case_passages', 'open_retrieved_passage'} &
                             {tool['name'] for tool in payload['available_tools']})
            next_option, = payload['last_action_feedback']['navigation_options']
            self.assertEqual(next_option['args']['page_ref'], page['controls']['next'])
            e.step({'action': next_option['tool'], 'args': next_option['args']})
            next_page = e.prepare(admit=False)['payload']['m6']['cm_page']
            self.assertEqual(next_page['offset'], 1)
            self.assertEqual([(card['case_id'], card['read_allowed']) for card in next_page['candidates']], [('C', True)])

    def test_query_continuation_does_not_create_a_candidate_pair(self):
        with TemporaryDirectory() as d:
            tools = Tools()
            tools.a = source('A', ''.join(
                f'At step {i:03}, the court considers the law of procedural fairness. ' for i in range(100)))
            tools.query_paragraphs = ({'handle': 'p000001', 'span_bytes': tools.a.span_bytes},)
            e, _ = self.make(d, tools)
            e.step(lambda p: self.action(p, 'continue_raw_evidence'))
            p = e.prepare(admit=False)
            names = {tool['name'] for tool in p['payload']['available_tools']}
            self.assertNotIn('resume_pair_evidence', names)
            self.assertNotIn('reload_pair_evidence', names)
            self.assertIn('search_cases_by_issue', names)
            self.assertEqual(e.context()['stage'], 'ready')
            e.step(lambda p: self.action(p, 'search_cases_by_issue'))
            self.assertEqual(e.context()['stage'], 'results_ready')

    def test_query_fetch_replaces_previous_raw_window(self):
        class QueryTools(Tools):
            def query_start(self):
                return ToolResult({'kind': 'query_map', 'items': [{'handle': 'p000002'}]}, (self.first,)), self.a

            def open_query(self, args):
                return ToolResult({}, (self.next,))

            def expand_source(self, args):
                return ToolResult({}, (self.next,))

        for action in ('read_query_passages', 'read_more_context'):
            with self.subTest(action=action), TemporaryDirectory() as d:
                tools = QueryTools()
                first = 'The court considers the law of procedural fairness. ' * 100
                second = 'A separate passage considers the appeal.'
                tools.a = source('A', first + second)
                tools.first = replace(tools.a.slice(0, len(first)), provenance={'components': [{
                    'unit_id': 'p000001', 'span_bytes': [0, len(first)], 'unit_kind': 'paragraph',
                    'reading_expansion': {'next_ref': 'p000002'},
                }]})
                tools.next = tools.a.slice(len(first), len(first + second))
                tools.query_paragraphs = ({'handle': 'p000001', 'span_bytes': tools.first.span_bytes},
                                          {'handle': 'p000002', 'span_bytes': tools.next.span_bytes})
                e, _ = self.make(d, tools)
                e.step(lambda p: self.action(p, 'continue_raw_evidence'))
                e.step(lambda p: self.action(p, action))
                p = e.prepare(admit=False)
                self.assertEqual([r['span_bytes'] for r in p['payload']['excerpts']], [list(tools.next.span_bytes)])

    def test_seven_parked_pairs_next_cursor_is_in_decoder_schema(self):
        from pipeline_v2.m6 import AdaptiveConfig
        class SevenTools(Tools):
            def __init__(self):
                super().__init__()
                self.rows = {}
                for number in range(7):
                    text = f'Candidate {number} reasons about the notice requirement.'
                    raw = text.encode()
                    self.rows[f'B{number}'] = SourceExcerpt(f'B{number}', sha256(raw).hexdigest(), (0, len(raw)), text, sha256(raw).hexdigest())
            def search_corpus(self, args):
                return ToolResult({'hits': [{'case_id': key, 'rank': n + 1,
                    'open_ref': {'case_id': key, 'source_hash': row.source_hash, 'passage_ids': [key]}}
                    for n, (key, row) in enumerate(self.rows.items())]}, candidates=tuple(self.rows))
            def open_source(self, args):
                row = self.rows[args['case_id']]
                return ToolResult({'case_id': row.case_id}, (row,), (row.case_id,))
            def verify_source(self, case, digest):
                return any(row.case_id == case and row.source_hash == digest for row in (self.a, *self.rows.values()))
        with TemporaryDirectory() as d:
            tools = SevenTools()
            identity = RunIdentity('seven', 'A', tools.a.source_hash, 'c', 'i', 'p', 'm', 'p', 't', 'z')
            raw = {'A': tools.a.text.encode(), **{key: row.text.encode() for key, row in tools.rows.items()}}
            e = Engine(d, identity=identity, tools=tools, count_tokens=count, raw_reader=lambda case: raw[case],
                       config=AdaptiveConfig(search_limit=7))
            e.step(lambda p: self.action(p, 'search_cases_by_issue'))
            for number in range(7):
                e.step(lambda p: {'action': 'show_context_page', 'args': {'page_ref': p['payload']['m6']['cm_page']['controls']['pool']}})
                if number >= 5:
                    e.step(lambda p: {'action': 'show_context_page', 'args': {'page_ref': p['payload']['m6']['cm_page']['controls']['next']}})
                def read(p, number=number):
                    key = next(key for key, value in p['payload']['m6']['candidates'].items() if value['case_id'] == f'B{number}')
                    lead_ref = next(lead_key for lead_key, row in p['payload']['m6']['retrieved_passages'].items()
                                    if row['description']['candidate_ref'] == key)
                    return {'action': 'open_retrieved_passage', 'args': {'lead_ref': lead_ref}}
                e.step(read)
                e.step(lambda p: self.action(p, 'assess_case_link'))
            self.assertEqual(len(e.state().active_assessments), 7)
            e.step(lambda p: {'action': 'show_context_page', 'args': {'page_ref': p['payload']['m6']['cm_page']['controls']['parked']}})
            p = e.prepare()
            next_ref = p['payload']['m6']['cm_page']['controls']['next']
            branch = next(b for b in p['manifest']['schema']['anyOf'] if b['properties']['action']['const'] == 'show_context_page')
            self.assertIn(next_ref, branch['properties']['args']['properties']['page_ref']['enum'])
            self.assertEqual(len(p['payload']['m6']['cm_page']['parked_pairs']), 5)
            e.reply(p['request_id'], {'action': 'show_context_page', 'args': {'page_ref': next_ref}})
            e.execute_pending()
            q = e.prepare(admit=False)
            # B6 is the active pair; only the other six pairs are parked.
            self.assertEqual(len(q['payload']['m6']['cm_page']['parked_pairs']), 1)
            self.assertEqual(len(e.state().active_assessments), 7)
            e.step(lambda current: self.action(current, 'resume_pair_evidence'))
            context = e.context()
            self.assertEqual(context['mode'], 'assessment')
            self.assertEqual(context['offset'], 0)
            self.assertEqual(context['back'], [])
            self.assertEqual(e.prepare(admit=False)['payload']['m6']['cm_page']['count'], 1)

    def test_new_read_region_replaces_old_B_pins(self):
        class TwoRegions(Tools):
            def __init__(self):
                super().__init__()
                text = 'First region needs context. Second region contains the exception.'
                raw = text.encode()
                self.b = SourceExcerpt('B', sha256(raw).hexdigest(), (0, len(raw)), text, sha256(raw).hexdigest())
                self.calls = 0
            def open_source(self, args):
                self.calls += 1
                part = self.b.slice(0, 27) if self.calls == 1 else self.b.slice(28, len(self.b.text))
                return ToolResult({'case_id': 'B'}, (part,), ('B',))
        with TemporaryDirectory() as d:
            tools = TwoRegions()
            e, _ = self.make(d, tools)
            self.search_read(e)
            # Acknowledge the first window before requesting a new source region.
            p = e.prepare(admit=False)
            self.assertNotIn('assessment', p['payload']['m6']['cm_page']['controls'])
            self.assertIn('read_case_passages', {b['properties']['action']['const']
                for b in p['manifest']['schema']['anyOf']})
            e.step(lambda p: self.action(p, 'read_case_passages'))
            p = e.prepare()
            b = next(r for r in p['payload']['excerpts'] if r['case_id'] == 'B')
            self.assertEqual(b['span_bytes'][0], 28)
            self.assertIn('exception', b['text'])

    def test_multiple_continuations_keep_original_root_and_full_tail(self):
        class LongTools(Tools):
            def __init__(self):
                super().__init__()
                text = 'Énoncé not adopted unless exception applies. ' * 130
                raw = text.encode()
                self.b = SourceExcerpt('B', sha256(raw).hexdigest(), (0, len(raw)), text, sha256(raw).hexdigest())
        with TemporaryDirectory() as d:
            tools = LongTools()
            e, _ = self.make(d, tools)
            self.search_read(e)
            seen, root = [], None
            for _ in range(5):
                p = e.prepare()
                b = next(r for r in p['payload']['excerpts'] if r['case_id'] == 'B')
                cov = next(c for c in p['manifest']['coverage'] if c['canonical_ref'] in e.state().catalog
                           and e.state().catalog[c['canonical_ref']]['case_id'] == 'B')
                root = root or cov['canonical_ref']
                self.assertEqual(cov['canonical_ref'], root)
                seen.append(b)
                if cov['pending'] is None:
                    break
                branch = next(x for x in p['manifest']['schema']['anyOf'] if x['properties']['action']['const'] == 'continue_raw_evidence')
                refs = branch['properties']['args']['properties']['context_ref']['enum']
                handle = next(r for r in refs if p['manifest']['handles'][canonical_ref(p, r)]['ref'] == root)
                e.reply(p['request_id'], {'action': 'continue_raw_evidence', 'args': {'context_ref': handle}})
                e.execute_pending()
            self.assertGreater(len(seen), 1)
            self.assertEqual(b''.join(r['text'].encode() for r in seen), tools.b.text.encode())

    def test_multiple_raw_roots_are_reachable_once_without_continuation_cycle(self):
        class SplitTools(Tools):
            def __init__(self):
                super().__init__()
                text = 'Rule without exception. ' * 320
                raw = text.encode()
                self.b = SourceExcerpt('B', sha256(raw).hexdigest(), (0, len(raw)), text, sha256(raw).hexdigest())
            def open_source(self, args):
                return ToolResult({'case_id': 'B'}, (self.b.slice(0, 3600), self.b.slice(3600, len(self.b.text))), ('B',))
        with TemporaryDirectory() as d:
            tools = SplitTools()
            e, _ = self.make(d, tools)
            self.search_read(e)
            seen = []
            for index in range(10):
                p = e.prepare()
                b = next(r for r in p['payload']['excerpts'] if r['case_id'] == 'B')
                seen.append(b)
                choices = [key for key, value in p['manifest']['handles'].items() if value['kind'] == 'continuation'
                           and e.state().catalog[value['ref']]['case_id'] == 'B']
                if not choices:
                    self.assertEqual(p['payload']['pending_source_count'], 0)
                    break
                # Continue tail of currently offered root before moving to next root.
                root = next(c['canonical_ref'] for c in p['manifest']['coverage'] if e.state().catalog[c['canonical_ref']]['case_id'] == 'B')
                choice = next((key for key in choices if p['manifest']['handles'][key]['ref'] == root), choices[0])
                e.reply(p['request_id'], {'action': 'continue_raw_evidence', 'args': {'context_ref': wire_ref(p, choice)}})
                e.execute_pending()
                # Re-instantiation must preserve original root queue and completed windows.
                e, _ = self.make(d, tools)
            else:
                self.fail('Continuation did not terminate')
            self.assertEqual(b''.join(r['text'].encode() for r in seen), tools.b.text.encode())
            self.assertEqual(len({tuple(r['span_bytes']) for r in seen}), len(seen))

    def test_park_resume_keeps_assessment_and_current_raw_only(self):
        class MultiTools(Tools):
            def __init__(self):
                super().__init__()
                text = 'Candidate C has a distinct source rule.'
                raw = text.encode()
                self.c = SourceExcerpt('C', sha256(raw).hexdigest(), (0, len(raw)), text, sha256(raw).hexdigest())
            def search_corpus(self, args):
                return ToolResult({'hits': [{'case_id': row.case_id, 'rank': i + 1,
                    'open_ref': {'case_id': row.case_id, 'source_hash': row.source_hash, 'passage_ids': [row.case_id + '-1']}}
                    for i, row in enumerate((self.b, self.c))]}, candidates=('B', 'C'))
            def open_source(self, args):
                row = self.b if args['case_id'] == 'B' else self.c
                return ToolResult({'case_id': row.case_id}, (row,), (row.case_id,))
            def verify_source(self, case, digest):
                return any(r.case_id == case and r.source_hash == digest for r in (self.a, self.b, self.c))
        with TemporaryDirectory() as d:
            tools = MultiTools()
            identity = RunIdentity('multi', 'A', tools.a.source_hash, 'c', 'i', 'p', 'm', 'p', 't', 'z')
            e = Engine(d, identity=identity, tools=tools, count_tokens=count,
                raw_reader=lambda case: {'A': tools.a, 'B': tools.b, 'C': tools.c}[case].text.encode())
            self.search_read(e)
            e.step(lambda p: self.action(p, 'assess_case_link'))
            assessment = list(e.state().active_assessments.values())
            e.step(lambda p: {'action': 'show_context_page', 'args': {'page_ref': p['payload']['m6']['cm_page']['controls']['pool']}})
            def read_c(p):
                candidate_ref = next(k for k, r in p['payload']['m6']['candidates'].items() if r['case_id'] == 'C')
                lead_ref = next(k for k, row in p['payload']['m6']['retrieved_passages'].items()
                                if row['description']['candidate_ref'] == candidate_ref)
                return {'action': 'open_retrieved_passage', 'args': {'lead_ref': lead_ref}}
            e.step(read_c)
            p = e.step(lambda p: self.action(p, 'record_missing_evidence'))
            self.assertEqual({r['case_id'] for r in p['payload']['excerpts']}, {'A', 'C'})
            self.assertEqual(list(e.state().active_assessments.values()), assessment)
            e.step(lambda p: {'action': 'show_context_page', 'args': {'page_ref': p['payload']['m6']['cm_page']['controls']['parked']}})
            def resume_b(p):
                key = next(k for k, target in p['manifest']['handles'].items() if target['kind'] == 'resume' and target['candidate_id'] == 'B')
                return {'action': 'resume_pair_evidence', 'args': {'evidence_ref': wire_ref(p, key)}}
            e.step(resume_b)
            q = e.prepare()
            self.assertEqual({r['case_id'] for r in q['payload']['excerpts']}, {'A', 'B'})
            self.assertEqual(list(e.state().active_assessments.values()), assessment)


    def test_nonsequential_root_returns_to_next_delivered_byte(self):
        from pipeline_v2.agent_harness.contracts import fingerprint
        class SplitTools(Tools):
            def __init__(self):
                super().__init__()
                raw = b'Rule without exception. ' * 400
                self.b = SourceExcerpt('B', sha256(raw).hexdigest(), (0, len(raw)), raw.decode(), sha256(raw).hexdigest())
            def open_source(self, args):
                return ToolResult({}, (self.b.slice(0, 4500), self.b.slice(4500, len(self.b.text))), ('B',))
        with TemporaryDirectory() as d:
            tools = SplitTools()
            e, _ = self.make(d, tools)
            self.search_read(e)
            p = e.prepare()
            first = next(r for r in p['payload']['excerpts'] if r['case_id'] == 'B')
            roots = sorted([r for r in e.state().catalog.values() if r['case_id'] == 'B'], key=lambda r: r['span_bytes'])
            root1, root2 = roots[0]['ref'], roots[1]['ref']
            key = next(k for k, v in p['manifest']['handles'].items() if v['kind'] == 'continuation' and v['ref'] == root2)
            e.reply(p['request_id'], {'action': 'continue_raw_evidence', 'args': {'context_ref': wire_ref(p, key)}})
            e.execute_pending()
            e, _ = self.make(d, tools)
            q = e.prepare()
            back = next((k, v) for k, v in q['manifest']['handles'].items() if v['kind'] == 'continuation' and v['ref'] == root1)
            self.assertEqual(back[1]['offset'], first['span_bytes'][1])
            second = next(r for r in q['payload']['excerpts'] if r['case_id'] == 'B')
            e.reply(q['request_id'], {'action': 'continue_raw_evidence', 'args': {'context_ref': wire_ref(q, back[0])}})
            e.execute_pending()
            r = e.prepare()
            resumed = next(x for x in r['payload']['excerpts'] if x['case_id'] == 'B')
            self.assertEqual(resumed['span_bytes'][0], first['span_bytes'][1])
            onward = next(v for v in r['manifest']['handles'].values() if v['kind'] == 'continuation' and v['ref'] == root2)
            self.assertEqual(onward['offset'], second['span_bytes'][1])
            pair = fingerprint([e.context()['need_id'], 'B'])
            self.assertEqual(e.context()['pair_progress'][pair]['next_offsets'][root2], second['span_bytes'][1])

    def test_shared_A_progress_and_missing_reason_are_pair_local_resume_preserves_reload_resets(self):
        from pipeline_v2.agent_harness.contracts import fingerprint
        class MultiTools(Tools):
            def __init__(self):
                super().__init__()
                raw = ''.join(f'The legal test applies to issue {i:03}. ' for i in range(300)).encode()
                self.a = SourceExcerpt('A', sha256(raw).hexdigest(), (0, len(raw)), raw.decode(), sha256(raw).hexdigest())
                self.query_paragraphs = ({'handle': 'p000001', 'span_bytes': self.a.span_bytes},)
                raw = b'Candidate rule and exceptions. ' * 300
                self.b = SourceExcerpt('B', sha256(raw).hexdigest(), (0, len(raw)), raw.decode(), sha256(raw).hexdigest())
                self.c = SourceExcerpt('C', self.b.source_hash, self.b.span_bytes, self.b.text, self.b.text_sha256)
            def search_corpus(self, args):
                return ToolResult({'hits': [{'case_id': x.case_id, 'rank': i + 1,
                    'open_ref': {'case_id': x.case_id, 'source_hash': x.source_hash, 'passage_ids': ['p1']}}
                    for i, x in enumerate((self.b, self.c))]}, candidates=('B', 'C'))
            def open_source(self, args):
                x = self.b if args['case_id'] == 'B' else self.c
                return ToolResult({}, (x,), (x.case_id,))
            def verify_source(self, case, digest):
                return any(x.case_id == case and x.source_hash == digest for x in (self.a, self.b, self.c))
        with TemporaryDirectory() as d:
            tools = MultiTools()
            identity = RunIdentity('pair-local', 'A', tools.a.source_hash, 'c', 'i', 'p', 'm', 'p', 't', 'z')
            kwargs = dict(identity=identity, tools=tools, count_tokens=count,
                raw_reader=lambda case: {'A': tools.a, 'B': tools.b, 'C': tools.c}[case].text.encode())
            e = Engine(d, **kwargs)
            self.search_read(e)
            def page(mode):
                return lambda p: {'action': 'show_context_page', 'args': {'page_ref': p['payload']['m6']['cm_page']['controls'][mode]}}
            def missing(reason):
                return lambda p: {'action': 'record_missing_evidence', 'args': {'reason': reason}}
            p = e.step(missing('B needs the next attribution passage.'))
            a_cov = next(c for c in p['manifest']['coverage'] if e.state().catalog[c['canonical_ref']]['case_id'] == 'A')
            b_cov = next(c for c in p['manifest']['coverage'] if e.state().catalog[c['canonical_ref']]['case_id'] == 'B')
            pair_b = fingerprint([e.context()['need_id'], 'B'])
            self.assertEqual(e.context()['missing_reason'], 'B needs the next attribution passage.')
            e.step(page('pool'))
            def read_c(p):
                candidate_ref = next(k for k, x in p['payload']['m6']['candidates'].items() if x['case_id'] == 'C')
                lead_ref = next(k for k, row in p['payload']['m6']['retrieved_passages'].items()
                                if row['description']['candidate_ref'] == candidate_ref)
                return {'action': 'open_retrieved_passage', 'args': {'lead_ref': lead_ref}}
            e.step(read_c)
            self.assertNotIn('missing_reason', e.context())
            pair_c = fingerprint([e.context()['need_id'], 'C'])
            self.assertNotIn(a_cov['canonical_ref'], e.context()['pair_progress'][pair_c]['next_offsets'])
            e.step(missing('C needs a different quote container.'))
            e.step(page('parked'))
            def resume_b(p):
                key = next(k for k, v in p['manifest']['handles'].items() if v['kind'] == 'resume' and v['candidate_id'] == 'B')
                return {'action': 'resume_pair_evidence', 'args': {'evidence_ref': wire_ref(p, key)}}
            e.step(resume_b)
            e = Engine(d, **kwargs)
            self.assertEqual(e.context()['missing_reason'], 'B needs the next attribution passage.')
            self.assertEqual(e.context()['pair_progress'][pair_b]['missing_reason'], 'B needs the next attribution passage.')
            q = e.step(lambda p: self.action(p, 'reload_pair_evidence'))
            resumed_b = next(x for x in q['payload']['excerpts'] if x['case_id'] == 'B')
            self.assertEqual(resumed_b['span_bytes'][0], b_cov['offered'][1])
            after_reset = e.prepare()
            reset_b = next(x for x in after_reset['payload']['excerpts'] if x['case_id'] == 'B')
            self.assertEqual(reset_b['span_bytes'][0], b_cov['requested'][0])
            self.assertNotIn('missing_reason', e.context())
            self.assertEqual(e.context()['pair_progress'][pair_c]['missing_reason'], 'C needs a different quote container.')


    def test_resume_completed_partial_A_anchor_does_not_advance_outside_requested_span(self):
        class PartialATools(Tools):
            def __init__(self):
                super().__init__()
                raw = ''.join(f'The fairness rule applies to evidence {i:03}. ' for i in range(40)).encode()
                self.a = SourceExcerpt('A', sha256(raw).hexdigest(), (0, len(raw)), raw.decode(), sha256(raw).hexdigest())
                self.query_paragraphs = ({'handle': 'p000001', 'span_bytes': (0, 100)},)
        with TemporaryDirectory() as d:
            tools = PartialATools()
            e, _ = self.make(d, tools)
            self.search_read(e)
            e.step(lambda p: self.action(p, 'record_missing_evidence'))
            q = e.prepare(admit=False)
            self.assertNotIn('resume_pair_evidence', {
                branch['properties']['action']['const'] for branch in q['manifest']['schema']['anyOf']})
            q = e.prepare()
            a = next(r for r in q['payload']['excerpts'] if r['case_id'] == 'A')
            self.assertEqual(tuple(a['span_bytes']), (0, 100))
            self.assertEqual(q['status'], 'ready')

    def test_unknown_receipt_never_advances_pair_raw_progress(self):
        with TemporaryDirectory() as d:
            e, _ = self.make(d)
            self.search_read(e)
            before = deepcopy(e.context()['pair_progress'])
            p = e.prepare()
            e.reply(p['request_id'], status='unknown')
            self.assertEqual(e.context()['pair_progress'], before)
            with self.assertRaises(HarnessError):
                e.prepare()


class EvidenceTests(unittest.TestCase):
    def test_narrow_anchor_never_returns_full_canonical_record(self):
        from pipeline_v2.agent_harness import SourceExcerpt
        raw = b'prefix requested anchor suffix'
        value = SourceExcerpt('A', sha256(raw).hexdigest(), (0, len(raw)), raw.decode(), sha256(raw).hexdigest())
        row, coverage = EvidenceStore(lambda _: raw).window(value.to_record(), byte_limit=1024, requested_span=[7, 23])
        self.assertEqual(tuple(row['span_bytes']), (7, 23))
        self.assertEqual(row['text'].encode(), raw[7:23])
        self.assertEqual(coverage['offered'], [7, 23])

    def test_utf8_continuations_cover_full_bytes_and_overlay_survives(self):
        from pipeline_v2.agent_harness import SourceExcerpt
        from pipeline_v2.agent_harness.evidence import source_record
        raw = 'Énoncé non adopté; exception à la règle. '.encode() * 3
        value = SourceExcerpt('A', sha256(raw).hexdigest(), (0, len(raw)), raw.decode(), sha256(raw).hexdigest(),
            {'components': [{'unit_id': 'p1', 'span_bytes': [0, len(raw)], 'unit_kind': 'paragraph', 'paragraph_role': 'quoted'}]})
        record = source_record(value, overlay=True)
        store = EvidenceStore(lambda case: raw)
        self.assertEqual(store.window(record, byte_limit=len(raw))[0], record)
        offset, collected = 0, b''
        while offset < len(raw):
            part, cov = store.window(record, offset, 13)
            self.assertTrue(part['provenance_overlay'])
            collected += part['text'].encode()
            offset = cov['offered'][1]
        self.assertEqual(collected, raw)


if __name__ == '__main__':
    unittest.main()
