"""Compile a new view from a recorded CM4 prefix without calling providers."""
import argparse
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from unittest.mock import patch

from jsonschema import Draft202012Validator
from pipeline_v2.agent_harness.contracts import encode, fingerprint
from pipeline_v2.agent_harness.ledger import Ledger
from pipeline_v2.experiments.context_manager_v1.core import require, write_once
from pipeline_v2.experiments.uncapped_probe.runner import Trace
from .cli import choose, choose_read, hashes
from .live import HybridSearch, LoopGuard, ModalQwenTransport, _prime_guard, runtime


def replay(root, source, output, through, check_action=None, check_side_contract=False,
           check_search_reuse=False, check_archived_pending=False, check_assessed_navigation=False,
           check_speaker_support=False, check_review_completion=False, check_empty_reopen=False,
           check_duplicate_navigation=False):
    require(not output.exists() and not output.is_relative_to(source), 'Use a fresh output outside the source run')
    before = hashes(source)
    plan = json.loads((source / 'plan.json').read_bytes())
    events = Ledger(source / 'session').read()
    prefix = [event for event in events if event['seq'] <= through]
    require(prefix and prefix[-1]['seq'] == through and prefix[-1]['kind'] == 'action_result',
            'Select a committed action-result sequence')
    output.mkdir(parents=True)
    with TemporaryDirectory(dir=output) as scratch, \
            patch.object(ModalQwenTransport, 'send_structured', side_effect=AssertionError('No inference')), \
            patch.object(HybridSearch, 'search', side_effect=AssertionError('No retrieval')):
        stage = Path(scratch) / 'prefix'
        stage.mkdir()
        if check_search_reuse:
            journal_uri = (source / 'embedding_events.sqlite3').as_uri() + '?mode=ro'
            with closing(sqlite3.connect(journal_uri, uri=True)) as original, \
                    closing(sqlite3.connect(stage / 'embedding_events.sqlite3')) as copied:
                original.backup(copied)
        with runtime(root, stage, plan['settings'], plan['options'], Trace(stage)) as (engine, transport):
            initial = engine.events()[0]
            require(initial['initial_result'] == prefix[0]['initial_result'] and initial['full_query'] == prefix[0]['full_query'],
                    'Initial source state differs from recorded prefix')
            for field in ('query_id', 'query_source_hash', 'candidate_fingerprint', 'index_fingerprint', 'tokenizer_fingerprint'):
                require(initial['config']['identity'][field] == prefix[0]['config']['identity'][field], f'Binding drift: {field}')
            with engine.harness.ledger.writer() as db:
                for event in prefix[1:]:
                    Ledger.append(db, event['kind'], **{k: v for k, v in event.items() if k not in ('seq', 'kind')})
            old_events = engine.events()
            counts = []
            original_count = engine.harness._count

            def measure(body):
                count = original_count(body)
                counts.append(count)
                return count

            engine.harness._count = measure
            result = engine.prepare(admit=False)
            require(engine.events() == old_events, 'Preview wrote an event')
            report = {'historical_prefix_through': through, 'historical_prefix_sha256': fingerprint(prefix),
                      'status': result['status'], 'controller_requests': 0, 'embedding_requests': 0,
                      'minimum_tested_input_tokens': min(counts) if counts else None}
            if result['status'] == 'ready':
                body = encode(result['payload'])
                manifest = result['manifest']
                require(sha256(body).hexdigest() == manifest['payload_sha256'], 'Wire hash mismatch')
                require(transport.count_tokens(body) == result['input_tokens'] <= 8500, 'Wire token accounting mismatch')
                report.update(input_tokens=result['input_tokens'], wire_sha256=manifest['payload_sha256'],
                              raw_spans=[{'case_id': row['case_id'], 'span_bytes': row['span_bytes']}
                                         for row in result['payload']['excerpts']],
                              tools=[row['name'] for row in result['payload']['available_tools']])
                write_once(output / 'preview.json', result)
                if check_side_contract:
                    verify_assessment_side_contract(engine, result, events, through, report)
                if check_search_reuse:
                    verify_search_reuse(engine, events, through, report)
                if check_archived_pending:
                    verify_archived_pending(engine, events, through, report)
                if check_assessed_navigation:
                    verify_assessed_navigation(engine, result, events, through, report)
                if check_review_completion:
                    verify_assessed_navigation(engine, result, events, through, report, check_completion=True)
                if check_empty_reopen:
                    verify_empty_reopen(engine, events, through, report, plan['options'])
                if check_duplicate_navigation:
                    verify_duplicate_navigation(engine, events, through, report, plan['options'])
                if check_speaker_support:
                    verify_speaker_support(engine, result, events, through, report)
                if check_action:
                    admitted = engine.prepare()
                    values = {'case_relation': 'unknown', 'passage_location': 'bounded',
                              'reason': 'Scripted dispatch test using current source refs.'} if check_action == 'assess_case_link' else {}
                    engine.reply(admitted['request_id'], choose(admitted, check_action, **values))
                    require(engine.state().pending_action is not None, 'Scripted reply was rejected')
                    engine.execute_pending()
                    outcome = engine.events()[-1]
                    require(outcome['kind'] == 'action_result' and outcome['status'] == 'success', 'Scripted dispatch failed')
                    report.update(scripted_action=check_action, scripted_action_status=outcome['status'])
    require(hashes(source) == before, 'Recorded run changed')
    report['source_unchanged'] = True
    write_once(output / 'report.json', report)
    return report


def verify_assessment_side_contract(engine, preview, events, through, report):
    """Check the archived mixed-side failure and one valid model alternative."""
    later = [row for row in events if row['seq'] > through]
    old_request = next(row for row in later if row['kind'] == 'request_admitted')
    old_receipt = next(row for row in later if row['kind'] == 'request_result')
    old_result = next(row for row in later if row['kind'] == 'action_result')
    require(old_request['request_id'] == old_receipt['request_id'] and
            old_result.get('reason') == 'assessment_state:container_refs_belongs_to_another_case',
            'Expected the recorded mixed-side assessment failure')
    invalid = json.loads(old_receipt['raw_model_reply'])
    require(invalid['action'] == 'assess_case_link' and 'speaker' not in invalid['args'],
            'Expected an assessment with omitted speaker')
    payload = preview['payload']
    require(set(invalid['args']['container_refs']) == set(payload['current_payload_source_refs']),
            'Current refs differ from the archived mixed-side refs')
    require(invalid['args']['pair_ref'] in payload['m6']['pair_refs'], 'Current pair differs from the archived pair')
    validator = Draft202012Validator(preview['manifest']['schema'])
    require(not validator.is_valid(invalid), 'New schema still allows the archived mixed-side response')
    # Simulate a new, valid model output in a separate scratch ledger. Live code
    # does not modify or resubmit rejected responses.
    alternative = json.loads(old_receipt['raw_model_reply'])
    a_ref = next(row['ref'] for row in payload['excerpts'] if row['case_id'] == payload['query_id'])
    alternative['args']['container_refs'].remove(a_ref)
    require(validator.is_valid(alternative), 'A same-side alternative should pass the schema')
    admitted = engine.prepare()
    engine.reply(admitted['request_id'], alternative)
    require(engine.state().pending_action is not None, 'Host rejected the same-side alternative')
    engine.execute_pending()
    outcome = engine.events()[-1]
    require(outcome['kind'] == 'action_result' and outcome['status'] == 'pending_evidence',
            'Same-side assessment should retain the model-reported evidence gap')
    report.update(archived_mixed_side_action_rejected_by_schema=True,
                  scripted_same_side_assessment=outcome['status'])


def verify_search_reuse(engine, events, through, report):
    """Submit the recorded second search to the local host with retrieval disabled."""
    later = [row for row in events if row['seq'] > through]
    receipt = next(row for row in later if row['kind'] == 'request_result')
    response = json.loads(receipt['raw_model_reply'])
    require(response['action'] == 'search_cases_by_issue', 'Expected a recorded issue search')
    first_action = next(row for row in events if row['kind'] == 'action_started'
                        and row['action']['action'] == 'search_corpus')
    first_result = next(row for row in events if row['kind'] == 'action_result'
                        and row['action_id'] == first_action['action_id'])
    admitted = engine.prepare()
    engine.reply(admitted['request_id'], response)
    require(engine.state().pending_action is not None, 'Recorded issue search was rejected')
    journal = engine.harness.hybrid_search.journal
    before = journal.events()
    engine.execute_pending()
    require(journal.events() == before, 'Reusing a result added an embedding or retrieval receipt')
    started, outcome = engine.events()[-2:]
    require(started['kind'] == 'action_started' and not started['executes_tool']
            and outcome['kind'] == 'action_result' and outcome['status'] == 'success',
            'Expected a successful search result without a tool call')
    old = first_result['result']['observation']
    new = outcome['result']['observation']
    require(new['hits'] == old['hits'], 'Reused ranking differs from recorded hits')
    require(new['search_reuse']['source_action_id'] == first_action['action_id'], 'Original search binding was lost')
    require(new['m6_source_need']['source_need_id'] != old['m6_source_need']['source_need_id'],
            'Search reuse merged source needs')
    next_view = engine.prepare(admit=False)
    require(next_view['status'] == 'ready' and next_view['payload']['m6']['cm_context']['stage'] == 'results_ready',
            'Reused search did not route to results')
    report.update(reused_prior_search_without_tool=True,
                  original_search_action=first_action['action_id'],
                  original_need=old['m6_source_need']['source_need_id'],
                  current_need=new['m6_source_need']['source_need_id'],
                  reused_case_ids=[row['case_id'] for row in new['hits']],
                  results_view_tokens=next_view['input_tokens'])


def verify_archived_pending(engine, events, through, report):
    """Replay the exact model action interrupted by the pending-feedback crash."""
    receipt = next(row for row in events if row['seq'] > through and row['kind'] == 'request_result')
    response = json.loads(receipt['raw_model_reply'])
    require(response['action'] == 'assess_case_link' and not {'missing_evidence', 'speaker_evidence_refs'} & response['args'].keys(),
            'Expected the recorded assessment with omitted evidence and note')
    admitted = engine.prepare()
    engine.reply(admitted['request_id'], response)
    require(engine.state().pending_action is not None, 'Recorded assessment was rejected')
    engine.execute_pending()
    outcome = engine.events()[-1]
    require(outcome['kind'] == 'action_result' and outcome['status'] == 'pending_evidence', 'Expected a committed pending assessment')
    rows = outcome['pending_assessments']
    require(len(rows) == 1 and rows[0]['reported_missing_evidence'] is None
            and rows[0]['missing_evidence'] == ['speaker_evidence_refs'], 'Pending assessment differs from validator result')
    followup = engine.prepare(admit=False)
    require(followup['status'] == 'ready', 'Follow-up payload did not fit')
    feedback = followup['payload']['last_action_feedback']
    require(feedback['reported_missing_evidence'] == [] and feedback['validation_missing_codes'] == ['speaker_evidence_refs'],
            'Follow-up feedback lost the validator reason')
    report.update(archived_assessment_status=outcome['status'], followup_input_tokens=followup['input_tokens'],
                  validation_missing_codes=feedback['validation_missing_codes'])


def verify_assessed_navigation(engine, preview, events, through, report, *, check_completion=False):
    """Reject the archived action and check that another candidate is reachable."""
    receipt = next(row for row in events if row['seq'] > through and row['kind'] == 'request_result')
    repeated = json.loads(receipt['raw_model_reply'])
    if check_completion:
        require(repeated == {'action': 'finish_case_review', 'args': {'reason': 'complete_policy'}},
                'Expected a recorded completion')
    else:
        require(repeated['action'] == 'assess_case_link', 'Expected a recorded repeated assessment')
    feedback = preview['payload']['last_action_feedback']
    require(feedback.get('active_assessment') and feedback.get('guidance'), 'Missing assessed feedback')
    old_request = next(row for row in events if row['seq'] > through and row['kind'] == 'request_admitted')
    require(set(preview['payload']['current_payload_source_refs']) == set(old_request['current_payload_source_refs']),
            'New preview differs from the raw refs in the repeated assessment')
    validator = Draft202012Validator(preview['manifest']['schema'])
    require(not validator.is_valid(repeated), 'Archived action remains allowed')
    if check_completion:
        require(not validator.is_valid({'action': 'finish_case_review', 'args': {'reason': 'no_progress'}}),
                'Controller no_progress stop remains available')
        report['review_progress'] = feedback['review_progress']
    results = next(option for option in feedback['navigation_options'] if option['view'] == 'results')
    engine.step({'action': results['tool'], 'args': results['args']})
    preview = engine.prepare(admit=False)
    cards = preview['payload']['m6']['cm_page']['candidates']
    current = engine.context()['candidate_id']
    candidate = next(card for card in cards if card['read_allowed'] and card['case_id'] != current)
    engine.step(choose_read(preview, candidate, 'leave to file reply affidavit'))
    require(engine.context()['candidate_id'] == candidate['case_id'] and engine.events()[-1]['status'] == 'success',
            'Navigating to a different candidate failed')
    key = 'archived_completion_rejected_by_schema' if check_completion else 'archived_repeat_rejected_by_schema'
    report.update({key: True, 'edited_navigation_candidate': candidate['case_id']})


def verify_empty_reopen(engine, events, through, report, options):
    """Replay the duplicate search and empty reopen, then read an unread candidate."""
    later = [row for row in events if row['seq'] > through]
    receipts = [row for row in later if row['kind'] == 'request_result']
    outcomes = [row for row in later if row['kind'] == 'action_result']
    duplicate, reopen, stop = [json.loads(row['raw_model_reply']) for row in receipts[:3]]
    require((duplicate['action'], reopen['action'], stop['action']) ==
            ('search_cases_by_issue', 'read_case_passages', 'finish_case_review')
            and stop['args']['reason'] == 'no_progress', 'Expected the recorded duplicate/reopen/stop path')
    require(outcomes[0]['status'] == 'duplicate' and outcomes[1]['cm_context']['stage'] == 'reading'
            and not (outcomes[1]['result'] or {}).get('excerpts'), 'Expected the original empty reopen')

    before = engine.state()
    context = engine.context()
    case = context['candidate_id']
    active_id = before.active_assessments[(context['need_id'], case)]
    engine.step(duplicate)
    require(engine.events()[-1]['status'] == 'duplicate', 'Repeated search ran instead of being skipped')
    engine.step(reopen)
    retained = engine.context()
    require(retained['stage'] == 'assessed' and retained['mode'] == 'results' and retained['candidate_id'] == case
            and retained['need_id'] == context['need_id'], 'Empty reopen lost the assessed state')
    outcome = engine.events()[-1]
    require(outcome['reason'] == 'reopened_without_new_raw' and not (outcome['result'] or {}).get('excerpts')
            and engine.state().active_assessments[(context['need_id'], case)] == active_id, 'Incorrect empty-reopen outcome')
    guard = LoopGuard(options['no_progress_limit'], options['cycle_limit'])
    guard_outcome = _prime_guard(engine, guard)
    require(not guard_outcome['stop'], 'Progress guard stopped before the controller could read an unread result')
    preview = engine.prepare(admit=False)
    feedback = preview['payload']['last_action_feedback']
    require(feedback['active_assessment']['assessment_id'] == active_id
            and not feedback['review_progress']['complete_policy_allowed'], 'Incorrect review progress')
    reviewed = {candidate for _, candidate in [*before.active_assessments, *before.pending_assessments]}
    card = next(row for row in preview['payload']['m6']['cm_page']['candidates']
                if row['read_allowed'] and row['case_id'] not in reviewed)
    engine.step(choose_read(preview, card, reopen['args']['focus']))
    alternative = engine.prepare(admit=False)
    require(engine.context()['candidate_id'] == card['case_id']
            and any(row['case_id'] == card['case_id'] for row in alternative['payload']['excerpts']),
            'Unread result did not deliver raw text')
    require(not guard.observe(engine.state(), engine.context())['stop'], 'Progress guard stopped despite new candidate raw')
    report.update(archived_model_stop=stop['args']['reason'], reopened_case=case, reopened_stage='assessed',
                  active_assessment_retained=True, unread_at_reopen=feedback['review_progress']['retrieval_only_candidates'],
                  next_read_case=card['case_id'], guard_after_reopen=guard_outcome, reopened_input_tokens=preview['input_tokens'],
                  next_read_input_tokens=alternative['input_tokens'])


def verify_duplicate_navigation(engine, events, through, report, options):
    later = [row for row in events if row['seq'] > through]
    receipts = [row for row in later if row['kind'] == 'request_result']
    duplicate, repeated = [json.loads(row['raw_model_reply']) for row in receipts[:2]]
    require(duplicate == repeated and duplicate['action'] == 'search_cases_by_issue',
            'Expected two recorded copies of an issue search')
    engine.step(duplicate)
    current = engine.context()
    require(engine.events()[-1]['status'] == 'duplicate' and current['mode'] == 'results',
            'Duplicate did not bring back the existing results')
    guard = LoopGuard(options['no_progress_limit'], options['cycle_limit'])
    guard_outcome = _prime_guard(engine, guard)
    require(not guard_outcome['stop'], 'Guard stopped before the alternative could be selected')
    preview = engine.prepare(admit=False)
    require(not Draft202012Validator(preview['manifest']['schema']).is_valid(repeated),
            'A second duplicate was still offered')
    state = engine.state()
    card = next(item for item in preview['payload']['m6']['cm_page']['candidates']
                if item['read_allowed'] and (current['need_id'], item['case_id']) not in state.active_assessments
                and (current['need_id'], item['case_id']) not in state.pending_assessments)
    engine.step(choose_read(preview, card, duplicate['args']['issue']))
    followup = engine.prepare(admit=False)
    require(any(row['case_id'] == card['case_id'] for row in followup['payload']['excerpts']),
            'Alternative did not deliver candidate raw')
    report.update(repeated_search_rejected=True, next_read_case=card['case_id'],
                  guard_after_duplicate=guard_outcome, recovery_input_tokens=preview['input_tokens'],
                  next_read_input_tokens=followup['input_tokens'])


def verify_speaker_support(engine, preview, events, through, report):
    receipt = next(row for row in events if row['seq'] > through and row['kind'] == 'request_result')
    response = json.loads(receipt['raw_model_reply'])
    args = response['args']
    require(response['action'] == 'assess_case_link' and args['speaker']['side'] == 'A'
            and 'speaker_evidence_refs' not in args, 'Expected the archived unsupported speaker claim')
    payload = preview['payload']
    require(args['pair_ref'] in payload['m6']['pair_refs'], 'Pair binding differs from the archived action')
    validator = Draft202012Validator(preview['manifest']['schema'])
    require(not validator.is_valid(response), 'Known speaker without support still passes the schema')
    a_ref, = (row['ref'] for row in payload['excerpts'] if row['case_id'] == payload['query_id'])
    args['speaker_evidence_refs'] = [a_ref]
    args['speaker']['side'] = 'query case'
    require(validator.is_valid(response), 'Scripted correction with the current query case ref was rejected')
    admitted = engine.prepare()
    engine.reply(admitted['request_id'], response)
    require(engine.state().pending_action is not None, 'Host rejected scripted correction')
    engine.execute_pending()
    outcome = engine.events()[-1]
    require(outcome['kind'] == 'action_result' and outcome['status'] == 'success'
            and len(outcome['assessments']) == 1, 'Expected structural acceptance of the scripted correction')
    require(outcome['assessments'][0]['attribution_status'] == 'model_inferred', 'Attribution status changed')
    report.update(archived_unsupported_speaker_rejected_by_schema=True,
                  scripted_assessment_status=outcome['assessments'][0]['status'], speaker_ref=a_ref)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--source-run', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--through', type=int, required=True)
    checks = parser.add_mutually_exclusive_group()
    checks.add_argument('--check-action', choices=('assess_case_link', 'read_more_context'))
    checks.add_argument('--check-side-contract', action='store_true')
    checks.add_argument('--check-search-reuse', action='store_true')
    checks.add_argument('--check-archived-pending', action='store_true')
    checks.add_argument('--check-assessed-navigation', action='store_true')
    checks.add_argument('--check-speaker-support', action='store_true')
    checks.add_argument('--check-review-completion', action='store_true')
    checks.add_argument('--check-empty-reopen', action='store_true')
    checks.add_argument('--check-duplicate-navigation', action='store_true')
    args = parser.parse_args()
    report = replay(args.root.resolve(), args.source_run.resolve(), args.output_dir.resolve(), args.through,
                    args.check_action, args.check_side_contract, args.check_search_reuse, args.check_archived_pending,
                    args.check_assessed_navigation, args.check_speaker_support, args.check_review_completion,
                    args.check_empty_reopen, args.check_duplicate_navigation)
    print(json.dumps(report))
    if report['status'] != 'ready':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
