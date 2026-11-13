"""One explicit cached-query attempt followed by source opening on shared state."""
import argparse
from contextlib import nullcontext
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
import traceback
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from pipeline_v2.sparse_bm25.index import SparseHybridSession
from pipeline_v2.full_search import hybrid as hybrid_module
from pipeline_v2.full_search.source_tools import SourceToolsSession
from pipeline_v2.source.core import digest


def replay_restored_diagnostic():
    evidence = ROOT / 'pipeline_v2/reviews/qdrant_restore_20261111_v1'
    receipt = json.loads((evidence / 'completion_receipt.json').read_bytes())
    filename = 'diagnostic_hybrid_stdout.json'
    raw = (evidence / filename).read_bytes()
    if receipt['status'] != 'PASS' or digest(raw) != receipt['evidence_sha256'][filename]:
        raise ValueError('Restored diagnostic evidence differs from its receipt')
    return json.loads(raw)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--diagnostic-timeout', type=int, choices=[300])
    mode.add_argument('--replay-restored-diagnostic', action='store_true')
    args = parser.parse_args()
    started = time.perf_counter()
    hybrid = tools = None
    record = {'status': 'STARTED', 'model_requests': 0,
              'cached_query_attempts': 0 if args.replay_restored_diagnostic else 1,
              'replayed_restored_diagnostic': args.replay_restored_diagnostic,
              'automatic_retries': 0, 'opened_cases': [],
              'qdrant_server_timeout_seconds': (None if args.replay_restored_diagnostic
                                                 else args.diagnostic_timeout or 120),
              'diagnostic_timeout_override': args.diagnostic_timeout is not None}
    try:
        hybrid = SparseHybridSession(ROOT)
        record['hybrid_session_open_seconds'] = time.perf_counter() - started
        t = time.perf_counter()
        tools = SourceToolsSession(ROOT, snapshot=hybrid.lexical)
        record['borrowed_source_tools_open_seconds'] = time.perf_counter() - t
        if args.replay_restored_diagnostic:
            response = replay_restored_diagnostic()
        else:
            print(json.dumps({'stage': 'cached_query', 'status': 'STARTED'}), flush=True)
            timeout_override = nullcontext()
            if args.diagnostic_timeout is not None:
                hybrid.db.timeout = args.diagnostic_timeout + 15
                timeout_override = patch.object(hybrid_module, 'SERVER_TIMEOUT_SECONDS',
                                                args.diagnostic_timeout)
            with timeout_override:
                response = hybrid.search_cached('standard of review', '095448.txt',
                                                '095448:88b488d43fde1389756a8dd7', 20)
        assert response['status'] == 'ok' and response['model_requests'] == 0
        assert len(response['hits']) == 20
        for hit in response['hits'][:3]:
            case = hit['case_id']
            assert case != '095448.txt'
            ids = sorted({lead['passage_id'] for lead in hit['channels'].values()
                          if 'passage_id' in lead})
            assert ids
            raw = (ROOT / 'data/task1_train_files_2026/cases' / case).read_bytes()
            page = tools.open_source(case, tools.sources[case], passage_ids=ids, byte_budget=4096)
            assert page['hit_refs'] and page['delivered_bytes'] > 0
            for fragment in page['fragments']:
                a, b = fragment['span_bytes']
                assert raw[a:b].decode('utf-8') == fragment['text']
                assert digest(raw[a:b]) == fragment['text_sha256']
            record['opened_cases'].append({
                'case_id': case, 'passage_ids': ids, 'source_hash': tools.sources[case],
                'requested_spans': page['requested_spans'],
                'delivered_spans': page['delivered_spans'],
                'pending_spans': page['pending_spans'], 'complete': page['complete'],
                'delivered_bytes': page['delivered_bytes']})
        tools.close()
        hybrid.lexical.guard()
        record.update(status='PASS', borrowed_snapshot_still_open='PASS',
                      cached_query_mode=response['execution_mode'], hybrid_hits=len(response['hits']),
                      hybrid_timings=response['timings'])
    except BaseException as exc:
        record.update(status='FAIL', error_type=type(exc).__name__, error=str(exc),
                      traceback=traceback.format_exc())
        response = getattr(exc, 'response', None)
        if response is not None:
            record['local_qdrant_error_body'] = response.text
    finally:
        if tools is not None:
            tools.close()
        if hybrid is not None:
            hybrid.close()
        record.update(elapsed_seconds=time.perf_counter() - started,
                      finished_utc=datetime.now(timezone.utc).isoformat())
        output = Path(__file__).with_name('hybrid_source_integration_' + str(time.time_ns()) + '.json')
        output.write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({'report': str(output), **record}), flush=True)
    return 0 if record['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
