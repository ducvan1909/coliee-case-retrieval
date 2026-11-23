"""Engine-level offline regressions for the grouped CM4 passage review."""
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator

from pipeline_v2.agent_harness import RunIdentity, ToolResult
from pipeline_v2.agent_harness.contracts import HarnessError, fingerprint
from pipeline_v2.agent_harness.selection import select_supported_cases, selector_fingerprint
from pipeline_v2.experiments.context_manager_v2.cli import choose
from pipeline_v2.experiments.context_manager_v2.dual_search import DualSearch
from pipeline_v2.experiments.context_manager_v2.engine import Engine
from pipeline_v2.experiments.context_manager_v2.passage_review import _intro
from pipeline_v2.experiments.context_manager_v2.model_view import restore_action
from pipeline_v2.experiments.context_manager_v2 import query_review
from pipeline_v2.experiments.context_manager_v2.tests.test_engine import count
from pipeline_v2.experiments.context_manager_v2.tests.test_source_gate import screen
from pipeline_v2.m6 import AdaptiveConfig
from pipeline_v2.tests.test_m6_adaptive import Tools, source


def sha(raw):
    return sha256(raw).hexdigest()


def recursively_has_key(value, keys):
    if isinstance(value, dict):
        return any(key in keys or recursively_has_key(item, keys) for key, item in value.items())
    if isinstance(value, list):
        return any(recursively_has_key(item, keys) for item in value)
    return False


class PassageTools(Tools):
    def __init__(self):
        super().__init__()
        self.a = source('A', 'The Court applied the notice fairness rule in this dispute.')
        self.query_paragraphs = ({'handle': 'p000001', 'span_bytes': self.a.span_bytes},)
        # Keep identity material away from the hit windows so the two are distinct
        # pieces of evidence in the grouped raw package.
        raw = b'B_A identity header. ' + b'background ' * 1700
        self.b = source('B_A', raw.decode())
        self.c = source('B_B', 'B_B identity header. ' + 'The notice rule applies. ' * 20)
        self.reads = []

    def verify_source(self, case, digest):
        row = {'A': self.a, 'B_A': self.b, 'B_B': self.c}.get(case)
        return bool(row and row.source_hash == digest)

    def search_corpus(self, args):
        raise AssertionError('Hybrid fixture should be called through its bound backend')

    def open_source(self, args):
        self.reads.append(args)
        case = args['case_id']
        row = {'A': self.a, 'B_A': self.b, 'B_B': self.c}[case]
        return ToolResult({'case_id': case}, (row,), (case,))


class HybridBinding:
    fingerprint = 'offline-dual-search-fixture'
    def __init__(self, tools):
        self.tools = tools
        self.queries = []
    def remaining(self):
        return {'requests': 10, 'input_tokens': 100000}
    def usage(self):
        return {}
    def search(self, *_args, **_kwargs):
        query, query_case, limit, action_id = _args
        self.queries.append(query)
        tools = self.tools
        def lead(row, span, passage):
            return {'case_id': row.case_id, 'span_bytes': span, 'source_hash': row.source_hash,
                    'rank': 1, 'score': 1.0,
                    'open_ref': {'case_id': row.case_id, 'source_hash': row.source_hash,
                                 'passage_ids': [passage]}}
        if query in ('issue terms', tools.a.text):
            hits = [
                {'case_id': 'B_A', 'score': 1.0, 'channels': {
                    'passage_bm25': lead(tools.b, [2500, 2700], 'A-early'),
                    'dense_passage': lead(tools.b, [2800, 3000], 'A-late')}},
                {'case_id': 'B_B', 'score': 0.8, 'channels': {
                    'passage_bm25': lead(tools.c, [22, 60], 'B-rule')}},
            ]
        else:
            hits = [
                {'case_id': 'B_A', 'score': 1.0, 'channels': {
                    'passage_bm25': lead(tools.b, [2500, 2700], 'A-early')}},
                {'case_id': 'B_B', 'score': 0.8, 'channels': {
                    'passage_bm25': lead(tools.c, [22, 60], 'B-rule')}},
            ]
        return {'hits': hits[:limit], 'query_case': query_case, 'query_sha256': sha(query.encode()),
                'request_id': 'local-request', 'timings': {}, 'policy': 'local-test',
                'execution_mode': 'offline', 'channels': {'case_bm25': [], 'passage_bm25': [], 'dense_passage': []},
                'model_requests': 0}


class ManyHitDualSearch:
    """Keep an eleventh same-case scored passage in the diagnostic pool only."""
    def __init__(self, tools):
        self.tools = tools

    def __call__(self, action, _execute_branch, _raw_reader):
        need = action['args']['_m6_need']
        hits = []
        raw = self.tools.b.text.encode('utf-8')
        for index in range(11):
            left = 1300 + index * 1300
            span = [left, left + 200]
            hit_ref = fingerprint(['B_A', self.tools.b.source_hash, span])
            hits.append({'case_id': 'B_A', 'source_hash': self.tools.b.source_hash,
                         'span_bytes': span, 'hit_ref': hit_ref, 'score': float(11-index),
                         'case_rank': 1, 'rank': index + 1,
                         'preview': {'text': raw[left:left+80].decode('utf-8'),
                                     'span_bytes': [left, left+80],
                                     'text_sha256': sha(raw[left:left+80])}})
        return ToolResult({'cm4_passage_review': True, 'm6_source_need': need,
                           'query_case': 'A', 'hits': hits[:10],
                           'dual_retrieval': {'scored_passages': hits}}, candidates=('B_A',))


class PassageReviewTests(unittest.TestCase):
    def test_relation_labels_commit_then_return_to_the_same_candidate_page(self):
        expected = {'same_decision': ('select', 'confirmed_identity'),
                    'different_decision': ('not_select', 'different_decision'),
                    'insufficient_evidence': ('not_select', 'insufficient_identity')}
        for relation, (decision, disposition) in expected.items():
            with self.subTest(relation=relation), TemporaryDirectory() as directory:
                engine, _ = self.make_engine(directory, page_size=1)
                engine.identity_check_enabled = True
                self.start(engine)
                # Enable the new profile after legacy fixture starts retrieval.
                engine.survey_first = True
                initial = engine.prepare(admit=False)
                engine.step(lambda p: choose(p, 'show_context_page'))
                page = engine.context()['passage_session']['survey_offset']
                current = engine.prepare(admit=False)
                card = current['payload']['m6']['cm_page']['candidates'][0]
                case = card['case_id']
                stale = choose(current, 'open_candidate_passages', candidate_ref=card['candidate_ref'])
                engine.step(stale)
                opened = engine.prepare(admit=False)
                fields = self.identity_check_fields(opened)
                roles = {key: [field['items']['enum'][0]] for key, field in fields.items()}
                engine.step({'action': 'request_identity_check', 'args': roles})
                frozen = engine.prepare(admit=False)
                schema = next(b for b in frozen['manifest']['schema']['anyOf']
                              if b['properties']['action']['const'] == 'conclude_candidate')
                props = schema['properties']['args']['properties']
                self.assertNotIn('decision', props)
                self.assertNotIn('disposition', props)
                args = {'identity_relation': relation, 'reason': 'A scripted comparison tests host mapping.',
                        'bridge': 'The identity evidence is compared on both sides.',
                        'a_refs': roles['a_refs'], 'b_refs': roles['b_rule_refs'],
                        'identity_refs': roles['b_identity_refs']}
                invalid = {'action': 'conclude_candidate', 'args': {**args, 'identity_relation': 'invented'}}
                self.assertFalse(Draft202012Validator(frozen['manifest']['schema']).is_valid(invalid))
                wrong_side = {'action': 'conclude_candidate', 'args': {
                    **args, 'identity_refs': roles['a_refs']}}
                self.assertFalse(Draft202012Validator(frozen['manifest']['schema']).is_valid(wrong_side))
                self.assertFalse(engine.context().get('candidate_conclusions'))
                engine.step({'action': 'conclude_candidate', 'args': args})
                final = next(iter(engine.context()['candidate_conclusions'].values()))[case]
                self.assertEqual((final['decision'], final['disposition']), (decision, disposition))
                self.assertEqual(final['identity_relation'], relation)
                self.assertIsNone(engine.context()['candidate_id'])
                self.assertEqual(engine.context()['passage_session']['survey_offset'], page)
                returned = engine.prepare(admit=False)
                self.assertEqual(returned['payload']['m6']['cm_page']['candidates'][0]['case_id'], case)
                self.assertTrue(returned['payload']['m6']['cm_page']['candidates'][0]['review_complete'])
                self.assertFalse(Draft202012Validator(returned['manifest']['schema']).is_valid(stale))
                self.assertNotIn('return_to_candidates', [t['name'] for t in returned['payload']['available_tools']])

    def test_direct_negative_returns_to_candidates_and_pending_can_leave(self):
        with TemporaryDirectory() as directory:
            engine, _ = self.make_engine(directory)
            engine.identity_check_enabled = True
            self.start(engine)
            engine.survey_first = True
            opened, _ = self.survey_then_open(engine, 'B_A')
            engine.step(lambda p: choose(p, 'return_to_candidates', reason='Read another candidate first.'))
            self.assertFalse(engine.context().get('candidate_conclusions'))
            reopened, _ = self.survey_then_open(engine, 'B_A')
            refs = self.conclusion(reopened, decision='not_select')
            engine.step({'action': 'conclude_candidate', 'args': refs})
            returned = engine.prepare(admit=False)
            self.assertIsNone(engine.context()['candidate_id'])
            self.assertEqual(returned['payload']['m6']['cm_context']['mode'], 'results')

    def identity_check_fields(self, opened):
        branch = next(row for row in opened['manifest']['schema']['anyOf']
                      if row['properties']['action']['const'] == 'request_identity_check')
        return branch['properties']['args']['properties']

    def test_identity_review_starts_on_open_even_without_a_recognized_title(self):
        tools = PassageTools()
        opening = '[1]\r\nThe court heard four applications together.\r\n'
        tools.b = source('B_A', opening + '[2]\r\n' + 'Reasoning. ' * 500)
        with TemporaryDirectory() as directory:
            engine, _ = self.make_engine(directory, tools=tools)
            engine.identity_check_enabled = True
            self.start(engine)
            opened, _ = self.survey_then_open(engine, 'B_A')
            payload = opened['payload']
            self.assertIn('Check identity first', payload['last_action_feedback']['guidance'])
            self.assertEqual(payload['m6']['cm_context']['mode'], 'assessment')
            self.assertEqual(payload['m6']['candidate_progress']['conclusion_status'], 'pending')
            fields = self.identity_check_fields(opened)
            roles = {role: [field['items']['enum'][0]] for role, field in fields.items()}
            opening_ref = roles['b_identity_refs'][0]
            opening_rows = [row for row in payload['excerpts'] if row['ref'] == opening_ref]
            self.assertEqual(len(opening_rows), 1)
            self.assertTrue(opening_rows[0]['text'].startswith(opening))
            self.assertEqual(opening_rows[0]['span_bytes'][0], 0)
            self.assertIn('return_to_candidates', [tool['name'] for tool in payload['available_tools']])
            engine.step({'action': 'request_identity_check', 'args': roles})
            engine.step(lambda p: choose(p, 'conclude_candidate', decision='select',
                                         disposition='confirmed_identity',
                                         reason='Replay of a positive identity conclusion.',
                                         bridge='Scripted identity bridge for host validation.',
                                         a_refs=roles['a_refs'], b_refs=roles['b_rule_refs'],
                                         identity_refs=roles['b_identity_refs']))
            final = next(iter(engine.context()['candidate_conclusions'].values()))['B_A']
            self.assertEqual(final['decision'], 'select')

    def test_aqua_gem_body_quote_is_not_offered_as_candidate_identity(self):
        path = Path('data/task1_train_files_2026/cases/011064.txt')
        if not path.exists():
            self.skipTest('Requires the original candidate from the pilot')

        class AquaGemBinding(HybridBinding):
            def search(self, *args, **kwargs):
                result = super().search(*args, **kwargs)
                for hit in result['hits']:
                    if hit['case_id'] == 'B_A':
                        for channel in hit['channels'].values():
                            channel['span_bytes'] = [11401, 12963]
                return result

        tools = PassageTools()
        tools.b = source('B_A', path.read_bytes().decode('utf-8'))
        with TemporaryDirectory() as directory:
            engine, _ = self.make_engine(directory, tools=tools, binding_cls=AquaGemBinding)
            engine.identity_check_enabled = True
            self.start(engine)
            opened, _ = self.survey_then_open(engine, 'B_A')
            payload = opened['payload']
            fields = self.identity_check_fields(opened)
            quote = next(row for row in payload['excerpts'] if row['case_id'] == 'B_A'
                         and row['span_bytes'][0] > 900 and 'Aqua-Gem' in row['text'])
            self.assertIn(quote['ref'], fields['b_rule_refs']['items']['enum'])
            self.assertNotIn(quote['ref'], fields['b_identity_refs']['items']['enum'])
            self.assertTrue(any(row['ref'] in fields['b_identity_refs']['items']['enum'] and "O'Keefe, J." in row['text']
                                for row in payload['excerpts']))

    def test_prothonotary_opening_is_offered_for_identity_check(self):
        path = Path('data/task1_train_files_2026/cases/070847.txt')
        if not path.exists():
            self.skipTest('Requires the original candidate from the pilot')
        tools = PassageTools()
        tools.b = source('B_A', path.read_bytes().decode('utf-8'))
        with TemporaryDirectory() as directory:
            engine, _ = self.make_engine(directory, tools=tools)
            engine.identity_check_enabled = True
            self.start(engine)
            opened, _ = self.survey_then_open(engine, 'B_A')
            refs = self.identity_check_fields(opened)['b_identity_refs']['items']['enum']
            rows = opened['payload']['excerpts']
            self.assertTrue(any(row['ref'] in refs and 'Hargrave, Prothonotary' in row['text']
                                and all(f'T-{docket}-01' in row['text'] for docket in range(1520, 1524))
                                and row['span_bytes'][0] == 0 for row in rows))

    def make_engine(self, directory, binding_cls=HybridBinding, review_limit=10, dual_search=None, tools=None, page_size=5):
        tools = tools or PassageTools()
        hybrid = binding_cls(tools)
        tools.hybrid = hybrid
        dual_search = dual_search(tools) if isinstance(dual_search, type) else dual_search
        rows = {'A': tools.a, 'B_A': tools.b, 'B_B': tools.c}
        identity = RunIdentity('cm4-passage-review', 'A', tools.a.source_hash,
                               'candidate-set', 'index', 'profile', 'model', 'prompt', 'tools', 'tokenizer')
        search = DualSearch(lambda _query, docs: [float(len(docs) - i) for i, _ in enumerate(docs)],
                             review_limit=review_limit)
        engine = Engine(directory, identity=identity, tools=tools, count_tokens=count,
                        raw_reader=lambda case: rows[case].text.encode('utf-8'),
                        config=AdaptiveConfig(channel='hybrid'), hybrid_search=hybrid,
                        gate_enabled=True, dual_search=dual_search or search, page_size=page_size, selector=select_supported_cases,
                        selector_fingerprint=selector_fingerprint())
        return engine, tools

    def start(self, engine):
        engine.step(lambda p: screen(p, 'The Court applied the notice fairness rule in this dispute.'))
        engine.step(lambda p: choose(p, 'search_cases_by_issue'))

    def test_search_cannot_conclude_before_the_other_candidate_page_is_shown(self):
        with TemporaryDirectory() as directory:
            engine, _ = self.make_engine(directory, page_size=1)
            self.start(engine)
            opened, _ = self.survey_then_open(engine, 'B_A')
            self.assertEqual(opened['payload']['m6']['cm_context']['candidate_id'], 'B_A')
            engine.step(lambda p: choose(p, 'return_to_candidates', reason='Review the other candidate page.'))
            page = engine.prepare(admit=False)
            nav = page['payload']['m6']['candidate_navigation']
            self.assertEqual(nav['unseen_after_this_page'], 1)
            self.assertFalse(any(t['name'] == 'conclude_search_query' for t in page['payload']['available_tools']))
            engine.step(lambda p: choose(p, 'show_context_page', page_ref=nav['next_unseen_page']))
            last_page = engine.prepare(admit=False)
            self.assertEqual(last_page['payload']['m6']['cm_page']['candidates'][0]['case_id'], 'B_B')
            engine.step(lambda p: choose(p, 'conclude_search_query', reason='The remaining candidates stay pending.'))
            query = next(iter(query_review.queries(engine.events(), engine.context()).values()))
            self.assertEqual(query['conclusion']['outcome'], 'partially_resolved')
            self.assertIn('B_B', query['conclusion']['not_read_candidate_ids'])
            self.assertEqual(engine.prepare(admit=False)['status'], 'ready')

    def test_permit_only_dispatches_the_real_multiline_source_and_scoped_citation(self):
        source_path = Path('data/task1_train_files_2026/cases/021095.txt')
        if not source_path.exists():
            self.skipTest('Requires canonical pilot corpus')
        raw = source_path.read_bytes()
        excerpt = raw[7580:8832]
        first = excerpt.index(b'"... discretionary')
        end = excerpt.index(b'"Where such')
        primary = excerpt[first:end]
        citation_start = excerpt.index(b'315 N.R. 175')
        tools = PassageTools()
        tools.a = source('A', excerpt.decode('utf-8'))
        tools.query_paragraphs = ({'handle': 'p000001', 'span_bytes': [0, len(excerpt)]},)
        with TemporaryDirectory() as directory:
            engine, _ = self.make_engine(directory, tools=tools)
            prepared = engine.prepare(admit=False)
            segments = prepared['payload']['m6']['source_gate_segments']
            citation_ref = next(ref for ref, row in segments.items()
                                if row['span_bytes'][0] <= citation_start < row['span_bytes'][1])
            support_span = segments[citation_ref]['span_bytes']
            engine.step(lambda p: choose(
                p, 'assess_source_need', decision='search_needed', attribution='party',
                reason_code='authority_reference', reason='The respondent sets out the test and its exceptions.',
                context_complete=True, sufficient_for_search=True, proposition_quote=primary.decode('utf-8'),
                a_supports=[{'role': 'citation', 'span_ref': citation_ref}]))
            pending = engine.prepare(admit=False)
            action = choose(pending, 'search_cases_by_issue')
            self.assertEqual(set(action['args']), {'source_need_ref'})
            validator = Draft202012Validator(pending['manifest']['schema'])
            self.assertFalse(validator.is_valid({**action, 'args': {**action['args'], 'issue': 'other issue'}}))
            engine.step(action)
            self.assertEqual(len(tools.hybrid.queries), 1)
            observed = tools.hybrid.queries[0].encode('utf-8')
            self.assertTrue(observed.startswith(primary.rstrip()))
            self.assertIn(b'315 N.R. 175', observed)
            self.assertIn(excerpt[support_span[0]:support_span[1]], observed)
            engine.step(lambda p: choose(p, 'conclude_search_query', reason='Leave remaining candidates pending.'))
            resumed = engine.prepare(admit=False)
            self.assertEqual(resumed['status'], 'ready')
            self.assertEqual(resumed['payload']['query_anchor']['paragraph_ref'], 'p000001')
            self.assertEqual(resumed['payload']['query_anchor']['span_bytes'], [first, end - (len(primary) - len(primary.rstrip()))])

    def test_real_heading_cannot_search_and_negative_covers_only_the_selected_item(self):
        source_path = Path('data/task1_train_files_2026/cases/021095.txt')
        if not source_path.exists():
            self.skipTest('Requires canonical pilot corpus')
        raw = source_path.read_bytes()
        for base, end, quote, decision, heading in (
                (8834, 9300, raw[9151:9170], 'search_needed', True),
                (929, 2551, raw[1067:1280], 'no_search_needed', [])):
            with self.subTest(decision=decision), TemporaryDirectory() as directory:
                tools = PassageTools()
                tools.a = source('A', raw[base:end].decode('utf-8'))
                tools.query_paragraphs = ({'handle': 'p000001', 'span_bytes': [0, end - base]},)
                engine, _ = self.make_engine(directory, tools=tools)
                def choose_span(p):
                    return choose(p, 'assess_source_need', decision=decision,
                    attribution='party', reason_code='legal_proposition', reason='Evaluate this literal span.',
                    context_complete=True, sufficient_for_search=True, proposition_quote=quote.decode('utf-8'))
                engine.step(choose_span)
                gate, = engine.context()['source_gate'].values()
                after = engine.prepare(admit=False)
                self.assertNotIn('search_cases_by_issue', [t['name'] for t in after['payload']['available_tools']])
                if heading:
                    self.assertEqual(gate['status'], 'unresolved')
                    self.assertIn('heading', gate['validation_message'])
                else:
                    self.assertEqual(gate['status'], 'screened')
                    self.assertEqual(gate['proposition']['span_bytes'], [1067 - base, 1067 - base + len(quote.rstrip())])
                    self.assertIn('assess_source_need', [t['name'] for t in after['payload']['available_tools']])

    def survey_then_open(self, engine, candidate):
        """Open a visible candidate directly; grouped review has no priority gate."""
        current = engine.prepare(admit=False)
        self.assertTrue(current['payload']['m6']['query_review']['query_id'])
        cards = current['payload']['m6']['cm_page']['candidates']
        self.assertNotIn('prioritize_query_results', [tool['name'] for tool in current['payload']['available_tools']])
        self.assertTrue(any(tool['name'] == 'open_candidate_passages'
                            for tool in current['payload']['available_tools']))
        open_branch = next(row for row in current['manifest']['schema']['anyOf']
                           if row['properties']['action']['const'] == 'open_candidate_passages')
        candidate_ref = next(ref for ref in open_branch['properties']['args']['properties']['candidate_ref']['enum']
                             if current['manifest']['handles'][ref]['case_id'] == candidate)
        engine.step(lambda p: choose(p, 'open_candidate_passages', candidate_ref=candidate_ref))
        return engine.prepare(admit=False), cards

    def conclusion(self, prepared, decision='select'):
        rows = prepared['payload']['excerpts']
        return {'decision': decision, 'reason': 'The current evidence supports this final case conclusion.',
                'a_refs': [next(r['ref'] for r in rows if r['case_id'] == 'A')],
                'b_refs': [next(r['ref'] for r in rows if r['case_id'] == 'B_A' and r['span_bytes'][0] > 0)],
                'identity_refs': [next(r['ref'] for r in rows if r['case_id'] == 'B_A' and r['span_bytes'][0] == 0)] if decision == 'select' else []}

    def search_hits(self, engine, tools, spans):
        hits = [{'case_id': 'B_A', 'source_hash': tools.b.source_hash, 'span_bytes': span} for span in spans]
        engine.harness.m3.search_case = lambda args: ToolResult({'hits': hits})

    def test_grouped_model_view_hides_rank_scores_and_merges_overlapping_raw_windows(self):
        with TemporaryDirectory() as directory:
            engine, _ = self.make_engine(directory)
            self.start(engine)
            prepared, cards = self.survey_then_open(engine, 'B_A')
            payload = prepared['payload']
            self.assertFalse(recursively_has_key(payload, {'rank', 'score', 'top_k', 'top'}))
            self.assertEqual(len([row for row in payload['m6']['passages'] if row['hit_ref']]), 2)
            merged = [row for row in payload['excerpts'] if row['case_id'] == 'B_A'
                      and row['span_bytes'][0] <= 2500 and row['span_bytes'][1] >= 3000]
            self.assertEqual(len(merged), 1, 'overlapping candidate windows should be delivered as one raw span')
            self.assertEqual({row['case_id'] for row in cards}, {'B_A', 'B_B'})
            self.assertFalse(recursively_has_key(cards, {'rank', 'score'}))
            source_spans = [row['span_bytes'] for row in payload['excerpts'] if row['case_id'] == 'B_A']
            self.assertEqual(source_spans, sorted(source_spans), 'grouped raw evidence should follow source order')

    def test_passage_aliases_bind_wire_schema_and_restore_canonical_evidence(self):
        from jsonschema import Draft202012Validator, ValidationError
        with TemporaryDirectory() as directory:
            engine, _ = self.make_engine(directory)
            self.start(engine)
            prepared, _ = self.survey_then_open(engine, 'B_A')
            aliases = prepared['manifest']['wire_aliases']
            canonical_rows = prepared['manifest']['excerpts']
            wire_rows = prepared['payload']['excerpts']
            for wire, canonical in zip(wire_rows, canonical_rows):
                self.assertEqual(aliases[wire['ref']], canonical['ref'])
                self.assertLess(len(wire['ref']), len(canonical['ref']))
                self.assertEqual(wire['text'], canonical['text'])
                self.assertEqual(wire['span_bytes'], list(canonical['span_bytes']))
            action = {'action': 'conclude_candidate', 'args': self.conclusion(prepared)}
            schema = Draft202012Validator(prepared['manifest']['schema'])
            schema.validate(action)
            canonical_action = restore_action(action, aliases)
            with self.assertRaises(ValidationError):
                schema.validate(canonical_action)
            with self.assertRaises(ValidationError):
                schema.validate({**action, 'args': {**action['args'], 'a_refs': ['unissued-ref']}})
            engine.step(lambda p: action)
            query = query_review.active(engine.events(), engine.context())
            final = engine.context()['candidate_conclusions'][query['query_id']]['B_A']
            for field in ('a_refs', 'b_refs', 'identity_refs'):
                self.assertEqual(final[field], canonical_action['args'][field])

    def test_group_reads_only_top_ten_and_model_can_page_to_a_distant_top_ten_hit(self):
        with TemporaryDirectory() as directory:
            engine, _ = self.make_engine(directory, dual_search=ManyHitDualSearch)
            self.start(engine)
            prepared, _ = self.survey_then_open(engine, 'B_A')
            payload = prepared['payload']
            passages = [row for row in payload['m6']['passages'] if row['hit_ref']]
            self.assertEqual(len(passages), 10, 'only the reranker top ten belong to the opened group')
            spans = [row['source_span'] for row in passages]
            self.assertEqual(spans, sorted(spans), 'the displayed group should preserve source order')
            excluded_pool_span = [14300, 14500]
            self.assertNotIn(excluded_pool_span, spans)
            self.assertFalse(any(row['case_id'] == 'B_A' and row['span_bytes'] == excluded_pool_span
                                 for row in payload['excerpts']))
            self.assertTrue(any(tool['name'] == 'continue_raw_evidence'
                                for tool in payload['available_tools']),
                            'distant top-ten spans should remain available for model-directed reading')

            continuation = next(row for row in prepared['manifest']['schema']['anyOf']
                                if row['properties']['action']['const'] == 'continue_raw_evidence')
            refs = continuation['properties']['args']['properties']['context_ref']['enum']
            later_ref = next(ref for ref in refs
                             if prepared['manifest']['handles'][ref]['kind'] == 'continuation'
                             and prepared['manifest']['handles'][ref]['region_index'] == 9)
            engine.step(lambda p: choose(p, 'continue_raw_evidence', context_ref=later_ref))
            later = engine.prepare(admit=False)
            self.assertTrue(any(row['case_id'] == 'B_A' and
                                row['span_bytes'][0] <= spans[9][0] and
                                row['span_bytes'][1] >= spans[9][1]
                                for row in later['payload']['excerpts']),
                            'the model can open a later same-candidate passage while keeping B active')
            self.assertEqual(later['payload']['m6']['cm_context']['candidate_id'], 'B_A')

    def test_intro_labels_literal_summary_and_fallback_as_semantically_unverified(self):
        def intro(text):
            raw = text.encode('utf-8')
            fake_engine = SimpleNamespace(store=SimpleNamespace(raw_reader=lambda _case: raw))
            records = _intro(fake_engine, 'B', sha(raw))
            return [(row['text'], row['provenance']['source_label'],
                     row['provenance']['semantic_status']) for row in records]

        summary_rows = intro('Case name: Court v Party\nSummary: The Court adopts the notice test. - Topic 123\n'
                             'Counsel: Counsel A\n[1] Background\nThe facts follow.')
        summary = next(row for row in summary_rows if 'Summary' in row[1])
        self.assertEqual(summary[0], 'The Court adopts the notice test.')
        self.assertEqual(summary[2], 'unverified')

        fallback_rows = intro('Case name: Court v Party\nNo summary available.\nCounsel: Counsel A\n'
                              '[1] Background\nThe facts follow.')
        fallback = next(row for row in fallback_rows if 'automatically selected' in row[1])
        self.assertEqual(fallback[2], 'unverified')
        self.assertIn('[1] Background', fallback[0])

    def test_final_once_at_case_level_and_locked_after_reopen(self):
        from pipeline_v2.experiments.context_manager_v2 import passage_review
        for decision in ('select', 'not_select'):
            with self.subTest(decision=decision), TemporaryDirectory() as directory:
                engine, _ = self.make_engine(directory)
                self.start(engine)
                prepared, _ = self.survey_then_open(engine, 'B_A')
                args = self.conclusion(prepared, decision)
                engine.step(lambda p: choose(p, 'conclude_candidate', **args))
                self.assertEqual(engine.context()['candidate_id'], 'B_A')
                query = query_review.active(engine.events(), engine.context())
                final = passage_review.conclusions(engine.context(), query)
                self.assertEqual(list(final), ['B_A'])
                self.assertEqual(final['B_A']['decision'], decision)
                self.assertNotIn('passage_votes', engine.context())
                self.assertEqual(select_supported_cases(engine.state().snapshot())['prediction'], ['B_A'] if decision == 'select' else [])
                engine.step(lambda p: choose(p, 'return_to_candidates', reason='Read another candidate temporarily.'))
                resumed, _ = self.survey_then_open(engine, 'B_A')
                self.assertNotIn('conclude_candidate', [t['name'] for t in resumed['payload']['available_tools']])
                self.assertEqual(resumed['payload']['m6']['candidate_progress']['conclusion_status'], 'final')
                engine, _ = self.make_engine(directory)
                resumed = engine.prepare(admit=False)
                self.assertNotIn('conclude_candidate', [t['name'] for t in resumed['payload']['available_tools']])
                self.assertEqual(resumed['payload']['m6']['candidate_progress']['decision'], decision)
                for other in (decision, 'not_select' if decision == 'select' else 'select'):
                    with self.assertRaisesRegex(HarnessError, 'already final'):
                        passage_review.execute(engine, None, engine.state(), engine.context(), query,
                            {'action': 'conclude_candidate', 'args': {**args, 'decision': other}}, resumed['manifest'], 'repeat')

    def test_temporary_leave_keeps_pending_and_partial_query(self):
        with TemporaryDirectory() as directory:
            engine, _ = self.make_engine(directory)
            self.start(engine)
            prepared, _ = self.survey_then_open(engine, 'B_A')
            self.assertEqual(prepared['payload']['m6']['candidate_progress']['conclusion_status'], 'pending')
            self.assertEqual(prepared['payload']['m6']['candidate_progress']['decision'], 'not_select')
            engine.step(lambda p: choose(p, 'return_to_candidates', reason='Leave without finalizing this candidate.'))
            resumed, _ = self.survey_then_open(engine, 'B_A')
            self.assertIn('conclude_candidate', [t['name'] for t in resumed['payload']['available_tools']])
            engine.step(lambda p: choose(p, 'return_to_candidates', reason='Keep this candidate pending.'))
            engine.step(lambda p: choose(p, 'conclude_search_query', reason='Insufficient evidence; candidates remain pending.'))
            query = next(iter(query_review.queries(engine.events(), engine.context()).values()))
            progress = query_review.progress(query, engine.state())
            self.assertEqual(query['conclusion']['outcome'], 'partially_resolved')
            self.assertEqual(progress['candidates_pending'], 2)
            self.assertEqual(progress['final_not_select_candidates'], 0)
            self.assertFalse(engine.context().get('candidate_conclusions'))

    def test_final_negative_without_evidence_is_not_pending(self):
        with TemporaryDirectory() as directory:
            engine, _ = self.make_engine(directory)
            self.start(engine)
            self.survey_then_open(engine, 'B_A')
            engine.step(lambda p: choose(p, 'conclude_candidate', decision='not_select',
                reason='No sufficient identity evidence to choose this candidate.', a_refs=[], b_refs=[], identity_refs=[]))
            progress = query_review.progress(query_review.active(engine.events(), engine.context()), engine.state())
            self.assertEqual(progress['final_not_select_candidates'], 1)
            self.assertEqual(progress['candidates_pending'], 1)
            self.assertEqual(progress['assessed_by_relation'], {})
            self.assertEqual(progress['conclusions_by_decision'], {'select': 0, 'not_select': 1})
            self.assertFalse(engine.state().assessments, 'No evidence-free legacy assessment should be fabricated')

    def test_positive_requires_identity_and_wrong_side_refs_rejected(self):
        with TemporaryDirectory() as directory:
            engine, _ = self.make_engine(directory)
            self.start(engine)
            prepared, _ = self.survey_then_open(engine, 'B_A')
            args = self.conclusion(prepared)
            engine.step(lambda p: choose(p, 'conclude_candidate', **{**args, 'identity_refs': []}))
            self.assertIn('explicit candidate identity', engine.prepare(admit=False)['payload']['last_action_feedback']['last_action']['reason'])
            self.assertFalse(engine.context().get('candidate_conclusions'))
            args['a_refs'] = args['b_refs']
            engine.step(lambda p: {'action': 'conclude_candidate', 'args': args})
            receipt = next(row for row in reversed(engine.events()) if row['kind'] == 'request_result')
            self.assertEqual(receipt['schema_validation'], 'rejected')

    def test_schema_omits_unique_items_but_host_rejects_duplicate_refs(self):
        from jsonschema import Draft202012Validator, ValidationError
        with TemporaryDirectory() as directory:
            engine, _ = self.make_engine(directory)
            self.start(engine)
            prepared, _ = self.survey_then_open(engine, 'B_A')
            self.assertFalse(recursively_has_key(prepared['manifest']['schema'], {'uniqueItems'}))
            for field in ('a_refs', 'b_refs', 'identity_refs'):
                args = self.conclusion(engine.prepare(admit=False))
                args[field] = [args[field][0], args[field][0]]
                if field == 'a_refs':
                    with self.assertRaises(ValidationError):
                        Draft202012Validator(prepared['manifest']['schema']).validate(
                            {'action': 'conclude_candidate', 'args': args})
                    continue
                engine.step(lambda p: choose(p, 'conclude_candidate', **args))
                receipt = next(row for row in reversed(engine.events()) if row['kind'] == 'request_result')
                self.assertNotEqual(receipt.get('schema_validation'), 'rejected')
                outcome = next(row for row in reversed(engine.events()) if row['kind'] == 'action_result')
                self.assertEqual(outcome['status'], 'error')
                self.assertIn('Duplicate', outcome['reason'])
                self.assertFalse(engine.context().get('candidate_conclusions'))
            valid_args = self.conclusion(engine.prepare(admit=False))
            engine.step(lambda p: choose(p, 'conclude_candidate', **valid_args))
            self.assertEqual(select_supported_cases(engine.state().snapshot())['prediction'], ['B_A'])

    def test_progress_warning_and_failed_tool_result_reach_payload(self):
        with TemporaryDirectory() as directory:
            engine, _ = self.make_engine(directory)
            self.start(engine)
            warning = {'cycles': 4, 'reason': 'repeated action'}
            self.assertEqual(engine.prepare(admit=False, progress_warning=warning)['payload']['last_action_feedback']['progress_warning'], warning)
            self.survey_then_open(engine, 'B_A')
            engine.step(lambda p: choose(p, 'read_case_passages', focus='lawx'))
            feedback = engine.prepare(admit=False)['payload']['last_action_feedback']['last_action']
            self.assertEqual(feedback['status'], 'error')
            self.assertIn('two words', feedback['reason'])

    def test_within_case_old_first_new_second_and_explicit_revisit(self):
        with TemporaryDirectory() as directory:
            engine, tools = self.make_engine(directory)
            self.start(engine)
            self.survey_then_open(engine, 'B_A')
            # Receiving the open-B payload establishes old byte coverage.
            self.search_hits(engine, tools, [[2500, 2700], [8000, 8200]])
            engine.step(lambda p: choose(p, 'read_case_passages', focus='notice fairness'))
            prepared = engine.prepare(admit=False)
            search = prepared['payload']['m6']['within_case_search']
            self.assertEqual(search['status'], 'new_content')
            self.assertEqual(search['span_bytes'], [8000, 8200])
            self.assertEqual(search['new_bytes'], 200)
            self.assertIn('revisit_case_passage', [t['name'] for t in prepared['payload']['available_tools']])
            # Repeating focus returns old spans after the new target is received.
            engine.step(lambda p: choose(p, 'read_case_passages', focus='notice fairness'))
            old = engine.prepare(admit=False)
            self.assertEqual(old['payload']['m6']['within_case_search']['status'], 'already_read')
            self.assertEqual(old['payload']['m6']['within_case_search']['new_bytes'], 0)
            target = next(ref for ref, value in old['manifest']['handles'].items()
                          if ref.startswith('revisit-') and value['span_bytes'] == [2500, 2700])
            engine.step(lambda p: choose(p, 'revisit_case_passage', target_ref=target))
            reopened = engine.prepare(admit=False)
            self.assertTrue(any(r['case_id'] == 'B_A' and r['span_bytes'][0] <= 2500 and r['span_bytes'][1] >= 2700
                                for r in reopened['payload']['excerpts']))

    def test_within_case_partial_overlap_no_hits_and_foreign_source(self):
        with TemporaryDirectory() as directory:
            engine, tools = self.make_engine(directory)
            self.start(engine)
            self.survey_then_open(engine, 'B_A')
            self.search_hits(engine, tools, [[3100, 3300]])
            engine.step(lambda p: choose(p, 'read_case_passages', focus='notice fairness'))
            search = engine.prepare(admit=False)['payload']['m6']['within_case_search']
            self.assertEqual(search['new_spans'], [[3180, 3300]])
            self.assertEqual(search['new_bytes'], 120)
            self.search_hits(engine, tools, [])
            engine.step(lambda p: choose(p, 'read_case_passages', focus='other phrase'))
            empty = engine.prepare(admit=False)
            self.assertEqual(empty['payload']['m6']['within_case_search']['status'], 'no_hits')
            self.assertNotIn('revisit_case_passage', [t['name'] for t in empty['payload']['available_tools']])
            engine.harness.m3.search_case = lambda args: ToolResult({'hits': [{'case_id': 'B_B', 'source_hash': tools.c.source_hash, 'span_bytes': [22,60]}]})
            engine.step(lambda p: choose(p, 'read_case_passages', focus='foreign phrase'))
            last = engine.prepare(admit=False)['payload']['last_action_feedback']['last_action']
            self.assertEqual(last['status'], 'error')
            self.assertIn('different candidate source', last['reason'])

    def test_search_starts_at_new_tail_after_long_received_prefix(self):
        from pipeline_v2.experiments.context_manager_v2 import passage_review
        with TemporaryDirectory() as directory:
            engine, tools = self.make_engine(directory)
            self.start(engine)
            self.survey_then_open(engine, 'B_A')
            self.search_hits(engine, tools, [[0, 10000]])
            engine.step(lambda p: choose(p, 'read_case_passages', focus='first phrase'))
            engine.prepare(admit=False)
            self.assertFalse(passage_review._contains([0,10000], passage_review.delivered(engine, 'B_A', tools.b.source_hash)))
            # Receive successive payloads and explicitly continue the same target.
            for _ in range(5):
                current = engine.prepare(admit=False)
                if passage_review._contains([0,10000], passage_review.delivered(engine, 'B_A', tools.b.source_hash)):
                    break
                extra = next((ref for ref,target in current['manifest']['handles'].items()
                              if target.get('kind') == 'extra_continuation'), None)
                if extra:
                    engine.step(lambda p: choose(p, 'continue_raw_evidence', context_ref=extra))
                else:
                    engine.step(lambda p: choose(p, 'read_case_passages', focus='first phrase'))
            # The request admitting this final search also receives the last old page.
            self.search_hits(engine, tools, [[0, 11000]])
            engine.step(lambda p: choose(p, 'read_case_passages', focus='tail phrase'))
            prepared = engine.prepare(admit=False)
            self.assertEqual(prepared['payload']['m6']['within_case_search']['new_spans'], [[10000,11000]])
            self.assertEqual(engine.context()['passage_session']['extra_cursor'], 10000)
            self.assertTrue(any(r['case_id'] == 'B_A' and r['span_bytes'][0] == 10000 and r['span_bytes'][1] == 11000
                                for r in prepared['payload']['excerpts']))

    def test_cross_query_same_need_negative_preserves_earlier_select(self):
        from copy import deepcopy
        from pipeline_v2.experiments.context_manager_v2 import passage_review
        with TemporaryDirectory() as directory:
            engine, _ = self.make_engine(directory)
            self.start(engine)
            prepared, _ = self.survey_then_open(engine, 'B_A')
            engine.step(lambda p: choose(p, 'conclude_candidate', **self.conclusion(prepared)))
            prepared = engine.prepare(admit=False)
            original = query_review.active(engine.events(), engine.context())
            query = deepcopy(original)
            query['query_id'] = 'different-search-same-need'
            context = engine.context()
            args = self.conclusion(prepared, 'not_select')
            with engine.harness.ledger.writer() as db:
                passage_review.execute(engine, db, engine.state(), context, query,
                    restore_action({'action': 'conclude_candidate', 'args': args}, prepared['manifest']['wire_aliases']),
                    prepared['manifest'], 'second-query-final')
            self.assertEqual(select_supported_cases(engine.state().snapshot())['prediction'], ['B_A'])
            self.assertEqual(engine.context()['candidate_conclusions'][query['query_id']]['B_A']['decision'], 'not_select')
            pending = deepcopy(query)
            pending['candidate_conclusions'] = {}
            pending['completed_candidates'] = []
            progress = query_review.progress(pending, engine.state())
            self.assertEqual(progress['assessed'], 0)
            self.assertEqual(progress['selected_candidates'], 0)

    def test_attribution_labels_describe_literal_window_not_semantic_detection(self):
        with TemporaryDirectory() as directory:
            engine, _ = self.make_engine(directory)
            self.start(engine)
            prepared, _ = self.survey_then_open(engine, 'B_A')
            tool = next(t for t in prepared['payload']['available_tools'] if t['name'] == 'read_passage_attribution')
            self.assertIn('1200 bytes', tool['description'])
            self.assertIn('does not identify attribution semantically', tool['description'])
            target = tool['parameters']['properties']['target_ref']['enum'][0]
            span = prepared['manifest']['handles'][target]['span_bytes']
            self.assertGreaterEqual(span[0], 1120)
            self.assertLessEqual(span[1], 4380)
            engine.step(lambda p: choose(p, 'read_passage_attribution', target_ref=target))
            raw = engine.prepare(admit=False)
            labels = [r['provenance']['source_label'] for r in raw['payload']['excerpts'] if r['case_id'] == 'B_A']
            self.assertTrue(any('speaker and quote source unverified' in label for label in labels))

    def test_identity_check_locks_role_evidence_and_commits_only_on_conclusion(self):
        from pipeline_v2.experiments.context_manager_v2 import passage_review

        with TemporaryDirectory() as directory:
            engine, _ = self.make_engine(directory)
            engine.identity_check_enabled = True
            self.start(engine)
            # A deterministic identity-region fixture tests roles separately
            # from the corpus heuristics that identify opening/header lines.
            with patch.object(passage_review, 'identity_regions', return_value=[[0, 12]]):
                opened, _ = self.survey_then_open(engine, 'B_A')
                refs = self.conclusion(opened)
                refs['identity_refs'] = [next(r['ref'] for r in opened['payload']['excerpts']
                                              if r['case_id'] == 'B_A' and r['span_bytes'] == [0, 12])]
                validator = Draft202012Validator(opened['manifest']['schema'])
                self.assertFalse(validator.is_valid({'action': 'conclude_candidate', 'args': refs}))
                request = {'action': 'request_identity_check', 'args': {
                    'a_refs': refs['a_refs'], 'b_identity_refs': refs['b_refs'], 'b_rule_refs': refs['b_refs']}}
                self.assertFalse(validator.is_valid(request))
                request['args']['b_identity_refs'] = refs['identity_refs']
                engine.step(request)
                locked = engine.prepare(admit=False)
            self.assertEqual({b['properties']['action']['const'] for b in locked['manifest']['schema']['anyOf']},
                             {'conclude_candidate'})
            self.assertFalse(engine.context().get('candidate_conclusions'))
            engine.step(lambda p: choose(p, 'conclude_candidate', **refs, disposition='confirmed_identity',
                                         bridge='The A citation matches the self-identifying line of B.'))
            final = next(iter(engine.context()['candidate_conclusions'].values()))['B_A']
            self.assertEqual(final['decision'], 'select')
            self.assertEqual(select_supported_cases(engine.state().snapshot())['prediction'], ['B_A'])
            after = engine.prepare(admit=False)
            self.assertNotIn('conclude_candidate', [t['name'] for t in after['payload']['available_tools']])


if __name__ == '__main__':
    unittest.main()
