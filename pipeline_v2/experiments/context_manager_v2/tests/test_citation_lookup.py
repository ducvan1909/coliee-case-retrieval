"""Independent safety tests for direct citation identity decisions."""
from hashlib import sha256
from pathlib import Path
import unittest

from pipeline_v2.agent_harness.contracts import HarnessError
from pipeline_v2.experiments.context_manager_v2.cli import choose
from pipeline_v2.experiments.context_manager_v2.citation_lookup import (
    CitationLookup, approved_citation, literal_citations, self_citation,
)
from pipeline_v2.experiments.context_manager_v2.tests import test_passage_review
from pipeline_v2.tests.test_m6_adaptive import source


def digest(raw):
    return sha256(raw).hexdigest()


def need_for(a_raw, citation='315 N.R. 175', anchor_text='The order is reported at 315 N.R. 175.'):
    start = a_raw.index(citation.encode('utf-8'))
    end = start + len(citation.encode('utf-8'))
    anchor = anchor_text.encode('utf-8')
    return {
        'source_bound': True,
        'a_anchor': {'case_id': 'A', 'source_hash': digest(a_raw),
                     'span_bytes': [0, len(anchor)], 'text': anchor_text},
        'a_supports': [{'role': 'citation', 'case_id': 'A', 'source_hash': digest(a_raw),
                        'span_bytes': [start, end], 'text': citation}],
        'a_sources': [{'case_id': 'A', 'source_hash': digest(a_raw)}],
    }


def decision(citation='315 N.R. 175', extra=''):
    return ("Federal Court of Appeal\n" +
            f"Citation: {citation}\nDate: 2003-10-01\nDocket: A-123-03\n" +
            "\n" + extra + "The decision applies the relevant rule.\n").encode('utf-8')


class CitationLookupTests(unittest.TestCase):
    def test_structured_self_identification_with_unicode_offsets_is_directly_matchable(self):
        a_raw = 'La décision cite 315 N.R. 175.\n'.encode('utf-8')
        # Put a multibyte value before Citation so the saved byte span is tested
        # against UTF-8 offsets rather than character offsets.
        b_raw = ('Federal Court of Appeal\nDate: 1er décembre 2003\nCitation: 315 N.R. 175\n'
                 'Docket: A-123-03\n\nReasons by Élodie.\n').encode('utf-8')
        index = CitationLookup({'A': digest(a_raw), 'B': digest(b_raw)},
                               lambda case: {'A': a_raw, 'B': b_raw}[case])
        match = index.match(need_for(a_raw))
        self.assertIsNotNone(match)
        self.assertEqual(match['citation'], '315NR175')
        row = match['b']
        left, right = row['span_bytes']
        self.assertEqual(b_raw[left:right].decode('utf-8'), 'Citation: 315 N.R. 175')
        self.assertEqual(row['text_sha256'], digest(b_raw[left:right]))
        self.assertIsNone(index.verify(match))

    def test_citation_in_083611_body_is_not_self_identification(self):
        path = Path('data/task1_train_files_2026/cases/083611.txt')
        raw = path.read_bytes()
        self.assertIn(b'315 N.R. 175', raw)
        self.assertIsNone(self_citation(raw))
        a_raw = b'The cited order is 315 N.R. 175.'
        index = CitationLookup({'A': digest(a_raw), '083611': digest(raw)},
                               lambda case: {'A': a_raw, '083611': raw}[case])
        self.assertIsNone(index.match(need_for(a_raw)))

    def test_literal_citation_refs_include_sentence_final_period(self):
        text = 'The Court relied on 315 N.R. 175.'
        spans = literal_citations(text)
        self.assertEqual(len(spans), 1)
        start, end = spans[0]
        self.assertEqual(text.encode('utf-8')[start:end], b'315 N.R. 175')

    def test_duplicate_self_citations_are_ambiguous_and_do_not_select(self):
        a_raw = b'The cited order is 315 N.R. 175.'
        b1, b2 = decision(), decision(extra='Different file.\n')
        index = CitationLookup({'A': digest(a_raw), 'B1': digest(b1), 'B2': digest(b2)},
                               lambda case: {'A': a_raw, 'B1': b1, 'B2': b2}[case])
        self.assertIsNone(index.match(need_for(a_raw)))

    def test_body_citation_is_only_a_lead_even_when_header_has_another_citation(self):
        a_raw = b'The cited order is 315 N.R. 175.'
        b_raw = decision('2003 FCA 488', 'The reasons discuss 315 N.R. 175 as a cited authority.\n')
        index = CitationLookup({'A': digest(a_raw), 'B': digest(b_raw)},
                               lambda case: {'A': a_raw, 'B': b_raw}[case])
        self.assertIsNone(index.match(need_for(a_raw)))

    def test_same_source_is_not_selected_and_cannot_become_its_own_cited_decision(self):
        raw = ('Federal Court\nCitation: 315 N.R. 175\nDate: 2003-10-01\n'
               'Docket: T-1-03\n\nReasons.\n').encode()
        index = CitationLookup({'A': digest(raw)}, lambda case: raw)
        self.assertIsNone(index.match(need_for(raw)))

    def test_multiple_or_unscoped_a_citations_are_not_eligible(self):
        a_raw = b'The cited order is 315 N.R. 175.'
        need = need_for(a_raw)
        self.assertIsNone(approved_citation({**need, 'source_bound': False}, lambda _: a_raw))
        self.assertIsNone(approved_citation({**need, 'a_supports': need['a_supports'] * 2}, lambda _: a_raw))
        contradictory = {**need, 'a_anchor': {**need['a_anchor'],
                                                'text': 'This cites 2001 FC 1, not the order.'}}
        self.assertIsNone(approved_citation(contradictory, lambda _: a_raw))

    def test_a_source_hash_or_literal_drift_is_rejected(self):
        a_raw = b'The cited order is 315 N.R. 175.'
        need = need_for(a_raw)
        with self.assertRaises(HarnessError):
            approved_citation({**need, 'a_sources': [{'case_id': 'A', 'source_hash': 'stale'}]},
                              lambda _: a_raw)
        with self.assertRaises(HarnessError):
            approved_citation(need, lambda _: b'Changed source with 315 N.R. 175.')

    def test_header_must_be_labelled_complete_unique_and_leading(self):
        cases = [
            b'315 N.R. 175\nDate: 2003\nDocket: A-1\n',
            b'Federal Court\nDate: 2003\nDocket: A-1\n\nCitation: 315 N.R. 175\n',
            b'Federal Court\nCitation: 315 N.R. 175\nCitation: 315 N.R. 175\nDate: 2003\nDocket: A-1\n',
            b'Federal Court\nCitation: 315 N.R. 175\nDate: 2003\n\nDocket: A-1\n',
        ]
        for raw in cases:
            with self.subTest(raw=raw):
                self.assertIsNone(self_citation(raw))

    def test_engine_direct_match_is_persisted_into_final_prediction_without_retrieval(self):
        a_raw = b'The Court relied on 315 N.R. 175'
        b_raw = ('Federal Court of Appeal\nCitation: 315 N.R. 175\nDate: 2003-10-01\n'
                 'Docket: A-123-03\n\nReasons follow.\n').encode('utf-8')
        tools = test_passage_review.PassageTools()
        tools.a = source('A', a_raw.decode('utf-8'))
        tools.query_paragraphs = ({'handle': 'p000001', 'span_bytes': [0, len(a_raw)]},)
        tools.b = source('B_A', b_raw.decode('utf-8'))
        tools.c = source('B_B', 'A different decision with no structured citation.')
        raw_by_case = {'A': a_raw, 'B_A': b_raw, 'B_B': tools.c.text.encode('utf-8')}

        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            engine, _ = test_passage_review.PassageReviewTests().make_engine(directory, tools=tools)
            engine.survey_first = True
            engine.citation_lookup = CitationLookup(
                {case: digest(raw) for case, raw in raw_by_case.items()}, raw_by_case.__getitem__)
            prepared = engine.prepare(admit=False)
            segment_ref = next((ref for ref, row in prepared['payload']['m6']['source_gate_segments'].items()
                                if row.get('citation_cue')), None)
            self.assertIsNotNone(segment_ref, repr(prepared['payload']['m6'].get('source_gate_segments')))
            engine.step(lambda p: choose(
                p, 'assess_source_need', paragraph_ref='p000001', decision='search_needed',
                attribution='court', reason_code='authority_reference',
                reason='The decision identifies the authority it relies on.', context_complete=True,
                sufficient_for_search=True, proposition_quote=a_raw.decode('utf-8'),
                a_supports=[{'role': 'citation', 'span_ref': segment_ref}]))
            ready = engine.prepare(admit=False)
            self.assertIn('search_cases_by_issue', [row['name'] for row in ready['payload']['available_tools']])
            engine.step(lambda p: choose(p, 'search_cases_by_issue'))

            context = engine.context()
            self.assertIn('host_citation_matches', context, repr(engine.events()[-4:]))
            self.assertEqual(len(context['host_citation_matches']), 1)
            self.assertEqual(len(context['candidate_conclusions']), 1)
            conclusion = next(iter(context['candidate_conclusions'].values()))['B_A']
            self.assertEqual(conclusion['decision'], 'select')
            self.assertEqual(conclusion['selection_origin'], 'host_exact_citation')
            self.assertEqual(tools.hybrid.queries, [])

            final_prompt = engine.prepare(admit=False)
            self.assertIn('finish_case_review', [row['name'] for row in final_prompt['payload']['available_tools']])
            engine.step(lambda p: choose(p, 'finish_case_review', reason='complete_policy'))
            final = engine.state().final
            self.assertEqual(final['stop_reason'], 'complete')
            self.assertEqual(final['prediction'], ['B_A'])
            self.assertEqual(len(final['prediction_host_citation_matches']), 1)


if __name__ == '__main__':
    unittest.main()
