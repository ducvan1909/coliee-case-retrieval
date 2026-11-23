"""Pinned-tokenizer regressions for source permits, without provider calls."""
from copy import deepcopy
from tempfile import TemporaryDirectory
import unittest

from pipeline_v2.experiments.context_manager_v2 import source_gate
from pipeline_v2.experiments.context_manager_v2.cli import choose
from pipeline_v2.experiments.context_manager_v2.tests import test_passage_review as fixtures
from pipeline_v2.tests.test_m6_adaptive import source


def assessment(prepared, paragraph):
    segments = prepared['payload']['m6']['source_gate_segments']
    ref = next(ref for ref, row in segments.items() if row['paragraph_ref'].split('@')[0] == paragraph)
    return choose(prepared, 'assess_source_need', paragraph_ref=segments[ref]['paragraph_ref'],
                  proposition_ref=ref, decision='search_needed', attribution='court',
                  context_complete=True, sufficient_for_search=True, reason_code='authority_reference',
                  reason='These literal source propositions refer to the same decision.')


class EmbeddingQueryBudgetTests(unittest.TestCase):
    def test_full_render_special_tokens_and_boundary(self):
        self.assertEqual(source_gate.embedding_query_budget('rule ' * 415),
                         {'input_tokens': 448, 'max_tokens': 448, 'accepted': True})
        self.assertEqual(source_gate.embedding_query_budget('rule ' * 416),
                         {'input_tokens': 449, 'max_tokens': 448, 'accepted': False})

    def test_454_token_group_splits_before_commit_and_executes_without_truncating(self):
        texts = ['rule ' * 140, 'y ' * 140, 'z ' * 139]
        self.assertTrue(all(len(text.encode()) <= 1000 for text in texts))
        self.assertEqual(source_gate.embedding_query_budget('\n'.join(texts))['input_tokens'], 454)
        tools = fixtures.PassageTools()
        tools.a = source('A', '\n'.join(texts))
        left = 0
        paragraphs = []
        for index, text in enumerate(texts, 1):
            end = left + len(text.encode())
            paragraphs.append({'handle': f'p{index:06}', 'span_bytes': [left, end]})
            left = end + 1
        tools.query_paragraphs = tuple(paragraphs)
        with TemporaryDirectory() as directory:
            engine, _ = fixtures.PassageReviewTests().make_engine(directory, tools=tools)
            engine.survey_first = True
            for paragraph in paragraphs:
                engine.step(lambda p, key=paragraph['handle']: assessment(p, key))
                self.assertIsNone(engine.state().final)
            refs = sorted(engine.context()['source_gate'], key=lambda ref:
                          engine.context()['source_gate'][ref]['proposition']['span_bytes'])
            engine.step(lambda p: choose(p, 'group_source_needs', source_need_refs=refs,
                                         reason='These source propositions refer to the same decision.'))
            context = engine.context()
            self.assertEqual([context['source_gate'][ref]['status'] for ref in refs],
                             ['approved', 'grouped', 'approved'])
            first, last = context['source_gate'][refs[0]], context['source_gate'][refs[2]]
            self.assertEqual(first['group_members'], refs[:2])
            self.assertEqual(first['embedding_split_from'], refs)
            self.assertEqual(last['embedding_split_from'], refs)
            self.assertEqual(source_gate.query_text(first), '\n'.join(texts[:2]))
            self.assertEqual(source_gate.query_text(last), texts[2])
            member = next(s for s in first['a_supports'] if s['role'] == 'group_member')
            self.assertEqual(member['span_bytes'], list(paragraphs[1]['span_bytes']))
            self.assertEqual(member['source_hash'], tools.a.source_hash)
            repeat = deepcopy(context)
            source_gate.fit_query_permits(repeat, 'A')
            self.assertEqual(repeat, context)
            engine.step(lambda p: choose(p, 'search_cases_by_issue', source_need_ref=refs[0]))
            self.assertIsNone(engine.state().final)
            self.assertEqual(tools.hybrid.queries, ['\n'.join(texts[:2])])
            self.assertTrue(engine.context()['source_gate'][refs[2]]['status'] == 'approved')

    def test_single_oversized_span_returns_to_source_selection(self):
        tools = fixtures.PassageTools()
        tools.a = source('A', 'x ' * 417)
        tools.query_paragraphs = ({'handle': 'p000001', 'span_bytes': tools.a.span_bytes},)
        with TemporaryDirectory() as directory:
            engine, _ = fixtures.PassageReviewTests().make_engine(directory, tools=tools)
            engine.survey_first = True
            engine.step(lambda p: assessment(p, 'p000001'))
            self.assertIsNone(engine.state().final)
            decision, = engine.context()['source_gate'].values()
            self.assertEqual(decision['status'], 'unresolved')
            self.assertEqual(decision['embedding_query_budget']['input_tokens'], 449)
            p = engine.prepare(admit=False)
            names = {tool['name'] for tool in p['payload']['available_tools']}
            self.assertIn('assess_source_need', names)
            self.assertNotIn('search_cases_by_issue', names)
            self.assertEqual(tools.hybrid.queries, [])

    def test_member_citation_provenance_is_kept_and_does_not_leak_after_split(self):
        rows = {}
        for i, text in enumerate(('rule ' * 140, 'court ' * 140, 'notice ' * 139)):
            rows[str(i)] = {'status': 'approved', 'source_hash': 'hash', 'source_ref': f'source-{i}',
                            'proposition': {'text': text, 'span_bytes': [i * 1000, i * 1000 + len(text)]},
                            'a_supports': [{'role': 'citation', 'text': '2010 FC 413',
                                            'source_hash': 'hash', 'source_ref': f'cite-{i}',
                                            'span_bytes': [4000 + i * 20, 4011 + i * 20]}]}
        rows['0'].update(group_members=['0', '1', '2'], group_kind='exact_citation', group_reason='same citation')
        rows['1'].update(status='grouped', grouped_into='0')
        rows['2'].update(status='grouped', grouped_into='0')
        ctx = {'source_gate': rows}
        source_gate.fit_query_permits(ctx, 'A')
        self.assertEqual(rows['0']['group_members'], ['0', '1'])
        self.assertEqual({s['source_ref'] for s in rows['0']['a_supports'] if s['role'] == 'citation'},
                         {'cite-0', 'cite-1'})
        self.assertEqual({s['source_ref'] for s in rows['2']['a_supports']}, {'cite-2'})
        once = deepcopy(ctx)
        source_gate.fit_query_permits(ctx, 'A')
        self.assertEqual(ctx, once)


if __name__ == '__main__':
    unittest.main()
