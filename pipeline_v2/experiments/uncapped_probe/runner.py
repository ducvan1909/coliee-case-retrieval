"""Disposable, AG-supervised single-query M6 experiment. Never imported by production."""

import argparse
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from threading import Event, Lock, Thread
from time import perf_counter, time_ns

from pipeline_v2.agent_harness import Budget, RunIdentity
from pipeline_v2.agent_harness.contracts import HarnessError, encode, fingerprint
from pipeline_v2.agent_harness.harness import AgentHarness
from pipeline_v2.agent_harness.ledger import Ledger, RunState
from pipeline_v2.m6 import AdaptiveConfig
from pipeline_v2.m6_live import _load, _settings
from .policy import AdaptiveHarness, INSTRUCTIONS

VERSION = 'experimental-supervised-m6-rt4-rt5-compact-registry-v2'
# Production contracts accept finite integers. This is an explicit sentinel,
# not mathematical infinity: 1,152,921,504,606,846,976 requests/actions/tokens.
PRACTICAL_UNBOUNDED = 2 ** 60
HEARTBEAT_SECONDS = 10
SOURCE_FILES = (
    'pipeline_v2/experiments/uncapped_probe/runner.py',
    'pipeline_v2/experiments/uncapped_probe/policy.py',
    'pipeline_v2/experiments/uncapped_probe/replay_payload.py',
    'pipeline_v2/m6.py', 'pipeline_v2/m6_live.py', 'pipeline_v2/m6_hybrid.py',
    'pipeline_v2/m4.py', 'pipeline_v2/query_navigation.py',
    'pipeline_v2/retrieval_diagnostics.py',
    'pipeline_v2/agent_harness/adaptive_policy.py',
    'pipeline_v2/agent_harness/harness.py', 'pipeline_v2/agent_harness/ledger.py',
    'pipeline_v2/agent_harness/contracts.py', 'pipeline_v2/agent_harness/evidence.py',
    'pipeline_v2/agent_harness/schema.py', 'pipeline_v2/agent_harness/assessment.py',
    'pipeline_v2/agent_harness/modal_qwen.py',
    'pipeline_v2/deployments/modal_qwen36_27b/app.py',
)


def settings(value):
    """One query; keep per-request caps while removing practical cumulative caps."""
    value = json.loads(encode(value))
    mode = value.pop('experiment_mode', 'uncapped')
    if mode not in ('uncapped', 'rt5'):
        raise HarnessError('Expected experiment_mode uncapped or rt5')
    if value.get('query_id') != '021095.txt':
        raise HarnessError('This first probe is restricted to discovery query 021095.txt')
    if set(value) != {'query_id', 'tokenizer_dir', 'byte_budget', 'map_limit',
                      'query_navigation', 'adaptive_config', 'budget', 'embedding_budget'}:
        raise HarnessError('Use the explicit isolated experiment settings')
    if value['adaptive_config'].get('channel') != 'hybrid':
        raise HarnessError('This experiment requires real-query hybrid retrieval')
    if mode == 'uncapped':
        value['adaptive_config']['no_progress_actions'] = PRACTICAL_UNBOUNDED
        value['budget'].update(max_requests=PRACTICAL_UNBOUNDED,
                               max_actions=PRACTICAL_UNBOUNDED,
                               max_input_tokens=PRACTICAL_UNBOUNDED,
                               max_total_tokens=None, max_retries=0)
        value['embedding_budget'] = {'max_requests': PRACTICAL_UNBOUNDED,
                                     'max_input_tokens': PRACTICAL_UNBOUNDED}
    else:
        value['adaptive_config']['no_progress_actions'] = 4
        value['budget'].update(max_requests=8, max_actions=8, max_input_tokens=68000,
                               max_total_tokens=72096, max_retries=0)
        value['embedding_budget'] = {'max_requests': 5, 'max_input_tokens': 2240}
    if value['budget']['max_payload_tokens'] != 8500 or value['budget']['max_output_tokens'] != 512:
        raise HarnessError('Keep the RT4 per-request caps at 8500 input / 512 output')
    if value['adaptive_config']['max_reviews'] != 0 or value['adaptive_config']['audit_untriggered'] != 0:
        raise HarnessError('Keep targeted review disabled for this retrieval probe')
    return {**_settings(value), 'experiment_mode': mode}


def code_binding(root):
    return {name: sha256((root / name).read_bytes()).hexdigest() for name in SOURCE_FILES}


class Trace:
    """Live stage observations, not estimates of hidden model/server progress."""
    def __init__(self, run_dir):
        self.run_dir = Path(run_dir)
        self.path = self.run_dir / 'trace.jsonl'
        self.started = perf_counter()
        self.lock = Lock()
        self.phase = 'startup'
        self.call_id = None
        self.stop_seen = False

    def emit(self, event_name, **fields):
        row = {'at_utc': datetime.now(timezone.utc).isoformat(),
               'elapsed_seconds': round(perf_counter() - self.started, 3),
               'event': event_name, **fields}
        with self.lock:
            self.run_dir.mkdir(parents=True, exist_ok=True)
            with self.path.open('ab') as stream:
                stream.write(encode(row) + b'\n')
                stream.flush()
            print(json.dumps(row, ensure_ascii=False), flush=True)

    @contextmanager
    def stage(self, name, *, call_id=None, **fields):
        previous = self.phase
        self.phase = name
        self.emit('stage_started', stage=name, **fields)
        done = Event()
        started = perf_counter()

        def beat():
            while not done.wait(HEARTBEAT_SECONDS):
                stop = (self.run_dir / 'STOP').is_file()
                self.emit('heartbeat', stage=name,
                          stage_elapsed_seconds=round(perf_counter() - started, 3),
                          call_id=call_id() if call_id else None,
                          stop_requested=stop,
                          progress='waiting; remote internal progress unknown')

        thread = Thread(target=beat, daemon=True)
        thread.start()
        try:
            yield
        except BaseException as exc:
            self.emit('stage_error', stage=name, error_type=type(exc).__name__,
                      call_id=call_id() if call_id else None,
                      stage_elapsed_seconds=round(perf_counter() - started, 3))
            raise
        else:
            self.emit('stage_finished', stage=name,
                      stage_elapsed_seconds=round(perf_counter() - started, 3))
        finally:
            done.set()
            thread.join()
            self.phase = previous


def observation_summary(result):
    if not isinstance(result, dict):
        return None
    obs = result.get('observation') or {}
    return {'candidate_ids': result.get('candidates', []),
            'raw_spans': [{key: row.get(key) for key in
                           ('ref', 'case_id', 'source_hash', 'span_bytes')}
                          for row in result.get('excerpts', [])],
            'kind': obs.get('kind'), 'tool': obs.get('tool'), 'route': obs.get('route'),
            'coverage': obs.get('coverage'), 'continuation_pending': bool(obs.get('continuation')),
            'hit_case_ids': [row.get('case_id') for row in obs.get('hits', [])]}


class ProbeHarness(AdaptiveHarness):
    def __init__(self, *args, trace, experiment_mode, experiment_root=None, **kwargs):
        self.trace = trace
        self.experiment_mode = experiment_mode
        super().__init__(*args, **kwargs)
        self.config['experiment'] = {'version': VERSION,
                                     'code_binding': code_binding(Path(experiment_root or Path.cwd())),
                                     'mode': experiment_mode,
                                     'cumulative_cap_sentinel': PRACTICAL_UNBOUNDED if experiment_mode == 'uncapped' else None,
                                     'automatic_no_progress_stop': experiment_mode != 'uncapped'}

    def _operator_stop(self, db, state):
        if (self.ledger.path / 'STOP').is_file():
            self.trace.emit('operator_stop_at_safe_boundary', usage=state.usage())
            self._stop(db, state, 'no_progress', 'operator_stop_file')
            return True
        return False

    def _turn(self, db, state):
        if self._operator_stop(db, state):
            return
        # Deliberately bypass only M6's automatic no-progress heuristic.
        # M4 admission, context budgets, schema, source and recovery still apply.
        with self.trace.stage('prepare_next_controller_request'):
            if self.experiment_mode == 'uncapped':
                AgentHarness._turn(self, db, state)
            else:
                super()._turn(db, state)

    def _apply_action(self, db, state):
        if self._operator_stop(db, state):
            return
        with self.trace.stage('pipeline_action', action=state.pending_action['action']):
            return super()._apply_action(db, state)

    def _write(self, db, state, kind, **fields):
        event = super()._write(db, state, kind, **fields)
        # Full canonical payload/action/results remain in the append-only ledger.
        summary = {'seq': event['seq'], 'kind': kind, 'usage': state.usage(),
                   'candidate_count': len(state.candidates),
                   'raw_record_count': len(state.catalog),
                   'active_assessment_count': len(state.active_assessments)}
        for key in ('request_id', 'action_id', 'status', 'action', 'final',
                    'input_tokens', 'output_tokens', 'admitted_input_tokens',
                    'provider_latency_ms', 'transport_elapsed_ms', 'reason'):
            if key in event:
                summary[key] = event[key]
        if 'm6_reply' in event:
            summary['model_reply'] = event['m6_reply']
        if 'result' in event:
            summary['result'] = observation_summary(event['result'])
        self.trace.emit('ledger_event', **summary)
        return event


@contextmanager
def runtime(root, run_dir, cfg, trace):
    from pipeline_v2.agent_harness.modal_qwen import (
        APP_NAME, MODAL_FUNCTION_ID, MODEL, MODEL_REVISION, VLLM_VERSION, ModalQwenTransport)
    from pipeline_v2.full_search.source_tools import SourceToolsSession
    from pipeline_v2.sparse_bm25.index import SparseSession
    from pipeline_v2.query_navigation import HierarchicalM3Tools, QueryNavigationConfig
    from pipeline_v2.m6_hybrid import (EmbeddingBudget, HybridSearch,
                                      AccountedSparseHybridSession, M6Qdrant)

    class LoggedTransport(ModalQwenTransport):
        def send_structured(self, payload, request_id, schema):
            body = json.loads(payload)
            trace.emit('controller_request', request_id=request_id,
                       input_tokens=self.count_tokens(payload),
                       output_token_cap=body['max_output_tokens'],
                       available_tools=[row['name'] for row in body.get('available_tools', [])],
                       a_paragraphs=body.get('m6', {}).get('a_paragraphs', {}),
                       query_navigation=body.get('m6', {}).get('query_navigation'))
            with trace.stage('controller_remote_wait', call_id=lambda: self.last_call_id,
                             request_id=request_id):
                reply = super().send_structured(payload, request_id, schema)
            trace.emit('controller_response', request_id=request_id, call_id=self.last_call_id,
                       action=reply.action, input_tokens=reply.input_tokens,
                       output_tokens=reply.output_tokens, latency_ms=reply.latency_ms)
            return reply

    class LoggedQdrant(M6Qdrant):
        def _request(self, method, path, body=None, allow404=False):
            if method == 'POST' and '/points/query' in path:
                with trace.stage('dense_exact_query'):
                    return super()._request(method, path, body, allow404)
            return super()._request(method, path, body, allow404)

    class LoggedSession(AccountedSparseHybridSession):
        def __init__(self, root, journal):
            with trace.stage('open_hybrid_session'):
                super().__init__(root, journal)
                previous = self.db
                self.db = LoggedQdrant(self.profile['qdrant']['url'], self.manifest['collection'],
                                      self.fingerprint, self.dimensions, timeout=previous.timeout)
                previous.session.close()

        def _query_embedding(self, query, query_case, request_id):
            with trace.stage('query_embedding', query=query, query_case=query_case,
                             m3_request_id=request_id):
                return super()._query_embedding(query, query_case, request_id)

        def search(self, query, query_case, limit):
            with trace.stage('hybrid_search', query=query, query_case=query_case, limit=limit):
                result = super().search(query, query_case, limit)
            trace.emit('hybrid_search_result',
                       candidate_ids=[hit['case_id'] for hit in result.get('hits', [])],
                       coverage=result.get('coverage'), timings=result.get('timings'))
            return result

    transport = LoggedTransport(root / cfg['tokenizer_dir'], instructions=INSTRUCTIONS, wait_seconds=None)
    lexical = sources = hybrid = None
    try:
        with trace.stage('open_local_source_and_sparse_index'):
            lexical = SparseSession(root)
            sources = SourceToolsSession(root, snapshot=lexical)
            tools = HierarchicalM3Tools(
                sources, lexical, cfg['query_id'], byte_budget=cfg['byte_budget'], map_limit=cfg['map_limit'],
                navigation_config=QueryNavigationConfig(**cfg['query_navigation']),
                count_tokens=transport.count_tokens, output_token_cap=cfg['budget']['max_output_tokens'])
            initial, whole = tools.query_start()
        hybrid = HybridSearch(root, run_dir, EmbeddingBudget(**cfg['embedding_budget']),
                              session_factory=LoggedSession, expected_snapshot={
                                  'full_manifest_sha256': lexical.binding['manifest.json'],
                                  'sparse_manifest_sha256': lexical.index_binding['manifest.json'],
                                  'embedding_fingerprint': lexical.manifest['embedding_fingerprint'],
                                  'collection': lexical.manifest['collection']})
        model = [APP_NAME, MODAL_FUNCTION_ID, MODEL, MODEL_REVISION, VLLM_VERSION]
        identity = RunIdentity(
            run_id=run_dir.name, query_id=cfg['query_id'], query_source_hash=whole.source_hash,
            candidate_fingerprint=fingerprint(lexical.binding), index_fingerprint=fingerprint(lexical.index_binding),
            profile_fingerprint=fingerprint([VERSION, cfg]), model_fingerprint=fingerprint(model),
            prompt_fingerprint=transport.prompt_fingerprint, tools_fingerprint=tools.fingerprint,
            tokenizer_fingerprint=transport.tokenizer_fingerprint)
        harness = ProbeHarness(run_dir, identity=identity, budget=Budget(**cfg['budget']),
                               m3_tools=tools, transport=transport, config=AdaptiveConfig(**cfg['adaptive_config']),
                               initial_observation=initial, query_excerpt=whole,
                               hybrid_search=hybrid, trace=trace, experiment_mode=cfg['experiment_mode'],
                               experiment_root=root)
        binding = {'identity': asdict(identity), 'harness_config': harness.config,
                   'initial_sha256': fingerprint({'observation': initial.observation,
                                                  'excerpts': [row.to_record() for row in initial.excerpts],
                                                  'candidates': initial.candidates,
                                                  'source_requests': initial.source_requests}),
                   'code_binding': code_binding(root)}
        yield harness, transport, binding
    finally:
        if hybrid is not None:
            hybrid.close()
        if sources is not None:
            sources.close()
        if lexical is not None:
            lexical.close()


def prepare(root, run_dir, value):
    cfg = settings(value)
    if run_dir.exists():
        raise HarnessError('Prepare requires a fresh experiment run directory')
    run_dir.mkdir(parents=True)
    trace = Trace(run_dir)
    with runtime(root, run_dir, cfg, trace) as (harness, _, binding):
        preview = harness.prepare()
        plan = {'version': VERSION, 'root': str(root), 'settings': cfg, 'binding': binding,
                'preflight_status': preview['status'], 'first_payload_sha256': fingerprint(preview),
                'model_requests': 0, 'first_payload_input_tokens': preview['input_tokens'],
                'experiment_mode': cfg['experiment_mode'],
                'limits': {'cumulative_sentinel': PRACTICAL_UNBOUNDED if cfg['experiment_mode'] == 'uncapped' else None,
                           'automatic_no_progress_stop': cfg['experiment_mode'] != 'uncapped',
                           'per_request_input': 8500, 'per_request_output': 512,
                           'retry': 0, 'mathematically_unlimited': False}}
        for name, value in (('first_payload.json', preview), ('plan.json', plan)):
            with (run_dir / name).open('xb') as stream:
                stream.write(encode(value))
        trace.emit('prepared', status=preview['status'], model_requests=0,
                   input_tokens=preview['input_tokens'], limits=plan['limits'])
        return plan


def run(root, run_dir):
    plan = _load(run_dir / 'plan.json')
    if plan.get('version') != VERSION or plan.get('preflight_status') != 'ready':
        raise HarnessError('Expected a ready isolated experiment plan')
    if code_binding(root) != plan['binding']['code_binding']:
        raise HarnessError('Experiment/production source changed after prepare; use a fresh run')
    if fingerprint(_load(run_dir / 'first_payload.json')) != plan['first_payload_sha256']:
        raise HarnessError('Prepared first payload changed')
    trace = Trace(run_dir)
    trace.emit('invocation_started', stop_requested=(run_dir / 'STOP').is_file(),
               experiment_mode=plan['experiment_mode'], limits=plan['limits'])
    with runtime(root, run_dir, settings(plan['settings']), trace) as (harness, transport, binding):
        if encode(binding) != encode(plan['binding']):
            raise HarnessError('Prepared binding changed; use a fresh run')
        try:
            result = harness.run()
            report = {'version': VERSION, 'status': 'returned', 'result': result,
                      'modal_receipts_this_invocation': transport.receipts}
        except BaseException as exc:
            report = {'version': VERSION, 'status': 'interrupted_or_error',
                      'error_type': type(exc).__name__, 'result': harness.inspect(),
                      'modal_receipts_this_invocation': transport.receipts,
                      'remote_cancelled': 'unknown; inspect receipts/call metadata'}
            with (run_dir / f'report_{time_ns()}.json').open('xb') as stream:
                stream.write(encode(report))
            trace.emit('invocation_interrupted_or_error', error_type=type(exc).__name__,
                       call_id=transport.last_call_id, usage=report['result'].get('usage'))
            raise
        with (run_dir / f'report_{time_ns()}.json').open('xb') as stream:
            stream.write(encode(report))
        trace.emit('invocation_finished', result=result)
        return report


def status(run_dir):
    """Read-only: no transport, tokenizer, source session, writer or remote calls."""
    events = Ledger(run_dir).read()
    state = RunState(events)
    snapshot = state.snapshot()
    plan_path = run_dir / 'plan.json'
    plan = _load(plan_path) if plan_path.is_file() else {}
    embedding = None
    if (run_dir / 'embedding_events.sqlite3').is_file() and plan:
        from pipeline_v2.m6_hybrid import EmbeddingBudget, EmbeddingJournal
        journal = EmbeddingJournal(run_dir, Path(plan['root']), EmbeddingBudget(**plan['settings']['embedding_budget']))
        embedding = journal.usage()
    return {'version': VERSION, 'run_dir': str(run_dir), 'query_id': plan.get('settings', {}).get('query_id'),
            'stop_requested': (run_dir / 'STOP').is_file(), 'usage': snapshot.get('usage'),
            'final': state.final, 'in_flight': state.in_flight and state.in_flight['request_id'],
            'active_action': state.active_action, 'pending_action': state.pending_action,
            'candidate_ids': sorted(state.candidates), 'raw_record_count': len(state.catalog),
            'active_assessment_count': len(state.active_assessments),
            'last_event': ({key: events[-1].get(key) for key in ('seq', 'kind', 'at_utc', 'status')}
                           if events else None), 'embedding_usage': embedding,
            'trace': str(run_dir / 'trace.jsonl')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'run', 'status', 'stop'))
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--settings', type=Path, default=Path(__file__).with_name('settings.json'))
    args = parser.parse_args()
    root, run_dir = args.root.resolve(), args.run_dir.resolve()
    if args.command == 'prepare':
        result = prepare(root, run_dir, _load(args.settings))
        result = {'status': result['preflight_status'], 'model_requests': 0,
                  'input_tokens': result['first_payload_input_tokens'], 'plan': str(run_dir / 'plan.json')}
    elif args.command == 'run':
        result = run(root, run_dir)
    elif args.command == 'status':
        result = status(run_dir)
    else:
        if not run_dir.is_dir() or not (run_dir / 'plan.json').is_file():
            raise HarnessError('Stop requires an existing experiment plan')
        with (run_dir / 'STOP').open('ab'):
            pass
        result = {'stop_requested': True, 'effect': 'safe boundary; active remote work may still be running'}
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
