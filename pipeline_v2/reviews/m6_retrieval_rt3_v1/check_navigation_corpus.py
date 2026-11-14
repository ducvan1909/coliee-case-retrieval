"""Check hierarchical maps on real sources and scripted navigation, with zero inference."""

import argparse
from contextlib import ExitStack, closing
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter

from pipeline_v2.agent_harness import Budget, RunIdentity
from pipeline_v2.agent_harness.contracts import HarnessError, ModelReply, encode, fingerprint
from pipeline_v2.agent_harness.modal_qwen import ModalQwenTransport
from pipeline_v2.agent_harness.ledger import RunState
from pipeline_v2.full_search.source_tools import SourceToolsSession
from pipeline_v2.m6 import AdaptiveConfig, AdaptiveHarness, implementation_fingerprint
from pipeline_v2.m6_live import INSTRUCTIONS
from pipeline_v2.query_navigation import HierarchicalM3Tools, QueryNavigationConfig
from pipeline_v2.sparse_bm25.index import SparseSession


QUERIES = ('017984.txt', '090579.txt', '021095.txt')


def no_remote(*args, **kwargs):
    raise AssertionError('RT3 probe must not create a remote client')


class ScriptedNavigation:
    def __init__(self, counter):
        self.count_tokens = counter
        self.payloads = []

    def send_structured(self, payload, request_id, schema):
        body = json.loads(payload)
        state = body['m6']
        page = state['query_navigation']
        step = len(self.payloads)
        if self.count_tokens(payload) > 7400:
            raise HarnessError('Actual scripted-controller payload exceeds the unchanged cap')
        if step in (0, 3, 4, 6):
            ref = (page['children'][0]['region_ref'] if step == 0 else
                   page['parent_ref'] if step == 3 else
                   page['children'][-1]['region_ref'] if step == 4 else page['root_ref'])
            key = next(key for key, row in state['query_maps'].items() if row['binding']['region_ref'] == ref)
            action = {'action': 'expand_query_map', 'args': {'map_ref': key}}
        elif step in (1, 5):
            key = next(key for key, row in state['query_targets'].items()
                       if row['binding']['region_ref'] == page['current']['region_ref'])
            action = {'action': 'read_query_passages', 'args': {'query_ref': key}}
        elif step == 2:
            key = next(key for key, row in state['expansions'].items()
                       if row['description']['purpose'] == 'continue_pending_raw_page')
            action = {'action': 'read_more_context', 'args': {'context_ref': key}}
        elif step == 7:
            action = {'action': 'finish_case_review', 'args': {'reason': 'no_progress'}}
        else:
            raise HarnessError('Unexpected scripted navigation step')
        self.payloads.append(body)
        return ModelReply(action, self.count_tokens(payload), 0, None)


class ScriptedRootRead(ScriptedNavigation):
    def send_structured(self, payload, request_id, schema):
        body = json.loads(payload)
        if not self.payloads:
            state = body['m6']
            key = next(key for key, row in state['query_targets'].items()
                       if row['binding']['region_ref'] == state['query_navigation']['root_ref'])
            action = {'action': 'read_query_passages', 'args': {'query_ref': key}}
        else:
            action = {'action': 'finish_case_review', 'args': {'reason': 'no_progress'}}
        self.payloads.append(body)
        return ModelReply(action, self.count_tokens(payload), 0, None)


def literal_check(raw, row):
    a, b = row['span_bytes']
    piece = raw[a:b]
    if piece.decode('utf-8') != row['text'] or sha256(piece).hexdigest() != row['text_sha256']:
        raise HarnessError('Map preview differs from canonical source bytes')


def probe(root, run_dir):
    start = perf_counter()
    tokenizer = ModalQwenTransport(root / 'cache/tokenizers/qwen36_27b_fp8',
                                   instructions=INSTRUCTIONS, remote_factory=no_remote)
    config = QueryNavigationConfig()
    maps, tools_by_query = [], {}
    with ExitStack() as stack:
        print(json.dumps({'stage': 'open_source_snapshot'}), flush=True)
        lexical = stack.enter_context(closing(SparseSession(root)))
        sources = stack.enter_context(closing(SourceToolsSession(root, snapshot=lexical)))
        for query in QUERIES:
            print(json.dumps({'stage': 'check_tree', 'query_id': query}), flush=True)
            tools = HierarchicalM3Tools(sources, lexical, query, byte_budget=1024, map_limit=2,
                                        navigation_config=config, count_tokens=tokenizer.count_tokens,
                                        output_token_cap=384)
            tools_by_query[query] = tools
            tree = tools.query_tree
            stack_refs, leaf_spans, pages, max_depth, max_tokens = [(tree.root_ref, 0)], [], 0, 0, 0
            min_chars, min_guidance = config.snippet_chars, None
            while stack_refs:
                ref, depth = stack_refs.pop()
                node = tree.region(ref)
                children = tree.children(ref)
                page = tools.map_page(ref)
                count = tools.page_tokens(page)
                if count > config.map_max_tokens or len(children) > config.max_children:
                    raise HarnessError('Map page exceeds explicit token/fanout cap')
                min_chars = min(min_chars, page['snippet_chars'])
                for item in page['children'] or [page['current']]:
                    literals = [*item.get('snippets', []), *([item['heading']] if item.get('heading') else [])]
                    present = sum(isinstance(row.get('text'), str) and bool(row['text']) for row in literals)
                    if present == 0:
                        raise HarnessError('Map fits tokens but has no literal text to guide a region choice')
                    min_guidance = present if min_guidance is None else min(min_guidance, present)
                max_tokens, max_depth, pages = max(max_tokens, count), max(max_depth, depth), pages + 1
                for item in (page['current'], *page['children']):
                    for snippet in item.get('snippets', []):
                        literal_check(tree.raw, snippet)
                    if item.get('heading'):
                        literal_check(tree.raw, item['heading'])
                if children:
                    ordered = sorted(children, key=lambda row: row['span_bytes'])
                    cursor = node['span_bytes'][0]
                    for child in ordered:
                        a, b = child['span_bytes']
                        if a != cursor or not a < b or b - a >= node['span_bytes'][1] - node['span_bytes'][0]:
                            raise HarnessError('Child regions have gap/overlap or do not shrink')
                        tree.raw[a:b].decode('utf-8')
                        cursor = b
                        if tree.parent(child['region_ref']) != ref:
                            raise HarnessError('Child parent ref mismatch')
                    if cursor != node['span_bytes'][1]:
                        raise HarnessError('Children do not cover their complete parent')
                    stack_refs.extend((row['region_ref'], depth + 1) for row in children)
                else:
                    leaf_spans.append(node['span_bytes'])
            ordered = sorted(leaf_spans)
            if ordered[0][0] != 0 or ordered[-1][1] != len(tree.raw):
                raise HarnessError('Tree omits heading/gap/trailing raw bytes')
            if any(left[1] != right[0] for left, right in zip(ordered, ordered[1:])):
                raise HarnessError('Terminal intervals do not partition the complete source')
            source_record = sources._case(query)[1]
            root_page = tools.map_page(tree.root_ref)
            shown_headings = [row['heading'] for row in (root_page['current'], *root_page['children'])
                              if row.get('heading')]
            if source_record.get('headings') and not shown_headings:
                raise HarnessError('Real M2 headings were discarded from the map')
            maps.append({'query_id': query, 'source_hash': tree.source_hash, 'source_bytes': len(tree.raw),
                         'tree_binding': tree.binding, 'pages_checked': pages, 'leaf_count': len(ordered),
                         'max_depth': max_depth, 'max_map_tokens': max_tokens,
                         'min_snippet_chars': min_chars, 'min_guidance_literals_per_region': min_guidance,
                         'observed_heading_count': len(source_record.get('headings', [])),
                         'root_displayed_heading_count': len(shown_headings), 'status': 'PASS'})

        query = '021095.txt'
        tools = tools_by_query[query]
        initial, whole = tools.query_start()
        identity = RunIdentity(run_dir.name, query, whole.source_hash, fingerprint(lexical.binding),
                               fingerprint(lexical.index_binding), fingerprint(asdict(config)),
                               'scripted-navigation-not-a-model', tokenizer.prompt_fingerprint,
                               tools.fingerprint, tokenizer.tokenizer_fingerprint)
        scripted = ScriptedNavigation(tokenizer.count_tokens)
        agent = AdaptiveHarness(run_dir / 'navigation', identity=identity,
                                budget=Budget(8, 8, 60000, 7400, 384, 63072, 0),
                                m3_tools=tools, transport=scripted,
                                config=AdaptiveConfig(channel='lexical_both', max_reviews=0, audit_untriggered=0),
                                initial_observation=initial, query_excerpt=whole)
        prepared = agent.prepare()
        if prepared['status'] != 'ready':
            raise HarnessError('Real hierarchical initial payload is unfit')
        body = prepared['payload']
        if body['excerpts'] or 'search_cases_by_issue' in {tool['name'] for tool in body['available_tools']}:
            raise HarnessError('Long-A map preview became raw search evidence')
        with (run_dir / 'first_payload.json').open('xb') as stream:
            stream.write(encode(body))
        outcome = agent.run()
        count_before_resume = len(scripted.payloads)
        resumed = agent.run()
        if count_before_resume != 8 or len(scripted.payloads) != count_before_resume:
            if outcome.get('stop_detail', '').startswith('token_count_error:'):
                agent._fit_payload(RunState(agent.events()), 7400)
            raise HarnessError('Scripted navigation or completed resume call count mismatch')
        if outcome['stop_reason'] != 'no_progress' or resumed['stop_reason'] != outcome['stop_reason']:
            raise HarnessError('Unexpected scripted navigation stop')
        final_page = scripted.payloads[-1]['m6']['query_navigation']
        for payload in scripted.payloads:
            offered_page = payload['m6']['query_navigation']
            for item in offered_page['children'] or [offered_page['current']]:
                if not item.get('snippets') and not item.get('heading'):
                    raise HarnessError('Final model payload lost region text during clipping')
        for index in (2, 6):
            payload = scripted.payloads[index]
            if not payload['excerpts'] or 'search_cases_by_issue' not in {row['name'] for row in payload['available_tools']}:
                raise HarnessError('Reading an internal region did not deliver raw with an issue-search choice')
        if final_page['current']['region_ref'] != final_page['root_ref'] or final_page['totals']['raw_read_bytes'] <= 0:
            raise HarnessError('Back-to-root or delivered raw coverage failed')
        if tokenizer._remote is not None or tokenizer.receipts:
            raise HarnessError('Unexpected remote initialization')
        direct = ScriptedRootRead(tokenizer.count_tokens)
        root_identity = RunIdentity(**{**asdict(identity), 'run_id': identity.run_id + '-root-read'})
        root_agent = AdaptiveHarness(run_dir / 'direct_root_read', identity=root_identity,
                                     budget=Budget(2, 2, 14800, 7400, 384, 15568, 0),
                                     m3_tools=tools, transport=direct,
                                     config=AdaptiveConfig(channel='lexical_both', max_reviews=0, audit_untriggered=0),
                                     initial_observation=initial, query_excerpt=whole)
        root_agent.run()
        if len(direct.payloads) != 2 or not direct.payloads[1]['excerpts']:
            raise HarnessError('Direct root read failed to deliver raw within the global payload cap')
        if 'search_cases_by_issue' not in {row['name'] for row in direct.payloads[1]['available_tools']}:
            raise HarnessError('Direct root raw did not offer grounded issue search')
        if any(direct.count_tokens(encode(row)) > 7400 for row in direct.payloads):
            raise HarnessError('Direct root read exceeds the unchanged global payload cap')
        files = ('pipeline_v2/query_navigation.py', 'pipeline_v2/m6.py',
                 'pipeline_v2/agent_harness/adaptive_policy.py', 'pipeline_v2/m6_live.py',
                 'pipeline_v2/reviews/m6_retrieval_rt3_v1/check_navigation_corpus.py')
        return {'status': 'PASS', 'maps': maps, 'navigation_requests_scripted': count_before_resume,
                'first_payload_tokens': prepared['input_tokens'],
                'max_payload_tokens': max(scripted.count_tokens(encode(row)) for row in scripted.payloads),
                'direct_root_read_scripted_requests': len(direct.payloads),
                'direct_root_read_max_payload_tokens': max(direct.count_tokens(encode(row)) for row in direct.payloads),
                'final_navigation_totals': final_page['totals'], 'elapsed_seconds': perf_counter() - start,
                'config': asdict(config), 'implementation_fingerprint': implementation_fingerprint(),
                'tokenizer_fingerprint': tokenizer.tokenizer_fingerprint,
                'files_sha256': {name: sha256((root / name).read_bytes()).hexdigest() for name in files},
                'controller_requests': 0, 'embedding_requests': 0, 'retrieval_requests': 0,
                'gold_labels_accessed': False,
                'limitations': ['Tree traversal and eight controller actions are scripted, not model navigation quality.',
                                'Source integrity is checked through current readers; no new full vector verification.',
                                'No semantic summaries, query embedding, retrieval or recall evaluation.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    args = parser.parse_args()
    args.run_dir.mkdir(parents=True, exist_ok=False)
    start = perf_counter()
    try:
        report = probe(Path.cwd(), args.run_dir)
    except Exception as exc:
        report = {'status': 'FAIL', 'error_type': type(exc).__name__, 'error': str(exc),
                  'elapsed_seconds': perf_counter() - start, 'controller_requests': 0,
                  'embedding_requests': 0, 'retrieval_requests': 0}
        with (args.run_dir / 'report.json').open('xb') as stream:
            stream.write(encode(report))
        print(json.dumps(report, ensure_ascii=False))
        raise
    with (args.run_dir / 'report.json').open('xb') as stream:
        stream.write(encode(report))
    print(json.dumps({'status': report['status'], 'maps': len(report['maps']),
                      'scripted_requests': report['navigation_requests_scripted'],
                      'elapsed_seconds': report['elapsed_seconds'], 'run_dir': str(args.run_dir)}))


if __name__ == '__main__':
    main()
