"""Synthetic pool pressure with the pinned tokenizer and full integrated catalog."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter

from pipeline_v2.agent_harness import RunIdentity, ToolResult
from pipeline_v2.experiments.context_manager_v1.cli import counter
from pipeline_v2.experiments.context_manager_v1.core import require, write_once
from pipeline_v2.tests.test_m6_adaptive import Tools
from .cli import choose
from .engine import Engine


class PoolTools(Tools):
    def __init__(self, size):
        super().__init__()
        self.ids = [f'fixture-{n:06}' for n in range(size)]

    def search_corpus(self, args):
        return ToolResult({'hits': [{'case_id': case, 'rank': index + 1,
            'open_ref': {'case_id': case, 'source_hash': self.b.source_hash, 'passage_ids': ['fixture-passage']}}
            for index, case in enumerate(self.ids)]}, candidates=tuple(self.ids))

    def open_source(self, args):
        raise AssertionError('Pool pressure fixture must not open fake candidate sources')


def run(root, output):
    require(not output.exists(), 'Fresh stress output directory required')
    output.mkdir(parents=True)
    count, binding = counter(root)
    results = []
    for size in (3, 50, 500, 10000):
        start = perf_counter()
        tools = PoolTools(size)
        identity = RunIdentity(f'stress-{size}', 'A', tools.a.source_hash, 'synthetic', 'synthetic',
                               'synthetic', 'forbidden', 'pinned', 'fixture', binding)
        engine = Engine(output / str(size), identity=identity, tools=tools, count_tokens=count,
                        raw_reader=lambda case: tools.a.text.encode() if case == 'A' else b'', counter_binding=binding)
        engine.step(lambda p: choose(p, 'search_cases_by_issue', issue='procedural fairness',
                                    source_proposition='The fairness test applies to the current legal issue.'))
        seen, peak, pages = [], 0, 0
        while True:
            p = engine.prepare()
            require(p['status'] == 'ready', 'Stress view unfit')
            cards = list(p['payload']['m6']['candidates'].values())
            require(len(cards) <= 5, 'Too many cards in view')
            seen.extend(r['case_id'] for r in cards)
            peak = max(peak, p['input_tokens'])
            pages += 1
            nxt = p['payload']['m6']['cm_page']['controls'].get('next')
            if not nxt or size >= 500:
                engine.reply(p['request_id'], choose(p, 'finish_case_review', reason='failure'))
                engine.execute_pending()
                break
            engine.reply(p['request_id'], choose(p, 'show_context_page', page_ref=nxt))
            engine.execute_pending()
        require(seen == tools.ids[:len(seen)] and len(set(seen)) == len(seen), 'Native rank/cursor mismatch')
        require(len(engine.state().candidates) == size, 'Canonical pool lost members')
        if size < 500:
            require(seen == tools.ids, 'Full traversal incomplete')
        results.append({'pool_size': size, 'canonical_count': len(engine.state().candidates),
            'shown_count': len(seen), 'pages': pages, 'peak_input_tokens': peak,
            'full_traversal': size < 500, 'elapsed_seconds': perf_counter() - start})
        print(json.dumps(results[-1]), flush=True)
    report = {'status': 'PASS', 'fixture': 'synthetic candidates; real pinned tokenizer and full CM2-CM3 catalog',
        'controller_inference_requests': 0, 'embedding_requests': 0, 'counter_binding': binding, 'results': results,
        'code_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
        'limitations': ['500 and 10000 sample the first page only.', 'No host memory/CPU bound or legal-semantic claim.']}
    write_once(output / 'report.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    run(args.root.resolve(), args.output_dir.resolve())


if __name__ == '__main__':
    main()
