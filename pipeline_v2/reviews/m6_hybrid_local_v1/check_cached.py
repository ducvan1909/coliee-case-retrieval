"""Exercise M6 through M3 hybrid, local Qdrant, and real raw sources."""

from contextlib import ExitStack
from argparse import ArgumentParser
from pathlib import Path
from time import perf_counter

from pipeline_v2.agent_harness import Budget, RunIdentity
from pipeline_v2.agent_harness.contracts import encode, fingerprint
from pipeline_v2.agent_harness.modal_qwen import ModalQwenTransport
from pipeline_v2.full_search.hybrid import fuse_channels
from pipeline_v2.full_search.source_tools import SourceToolsSession
from pipeline_v2.m4 import M3Tools
from pipeline_v2.m6 import AdaptiveConfig, AdaptiveHarness, M6_INSTRUCTIONS
from pipeline_v2.m6_hybrid import EmbeddingBudget, HybridSearch
from pipeline_v2.reviews.m6_local_v1.replay_corpus import Replay
from pipeline_v2.reviews.m3_completion_v1.hybrid_source_integration import replay_restored_diagnostic
from pipeline_v2.sparse_bm25.index import SparseHybridSession


class CachedDiagnostic(SparseHybridSession):
    replay_recorded = False

    def search(self, query, query_case, limit):
        if self.replay_recorded:
            recorded = replay_restored_diagnostic()
            self.response = {**recorded, 'hits': recorded['hits'][:limit]}
        else:
            self.response = self.search_cached(query, query_case, '095448:88b488d43fde1389756a8dd7', limit)
        return self.response

    def _query_embedding(self, *args):
        raise AssertionError('Cached diagnostic attempted query embedding')


def no_remote():
    raise AssertionError('Diagnostic attempted controller inference')


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('run_dir', type=Path)
    parser.add_argument('--replay-recorded', action='store_true')
    args = parser.parse_args()
    root = Path.cwd()
    run_dir = args.run_dir.resolve()
    run_dir.mkdir(parents=True, exist_ok=False)
    started = perf_counter()
    with ExitStack() as stack:
        cached = stack.enter_context(CachedDiagnostic(root))
        cached.replay_recorded = args.replay_recorded
        lexical = cached.lexical
        sources = SourceToolsSession(root, snapshot=lexical)
        stack.callback(sources.close)
        hybrid = HybridSearch(root, run_dir, EmbeddingBudget(0, 0),
                              session_factory=lambda root, journal: cached,
                              execution_mode='cached_vector_diagnostic')
        # The outer context owns the diagnostic session.
        tools = M3Tools(sources, lexical, '095448.txt', byte_budget=4096, map_limit=5)
        initial, whole = tools.query_start()
        tokenizer = ModalQwenTransport(root / 'cache/tokenizers/qwen36_27b_fp8',
                                       instructions=M6_INSTRUCTIONS, remote_factory=no_remote)
        replay = Replay(tokenizer.count_tokens)
        identity = RunIdentity(run_dir.name, tools.query_case, whole.source_hash, fingerprint(lexical.binding),
                               fingerprint(lexical.index_binding), 'cached-diagnostic', 'scripted',
                               tokenizer.prompt_fingerprint, tools.fingerprint, tokenizer.tokenizer_fingerprint)
        harness = AdaptiveHarness(
            run_dir, identity=identity, budget=Budget(8, 8, 120000, 24000, 512, 124096, 0),
            m3_tools=tools, transport=replay, config=AdaptiveConfig(channel='hybrid', search_limit=3),
            initial_observation=initial, query_excerpt=whole, hybrid_search=hybrid,
        )
        result = harness.run()
        response = getattr(cached, 'response', None)
        expected = fuse_channels(response['channels'], limit=3) if response else []
        receipt = next((event['result']['observation'] for event in harness.events()
                        if event.get('result') and event['result']['observation'].get('policy')), {})
        checks = {
            'fused_order': bool(receipt) and [h['case_id'] for h in receipt['hits']] == [h['case_id'] for h in expected],
            'no_self_match': bool(receipt) and all(h['case_id'] != tools.query_case for h in receipt['hits']),
            'three_channels': set(receipt.get('coverage', {})) == {'case_bm25', 'passage_bm25', 'dense_passage'},
            'accepted_assessment': len(result['active_assessment_ids']) == 1,
            'cached_zero_inference': result['embedding_usage']['model_requests'] == 0 and not tokenizer.receipts,
            'resume_no_replay': harness.run()['embedding_usage']['search_operations'] == 1,
            'pending_selection': result['selection_status'] == 'pending_selection',
        }
    summary = {'checks': checks, 'replay_recorded': args.replay_recorded, 'elapsed_seconds': perf_counter() - started,
               'embedding_usage': result['embedding_usage'], 'controller_replay_usage': result['usage'],
               'retrieval': receipt, 'stop_reason': result['stop_reason'], 'stop_detail': result['stop_detail']}
    (run_dir / 'report.json').write_bytes(encode(summary))
    print(checks)
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
