"""Probe clipped paragraph search refs on real discovery sources, with zero inference.

The raw windows and query text here are scripted diagnostic inputs, not model
choices. No retrieval, gold scoring or semantic assessment is performed.
"""

import argparse
from contextlib import ExitStack, closing
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter

from pipeline_v2.agent_harness import Budget, RunIdentity
from pipeline_v2.agent_harness.adaptive_policy import catalog, translate
from pipeline_v2.agent_harness.contracts import HarnessError, encode, fingerprint
from pipeline_v2.agent_harness.modal_qwen import ModalQwenTransport
from pipeline_v2.full_search.source_tools import SourceToolsSession
from pipeline_v2.m4 import M3Tools
from pipeline_v2.m6 import AdaptiveConfig, AdaptiveHarness, implementation_fingerprint
from pipeline_v2.m6_live import INSTRUCTIONS
from pipeline_v2.sparse_bm25.index import SparseSession


QUERIES = ('017984.txt', '090579.txt', '021095.txt')
ISSUE = 'partial paragraph diagnostic'


def no_remote(*args, **kwargs):
    raise AssertionError('RT2 local probe must never call a remote model')


class NoInference:
    def __init__(self, transport):
        self.count_tokens = transport.count_tokens

    send_structured = staticmethod(no_remote)


def window(raw, paragraph_span, position):
    start, end = paragraph_span
    text = raw[start:end].decode('utf-8')
    offsets = [start]
    for char in text:
        offsets.append(offsets[-1] + len(char.encode('utf-8')))
    index = {'beginning': 0, 'middle': len(text) // 2,
             'end': max(0, len(text) - 128)}[position]
    stop = min(len(text), index + 128)
    return [offsets[index], offsets[stop]]


def probe(root, run_dir, tokenizer_dir):
    started = perf_counter()
    tokenizer = ModalQwenTransport(tokenizer_dir, instructions=INSTRUCTIONS, remote_factory=no_remote)
    counter = NoInference(tokenizer)
    results = []
    with ExitStack() as stack:
        print(json.dumps({'stage': 'open_sparse_snapshot', 'status': 'STARTED'}), flush=True)
        lexical = stack.enter_context(closing(SparseSession(root)))
        sources = stack.enter_context(closing(SourceToolsSession(root, snapshot=lexical)))
        print(json.dumps({'stage': 'source_snapshot_ready'}), flush=True)
        for query in QUERIES:
            tools = M3Tools(sources, lexical, query, byte_budget=1024, map_limit=2)
            initial, whole = tools.query_start()
            identity = RunIdentity(run_dir.name, query, whole.source_hash,
                                   fingerprint(lexical.binding), fingerprint(lexical.index_binding),
                                   'rt2-local-probe', 'no-controller-inference', tokenizer.prompt_fingerprint,
                                   tools.fingerprint, tokenizer.tokenizer_fingerprint)
            agent = AdaptiveHarness(run_dir / query, identity=identity,
                                    budget=Budget(1, 1, 7400, 7400, 384, 7784, 0),
                                    m3_tools=tools, transport=counter, config=AdaptiveConfig(),
                                    initial_observation=initial, query_excerpt=whole)
            long = [row for row in agent.query_paragraphs
                    if row['span_bytes'][1] - row['span_bytes'][0] > 1024]
            if not long:
                raise HarnessError('Expected at least one long paragraph in each locked pilot source')
            paragraph = max(long, key=lambda row: row['span_bytes'][1] - row['span_bytes'][0])
            p_start, p_end = paragraph['span_bytes']
            raw = whole.text.encode('utf-8')
            for position in ('beginning', 'middle', 'end'):
                print(json.dumps({'stage': 'open_raw_page', 'query_id': query,
                                  'position': position}), flush=True)
                requested = window(raw, paragraph['span_bytes'], position)
                page = tools.open_query({'hit_spans': [requested]})
                excerpts = [row.to_record() for row in page.excerpts]
                body = {'query_id': query, 'query_source_hash': whole.source_hash,
                        'max_output_tokens': 384, 'excerpts': excerpts,
                        'current_payload_source_refs': [row['ref'] for row in excerpts]}
                anchors = agent._visible_paragraphs(body)
                body['m6'] = {'a_paragraphs': anchors, 'hybrid_budget_remaining': None,
                              'channel': 'lexical_both', 'search_limit': 3, 'candidates': {},
                              'query_targets': {}, 'expansions': {}, 'reloads': {},
                              'review_candidates': {}, 'review_count': 0, 'max_reviews': 0,
                              'search_completed': False}
                tool_rows, schema, citation_rows, pairs = catalog(body)
                body.update(available_tools=tool_rows)
                body['m6'].update(schema_fingerprint=fingerprint(schema), citation_refs=citation_rows,
                                  pair_refs=pairs)
                token_count = tokenizer.count_tokens(encode(body))
                if token_count > 7400:
                    raise HarnessError('Diagnostic model-shaped payload exceeds the unchanged input cap')
                spans = {(max(p_start, row['span_bytes'][0]), min(p_end, row['span_bytes'][1]))
                         for row in excerpts if max(p_start, row['span_bytes'][0]) < min(p_end, row['span_bytes'][1])}
                maximal = {span for span in spans if not any(other != span and
                           other[0] <= span[0] and span[1] <= other[1] for other in spans)}
                selected = {key: row for key, row in anchors.items()
                            if row.get('paragraph_handle') == paragraph['handle']}
                if {tuple(row['span_bytes']) for row in selected.values()} != maximal or not selected:
                    raise HarnessError('Offered fragments differ from actual maximal raw intersections')
                translated = []
                for handle, row in selected.items():
                    a, b = row['span_bytes']
                    if row['text_sha256'] != sha256(raw[a:b]).hexdigest():
                        raise HarnessError('Fragment hash differs from canonical raw bytes')
                    if row['paragraph_span_bytes'] != [p_start, p_end] or row['paragraph_coverage'] != 'partial':
                        raise HarnessError('Original paragraph/partial metadata mismatch')
                    action = translate(body, {'action': 'search_cases_by_issue',
                                             'args': {'issue': ISSUE, 'a_paragraph_ref': handle}})
                    need = action['args']['_m6_need']
                    if action['args']['text'] != ISSUE or list(need['a_paragraph']['span_bytes']) != [a, b]:
                        raise HarnessError('Translation changed diagnostic query or visible grounding span')
                    for key in ('paragraph_handle', 'paragraph_span_bytes', 'paragraph_coverage'):
                        if need['a_paragraph'][key] != row[key]:
                            raise HarnessError('Source need lost original paragraph metadata')
                    translated.append({'handle': handle, 'span_bytes': [a, b], 'text_sha256': row['text_sha256'],
                                       'source_ref': row['source_ref']})
                results.append({'query_id': query, 'source_hash': whole.source_hash,
                                'paragraph_handle': paragraph['handle'], 'paragraph_span_bytes': [p_start, p_end],
                                'position': position, 'requested_span_bytes': requested,
                                'delivered_spans': [row['span_bytes'] for row in excerpts],
                                'token_count': token_count, 'anchors': translated, 'status': 'PASS'})
                print(json.dumps({'stage': 'partial_ref_verified', 'query_id': query,
                                  'position': position, 'token_count': token_count}), flush=True)
    if tokenizer._remote is not None or tokenizer.receipts:
        raise HarnessError('Unexpected remote initialization during local-only probe')
    names = ('pipeline_v2/m6.py', 'pipeline_v2/agent_harness/adaptive_policy.py',
             'pipeline_v2/reviews/m6_retrieval_rt2_v1/check_partial_corpus.py')
    return {'status': 'PASS', 'execution_mode': 'real_source_scripted_windows_local_tokenizer',
            'queries': list(QUERIES), 'checks': results, 'elapsed_seconds': perf_counter() - started,
            'implementation_fingerprint': implementation_fingerprint(),
            'files_sha256': {name: sha256((root / name).read_bytes()).hexdigest() for name in names},
            'tokenizer_fingerprint': tokenizer.tokenizer_fingerprint,
            'controller_requests': 0, 'embedding_requests': 0, 'retrieval_requests': 0,
            'gold_labels_accessed': False,
            'limitations': ['Window and query choices are scripted, not model semantic decisions.',
                            'Payload exercises raw/current refs and tool translation, not a full harness live run.',
                            'No gold scoring, recall claim or Qdrant/model inference.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--tokenizer-dir', type=Path, default=Path('cache/tokenizers/qwen36_27b_fp8'))
    args = parser.parse_args()
    args.run_dir.mkdir(parents=True, exist_ok=False)
    started = perf_counter()
    try:
        report = probe(Path.cwd(), args.run_dir, args.tokenizer_dir)
    except Exception as exc:
        report = {'status': 'FAIL', 'error_type': type(exc).__name__, 'error': str(exc),
                  'elapsed_seconds': perf_counter() - started, 'controller_requests': 0,
                  'embedding_requests': 0, 'retrieval_requests': 0}
        with (args.run_dir / 'report.json').open('xb') as stream:
            stream.write(encode(report))
        print(json.dumps(report, ensure_ascii=False))
        raise
    with (args.run_dir / 'report.json').open('xb') as stream:
        stream.write(encode(report))
    print(json.dumps({'status': report['status'], 'checks': len(report['checks']),
                      'elapsed_seconds': report['elapsed_seconds'], 'run_dir': str(args.run_dir)}))


if __name__ == '__main__':
    main()
