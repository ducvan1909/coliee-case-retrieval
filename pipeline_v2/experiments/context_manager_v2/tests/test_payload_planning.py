"""Exact memo isolation and source integrity; no approximate admission proof."""
from copy import deepcopy
from tempfile import TemporaryDirectory
from pathlib import Path
import unittest

from pipeline_v2.agent_harness.evidence import SourceDrift
from pipeline_v2.experiments.context_manager_v2.payload_planning import CompileMemo, CompileFrame
from pipeline_v2.experiments.context_manager_v2.tests import test_engine as fixtures


class PayloadPlanningTests(unittest.TestCase):
    def test_exact_result_builds_once_and_does_not_share_mutable_return(self):
        memo = CompileMemo()
        calls = []
        def build():
            calls.append(1)
            return {'rows': [{'text': 'literal'}], 'fits': False}
        first = memo.get_or_build(('same',), build)
        first['rows'][0]['text'] = 'changed'
        second = memo.get_or_build(('same',), build)
        self.assertEqual(second['rows'][0]['text'], 'literal')
        self.assertEqual((len(calls), memo.hits, memo.misses), (1, 1, 1))
        with self.assertRaises(RuntimeError):
            memo.get_or_build(('cycle',), lambda: memo.get_or_build(('cycle',), build))

    def test_common_source_artifacts_reused_but_fresh_boundary_detects_drift(self):
        with TemporaryDirectory() as directory:
            engine, raw = fixtures.EngineTests().make(directory)
            frame = CompileFrame(engine, engine._state())
            engine.store.raw_reader, engine.store.verify = frame.raw, frame.verify
            try:
                record = next(iter(engine._state().catalog.values()))
                self.assertEqual(engine.store.verify(record), record)
                self.assertEqual(engine.store.verify(record), record)
                self.assertEqual((frame.common_builds, frame.source_opens, frame.record_verifications), (1, 1, 1))
                raw['A'] = raw['A'] + b' changed'
                with self.assertRaises(SourceDrift):
                    frame.verify_sources_fresh()
            finally:
                frame.restore(engine.store)

    def test_feedback_cache_retains_working_context_initialization(self):
        with TemporaryDirectory() as directory:
            engine, _ = fixtures.EngineTests().make(directory)
            engine._compile_memo = CompileMemo()
            base = engine.context()
            base.update(stage='missing_evidence', pair_progress={})
            first, second = deepcopy(base), deepcopy(base)
            self.assertEqual(engine._feedback(first), engine._feedback(second))
            self.assertEqual(first, second)
            self.assertTrue(second['pair_progress'])
            self.assertEqual(engine._compile_memo.hits, 1)

    def test_prepare_restores_store_and_builds_one_frame(self):
        with TemporaryDirectory() as directory:
            engine, _ = fixtures.EngineTests().make(directory)
            original_reader, original_verifier = engine.store.raw_reader, engine.store.verify
            before = engine.events()
            first = engine.prepare(admit=False)
            second = engine.prepare(admit=False)
            self.assertEqual(first['payload'], second['payload'])
            self.assertEqual(engine.events(), before)
            self.assertEqual(engine.last_compile_cache['common_frame_builds'], 1)
            self.assertIs(engine.store.raw_reader, original_reader)
            self.assertEqual(engine.store.verify, original_verifier)

    def test_stop_file_blocks_automatic_candidate_page_proposal(self):
        from pipeline_v2.experiments.context_manager_v2.tests import test_passage_review as passages
        from pipeline_v2.experiments.context_manager_v2.cli import choose
        fixture = passages.PassageReviewTests()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            engine, _ = fixture.make_engine(root / 'session', page_size=1)
            engine.identity_check_enabled = True
            fixture.start(engine)
            engine.survey_first = True
            opened, _ = fixture.survey_then_open(engine, 'B_A')
            engine.step({'action': 'conclude_candidate', 'args': fixture.conclusion(opened, 'not_select')})
            engine.deterministic_candidate_paging = True
            (root / 'STOP').write_text('stop', encoding='utf-8')
            preview = engine.prepare(admit=False)
            self.assertEqual(engine.context()['passage_session']['survey_offset'], 0)
            self.assertEqual(preview['payload']['m6']['cm_page']['candidates'][0]['case_id'], 'B_A')
            self.assertFalse(any(e.get('cm_auto_candidate_view') for e in engine.events()))


if __name__ == '__main__':
    unittest.main()
