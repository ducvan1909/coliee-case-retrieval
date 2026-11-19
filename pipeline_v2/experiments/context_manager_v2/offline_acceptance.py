"""Run CM4 to completion with scripted decisions, recorded search, and real source tools."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator

from pipeline_v2.agent_harness.contracts import ModelReply, fingerprint
from pipeline_v2.experiments.context_manager_v1.core import Snapshot, require, write_once
from pipeline_v2.experiments.uncapped_probe.runner import Trace
from .cli import RecordedHybrid, hashes, historical_events, quote_for_paragraph
from .engine import VERSION
from .live import HybridSearch, ModalQwenTransport, run_loop, runtime


class ScriptedController:
    def __init__(self, counter, history, *, exercise_repair=False):
        self.count_tokens = counter
        actions = [row['action'] for row in history if row['kind'] == 'action_started']
        self.query_region = next(row['args'] for row in actions if row['action'] == 'open_query')
        self.need = next(row['args']['_m6_need'] for row in actions if row['action'] == 'search_corpus')
        self.calls = []
        self.search_submitted = False
        self.receipts = []
        self.assessment_pending_exercised = False
        self.exercise_repair = exercise_repair
        self.rejected_turn = None

    def choose(self, payload):
        feedback, view = payload['last_action_feedback'], payload['m6']
        context = view['cm_context']
        navigation = view['cm_page']['controls']
        if not self.search_submitted and context['mode'] == 'query':
            start = self.need['a_paragraph']['span_bytes'][0]
            choices = [(row['description']['byte_length'], key) for key, row in view['query_targets'].items()
                       if row['description']['span_bytes'][0] <= start < row['description']['span_bytes'][1]]
            return 'read_query_passages', {'query_ref': min(choices)[1]}
        if not self.search_submitted:
            paragraph = self.need['a_paragraph']['paragraph_handle']
            ref = next(key for key, row in view['a_paragraphs'].items() if row['paragraph_handle'] == paragraph)
            self.search_submitted = True
            return 'search_cases_by_issue', {'issue': self.need['intent'], 'anchor_quote': quote_for_paragraph(payload, ref),
                                             'source_proposition': self.need['source_proposition']}
        progress = feedback['review_progress']
        if progress['complete_policy_allowed']:
            return 'finish_case_review', {'reason': 'complete_policy'}
        if context['stage'] == 'reading' or progress['pending_pairs']:
            pair = next(key for key, row in view['pair_refs'].items() if row['candidate_id'] == context['candidate_id'])
            args = {'pair_ref': pair, 'case_relation': 'unknown', 'passage_location': 'bounded',
                    'reason': 'Scripted offline check of the assessment path for the displayed evidence.'}
            if self.exercise_repair and self.rejected_turn is None:
                self.rejected_turn = len(self.calls)
                return 'assess_case_link', {**args, 'reason': '   '}
            if self.rejected_turn == len(self.calls) - 1:
                repair = feedback.get('tool_repair', {})
                require(repair.get('tool') == 'assess_case_link' and repair.get('fields') == ['reason'],
                        'Missing corrective feedback for the scripted blank reason')
            if not self.assessment_pending_exercised:
                args['missing_evidence'] = ['Scripted evidence-gap branch of the offline test.']
                self.assessment_pending_exercised = True
            return 'assess_case_link', args
        if context['mode'] != 'results':
            return 'show_context_page', {'page_ref': navigation['results']}
        remaining = set(progress['retrieval_only_examples'])
        candidate = next((card for card in view['cm_page']['candidates']
                          if card['case_id'] in remaining and card['read_allowed']), None)
        if candidate:
            if candidate.get('retrieved_lead_ref'):
                return 'open_retrieved_passage', {'lead_ref': candidate['retrieved_lead_ref']}
            return 'read_case_passages', {'candidate_ref': candidate['candidate_ref'], 'focus': self.need['intent']}
        return 'show_context_page', {'page_ref': navigation['next']}

    def send_structured(self, body, request_id, schema):
        name, args = self.choose(json.loads(body))
        action = {'action': name, 'args': args}
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(action)
        tokens = self.count_tokens(body)
        self.calls.append({'request_id': request_id, 'wire_sha256': sha256(body).hexdigest(),
                           'schema_sha256': fingerprint(schema), 'action': name, 'input_tokens': tokens})
        self.receipts.append({'request_id': request_id, 'submission_attempted': False, 'receipt': 'offline_script'})
        return ModelReply(action)


def acceptance(root, source, output, *, exercise_repair=False):
    require(not output.exists() and not output.is_relative_to(source), 'Use a fresh output outside the source run')
    before = hashes(source)
    plan = json.loads((source / 'plan.json').read_bytes())
    output.mkdir(parents=True)
    trace = Trace(output)
    with patch.object(ModalQwenTransport, 'send_structured', side_effect=AssertionError('No provider in acceptance')), \
            runtime(root, output, plan['settings'], plan['options'], trace) as (engine, tokenizer):
        recorded = RecordedHybrid(source, engine.harness.m3.lexical)
        controller = ScriptedController(tokenizer.count_tokens, historical_events(source),
                                        exercise_repair=exercise_repair)
        journal = engine.harness.hybrid_search.journal
        initial_journal = journal.events()
        with patch.object(HybridSearch, 'search', side_effect=recorded.search):
            run_loop(engine, controller, trace, max_turns=30)

        state = engine.state()
        require(state.final and state.final['stop_reason'] == 'complete', 'Script did not reach policy completion')
        require(not (state.pending_action or state.active_action or state.in_flight), 'Incomplete ledger boundary')
        require(len(state.receipts) == len(controller.calls), 'Missing scripted response')
        repairs = [row for row in state.receipts.values() if row.get('cm_tool_repair')]
        require(len(repairs) == int(exercise_repair), 'Unexpected number of tool repairs')
        if exercise_repair:
            failed, corrected = controller.calls[controller.rejected_turn:controller.rejected_turn + 2]
            require(repairs[0]['request_id'] == failed['request_id'] and repairs[0]['status'] == 'malformed'
                    and repairs[0]['cm_tool_repair']['retry_allowed'] and state.receipts[corrected['request_id']]['status'] == 'success',
                    'Scripted correction did not recover')
            require(state.requests[failed['request_id']]['excerpts'] == state.requests[corrected['request_id']]['excerpts'],
                    'Scripted correction did not preserve current raw')
        require(all(row['status'] == 'success' or row in repairs for row in state.receipts.values()),
                'Unexpected rejected scripted response')
        snapshot = Snapshot.from_events(engine.events(), {})
        retrieved_pairs = {(operation['need_id'], hit['case_id'])
                           for operation in snapshot.operations if operation['status'] == 'success'
                           for hit in operation['hits'] if hit['case_id'] in state.candidates}
        require(retrieved_pairs <= state.active_assessments.keys() and not state.pending_assessments,
                'Incomplete assessment coverage of retrieved need/candidate pairs')
        require(set(state.candidates) <= {case for _, case in state.active_assessments},
                'Incomplete candidate assessment coverage')
        require(recorded.calls == 1 and journal.events() == initial_journal, 'Unexpected retrieval or embedding usage')
        for call in controller.calls:
            admission = state.requests[call['request_id']]
            manifest = engine._manifest(admission)
            require(call['wire_sha256'] == manifest['payload_sha256'] and call['schema_sha256'] == manifest['schema_sha256']
                    and call['input_tokens'] == admission['admitted_input_tokens'] <= 8500, 'Wire, schema or token mismatch')
        report = {'engine_version': VERSION, 'scripted_turns': len(controller.calls),
                  'real_controller_requests': 0, 'real_embedding_requests': 0,
                  'tool_repairs_exercised': len(repairs),
                  'recorded_search_replays': recorded.calls, 'pending_actions_exercised': state.assessment_outcomes['pending_actions'],
                  'candidates': list(state.candidates), 'retrieved_pairs': len(retrieved_pairs),
                  'peak_input_tokens': max(row['input_tokens'] for row in controller.calls),
                  'stop_reason': state.final['stop_reason'], 'selection_status': state.final['selection_status'],
                  'turns': controller.calls}
    require(hashes(source) == before, 'Recorded run changed')
    write_once(output / 'report.json', {**report, 'source_unchanged': True})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--source-run', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--exercise-repair', action='store_true')
    args = parser.parse_args()
    acceptance(args.root.resolve(), args.source_run.resolve(), args.output_dir.resolve(), exercise_repair=args.exercise_repair)


if __name__ == '__main__':
    main()
