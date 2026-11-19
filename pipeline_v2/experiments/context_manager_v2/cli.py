"""Real-tokenizer, local-source replay. No model or embedding execution."""
import argparse
from contextlib import ExitStack, closing
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from time import perf_counter
from unittest.mock import patch

from pipeline_v2.agent_harness.contracts import fingerprint
from pipeline_v2.agent_harness.ledger import Ledger
from pipeline_v2.agent_harness.modal_qwen import ModalQwenTransport
from pipeline_v2.experiments.context_manager_v1.core import require, write_once
from pipeline_v2.full_search.source_tools import SourceToolsSession
from pipeline_v2.sparse_bm25.index import SparseSession
from pipeline_v2.query_navigation import HierarchicalM3Tools, QueryNavigationConfig
from pipeline_v2.m6 import AdaptiveConfig
from pipeline_v2.m6_hybrid import HybridSearch
from pipeline_v2.retrieval_diagnostics import verify_capture
from .engine import Engine
from .live import INSTRUCTIONS


def hashes(directory):
    return {str(p.relative_to(directory)): sha256(p.read_bytes()).hexdigest()
            for p in directory.rglob('*') if p.is_file()}


def historical_events(directory):
    session = directory / 'session'
    return Ledger(session if (session / 'events.sqlite3').exists() else directory).read()


class RecordedHybrid:
    def __init__(self, source, lexical):
        with closing(sqlite3.connect((source / 'embedding_events.sqlite3').as_uri() + '?mode=ro', uri=True)) as db:
            events = [json.loads(r[0]) for r in db.execute('SELECT body FROM events ORDER BY id')]
        admission = next(r for r in events if r['kind'] == 'search_admitted')
        receipt = next(r for r in events if r['kind'] == 'search_returned' and r['operation'] == admission['operation'])
        self.capture = verify_capture(source, receipt, admission)
        b = self.capture['bindings']
        require(b['full_manifest_sha256'] == lexical.binding['manifest.json'] and
                b['sparse_manifest_sha256'] == lexical.index_binding['manifest.json'], 'Recorded search index drift')
        actions = [r for r in historical_events(source) if r['kind'] == 'action_started']
        action = next(r for r in actions if r['action_id'] == self.capture['action_id'])['action']
        require(action['action'] == 'search_corpus' and action['args']['text'] == self.capture['query']
                and action['args']['limit'] == self.capture['limit'], 'Capture not linked to controller action')
        self.fingerprint = fingerprint(self.capture)
        self.calls = 0

    def search(self, query, query_case, limit, action_id):
        require((query, query_case, limit) == (self.capture['query'], self.capture['query_case'], self.capture['limit']),
                'Offline replay only permits exactly captured retrieval')
        self.calls += 1
        result = deepcopy(self.capture['result'])
        result['execution_mode'] = 'recorded_replay_no_new_retrieval'
        result['model_requests'] = 0
        result['timings'] = {'historical_timings_excluded': True}
        return result

    def usage(self):
        return {'requests': 0, 'input_tokens': 0, 'recorded_search_replays': self.calls}

    def remaining(self):
        return {'requests': 1, 'input_tokens': 2**60}


def branch(prepared, name):
    return next(b['properties']['args']['properties'] for b in prepared['manifest']['schema']['anyOf']
                if b['properties']['action']['const'] == name)


def quote_for_paragraph(payload, paragraph_ref=None):
    """Build an exact quote from a known paragraph for a scripted offline action."""
    paragraphs = payload['m6']['a_paragraphs']
    ref = paragraph_ref if paragraph_ref is not None else next(iter(paragraphs))
    paragraph = paragraphs[ref]
    source = next(row for row in payload['excerpts'] if row['ref'] == paragraph['source_ref'])
    left, right = paragraph['span_bytes']
    start = source['span_bytes'][0]
    text = source['text'].encode('utf-8')[left - start:right - start].decode('utf-8').strip()
    return text[:200].rstrip()


def choose(prepared, name, **values):
    row = next(row for row in prepared['manifest']['schema']['anyOf'] if row['properties']['action']['const'] == name)
    params = row['properties']['args']
    fields = params['properties']
    if name == 'search_cases_by_issue' and 'anchor_quote' not in values:
        values['anchor_quote'] = quote_for_paragraph(prepared['payload'], values.pop('a_paragraph_ref', None))
    args = {k: values[k] if k in values else v['enum'][0] for k, v in fields.items()
            if k in values or (k in params['required'] and 'enum' in v)}
    return {'action': name, 'args': args}


def choose_read(prepared, card, focus):
    if card.get('retrieved_lead_ref'):
        return choose(prepared, 'open_retrieved_passage', lead_ref=card['retrieved_lead_ref'])
    return choose(prepared, 'read_case_passages', candidate_ref=card['candidate_ref'], focus=focus)


def replay(root, source, output):
    root, source, output = root.resolve(), source.resolve(), output.resolve()
    require(not output.exists() and not output.is_relative_to(source), 'Fresh output outside source required')
    before = hashes(source)
    start = perf_counter()
    output.mkdir(parents=True)
    plan = json.loads((source / 'plan.json').read_bytes())
    history = historical_events(source)
    cfg = plan['settings']
    transcript = []
    with ExitStack() as stack:
        stack.enter_context(patch.object(ModalQwenTransport, 'send_structured', side_effect=AssertionError('Inference forbidden')))
        stack.enter_context(patch.object(HybridSearch, 'search', side_effect=AssertionError('Live retrieval forbidden')))
        transport = ModalQwenTransport(root / cfg['tokenizer_dir'], instructions=INSTRUCTIONS)
        lexical = SparseSession(root)
        stack.callback(lexical.close)
        sources = SourceToolsSession(root, snapshot=lexical)
        stack.callback(sources.close)
        tools = HierarchicalM3Tools(sources, lexical, cfg['query_id'], byte_budget=cfg['byte_budget'],
                    map_limit=cfg['map_limit'], navigation_config=QueryNavigationConfig(**cfg['query_navigation']),
                    count_tokens=transport.count_tokens, output_token_cap=512)
        initial, whole = tools.query_start()
        recorded = RecordedHybrid(source, lexical)
        from pipeline_v2.agent_harness.contracts import RunIdentity
        historical_identity = next(e['config']['identity'] for e in history if e['kind'] == 'run_created')
        identity = RunIdentity(**{**historical_identity, 'run_id': output.name,
            'profile_fingerprint': fingerprint(['CM2-CM3', cfg]), 'tools_fingerprint': tools.fingerprint,
            'prompt_fingerprint': transport.prompt_fingerprint})
        require(identity.query_source_hash == whole.source_hash and identity.tokenizer_fingerprint == transport.tokenizer_fingerprint,
                'Source/tokenizer drift')
        kwargs = dict(identity=identity, tools=tools, count_tokens=transport.count_tokens,
            raw_reader=lambda case: (root / 'data/task1_train_files_2026/cases' / case).read_bytes(),
            config=AdaptiveConfig(**cfg['adaptive_config']), initial_observation=initial, query_excerpt=whole,
            hybrid_search=recorded, counter_binding=fingerprint([transport.tokenizer_fingerprint, transport.prompt_fingerprint]))
        engine = Engine(output / 'session', **kwargs)

        def step(label, select):
            print(json.dumps({'stage': label, 'status': 'started', 'inference_requests': 0}), flush=True)
            p = engine.step(select)
            transcript.append({'label': label, 'input_tokens': p['input_tokens'],
                'request_id': p['request_id'], 'coverage': p['manifest']['coverage'],
                'context_after': engine.context(), 'active_assessments': len(engine.state().active_assessments),
                'pending_assessments': len(engine.state().pending_assessments),
                'last_action_feedback': p['payload'].get('last_action_feedback'),
                'candidate_page': p['payload']['m6']['cm_page']})
            print(json.dumps({'stage': label, 'status': 'finished', 'input_tokens': p['input_tokens']}), flush=True)
            return p

        historical_query = next(r['action']['args'] for r in history
                                if r['kind'] == 'action_started' and r['action']['action'] == 'open_query')
        def read_query(p):
            manifest = p['manifest']
            targets = manifest['dispatch_m6']['query_targets']
            aliases = manifest['wire_aliases']
            ref = next(ref for ref in p['payload']['m6']['query_targets']
                       if targets[aliases.get(ref, ref)]['binding'] == historical_query)
            return choose(p, 'read_query_passages', query_ref=ref)
        step('read_query', read_query)
        saved_search = next(r for r in history if r['kind'] == 'request_result'
                            and r.get('action', {}).get('action') == 'search_corpus')
        if saved_search.get('m6_reply'):
            search_reply = json.loads(saved_search['m6_reply']['raw_action'])
        else:
            require(saved_search.get('raw_model_reply_encoding', 'native') == 'native', 'Cannot replay malformed raw output')
            search_reply = saved_search['raw_model_reply']
            search_reply = json.loads(search_reply) if isinstance(search_reply, str) else deepcopy(search_reply)
        paragraph_handle = saved_search['action']['args']['_m6_need']['a_paragraph']['paragraph_handle']
        def replay_search(p):
            reply = deepcopy(search_reply)
            ref = next(k for k, v in p['payload']['m6']['a_paragraphs'].items()
                if v['paragraph_handle'] == paragraph_handle)
            reply['args'].pop('a_paragraph_ref', None)
            reply['args']['anchor_quote'] = quote_for_paragraph(p['payload'], ref)
            return reply
        step('recorded_search', replay_search)
        case_ids = [h['case_id'] for h in recorded.capture['result']['hits']]

        def read(case):
            def select(p):
                card = next(row for row in p['payload']['m6']['cm_page']['candidates'] if row['case_id'] == case)
                return choose_read(p, card, recorded.capture['query'])
            return select

        def read_step(label, case):
            # Fitting can shrink a page below the configured five cards. Script
            # real page navigation instead of assuming every hit is visible.
            for page_index in range(len(case_ids) + 1):
                preview = engine.prepare(admit=False)
                require(preview['status'] == 'ready', 'Candidate navigation context unfit')
                if any(row['case_id'] == case for row in preview['payload']['m6']['candidates'].values()):
                    return step(label, read(case))
                require(preview['payload']['m6']['cm_page']['controls'].get('next'), 'Candidate absent from remaining pages')
                step(label + '_page_' + str(page_index + 1), lambda p: choose(p, 'show_context_page',
                    page_ref=p['payload']['m6']['cm_page']['controls']['next']))
            raise AssertionError('Candidate paging did not terminate')

        read_step('read_B', case_ids[0])
        step('assess_B_unknown', lambda p: choose(p, 'assess_case_link', case_relation='unknown',
            passage_location='bounded', reason='Offline scripted validation only; legal relationship remains unverified.'))
        assessed = deepcopy(engine.state().active_assessments)
        def page(mode):
            return lambda p: choose(p, 'show_context_page', page_ref=p['payload']['m6']['cm_page']['controls'][mode])
        step('pool', page('pool'))
        read_step('read_C', case_ids[1])
        step('missing_C', lambda p: choose(p, 'record_missing_evidence', reason='Scripted boundary: inspect additional legal attribution before assessment.'))
        require(engine.state().active_assessments == assessed, 'Parking invalidated assessment')
        step('parked_pairs', page('parked'))
        def return_b(p):
            ref = next(k for k, v in p['manifest']['handles'].items()
                       if v['kind'] == 'resume' and v['candidate_id'] == case_ids[0])
            return choose(p, 'resume_pair_evidence', evidence_ref=ref)
        for page_index in range(len(case_ids) + 1):
            preview = engine.prepare(admit=False)
            require(preview['status'] == 'ready', 'Parked navigation context unfit')
            if any(v['kind'] == 'resume' and v['candidate_id'] == case_ids[0]
                   for v in preview['manifest']['handles'].values()):
                break
            require(preview['payload']['m6']['cm_page']['controls'].get('next'), 'Parked pair absent from remaining pages')
            step('return_B_page_' + str(page_index + 1), lambda p: choose(p, 'show_context_page',
                page_ref=p['payload']['m6']['cm_page']['controls']['next']))
        else:
            raise AssertionError('Parked paging did not terminate')
        step('return_B', return_b)
        p = engine.prepare()
        require(p['status'] == 'ready', 'Reload payload unfit')
        require({r['case_id'] for r in p['payload']['excerpts']} == {identity.query_id, case_ids[0]}, 'Reload pair mismatch')
        engine.reply(p['request_id'], choose(p, 'finish_case_review', reason='failure'))
        engine.execute_pending()
        original = engine.inspect()
        reopened = Engine(output / 'session', **kwargs)
        require(original == reopened.inspect(), 'Resume mismatch')
        executed = [e['action']['action'] for e in engine.events() if e['kind'] == 'action_started']
        report = {'milestones': ['CM2', 'CM3'], 'status': 'PASS', 'controller_inference_requests': 0,
            'embedding_requests': 0, 'new_corpus_retrieval_requests': 0, 'recorded_search_replays': recorded.calls,
            'receipts': 'scripted_offline_not_provider', 'scripted_turns': engine.state().usage()['requests'],
            'peak_input_tokens': max([r['input_tokens'] for r in transcript] + [p['input_tokens']]),
            'transcript': transcript, 'final_reload_coverage': p['manifest']['coverage'],
            'assessment_count_before_park': len(assessed), 'park_preserves_assessment': True,
            'resume_equal': True, 'captured_operation': recorded.capture['operation'],
            'executed_action_counts': {name: executed.count(name) for name in sorted(set(executed))},
            'local_source_work': 'Real query navigation/source reads; counts are controller actions, not underlying I/O or within-case search counts.',
            'source_hashes': before, 'source_unchanged': before == hashes(source),
            'code_binding': {str(p.relative_to(Path(__file__).parent)): sha256(p.read_bytes()).hexdigest()
                             for p in Path(__file__).parent.rglob('*.py')},
            'elapsed_seconds': perf_counter() - start,
            'limitations': ['Scripted choices do not validate model decisions or legal quality.',
                            'No live inference, CM4, or 8500-token provider canary.']}
        require(report['source_unchanged'], 'Historical run changed')
        write_once(output / 'report.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--source-run', type=Path, default=Path('cache/m6-uncapped-021095-20261114-200422096'))
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    report = replay(args.root, args.source_run, args.output_dir)
    print(json.dumps({'status': report['status'], 'report': str(args.output_dir / 'report.json'),
                      'inference_requests': 0, 'peak_input_tokens': report['peak_input_tokens']}))


if __name__ == '__main__':
    main()
