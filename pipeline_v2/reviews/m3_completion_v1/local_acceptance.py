"""Bounded real-source acceptance for the new M3 tools, without model calls."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from pipeline_v2.full_search.source_tools import SourceToolsSession
from pipeline_v2.source.core import digest


def union(spans):
    merged = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def check_fragments(page, raw):
    assert page['delivered_bytes'] <= page['byte_budget']
    assert page['M4_delivery_recorded'] is False
    assert page['token_safe_agent_payload'] is False
    assert page['delivered_spans'] == union(page['delivered_spans'])
    assert sum(b - a for a, b in page['delivered_spans']) == page['delivered_bytes']
    for fragment in page['fragments']:
        a, b = fragment['span_bytes']
        assert raw[a:b].decode('utf-8') == fragment['text']
        assert digest(raw[a:b]) == fragment['text_sha256']


def main():
    started = time.perf_counter()
    record = {'status': 'STARTED', 'model_requests': 0, 'phases': {}}
    session = None
    output = Path(__file__).with_name('local_acceptance_' + str(time.time_ns()) + '.json')
    try:
        session = SourceToolsSession(ROOT)
        record['session_open_seconds'] = time.perf_counter() - started
        record['snapshot_sha256'] = session.snapshot_sha256
        print(json.dumps({'stage': 'session_open', 'seconds': record['session_open_seconds']}), flush=True)
        case = '095448.txt'
        raw = (ROOT / 'data/task1_train_files_2026/cases' / case).read_bytes()
        t = time.perf_counter()
        mapped = session.case_map(case, limit=3)
        anchors = session.case_anchors(case, source=True, limit=5)
        lexical = session.search_case(case, 'standard of review', limit=5)
        assert mapped['items'] and lexical['hits']
        for hit in lexical['hits']:
            a, b = hit['span_bytes']
            assert digest(raw[a:b]) == hit['exact_input_sha256']
        cursor, spans = None, []
        while True:
            response = session.search_phrase('Federal Court', case_id=case, limit=1, cursor=cursor)
            for hit in response['hits']:
                a, b = hit['span_bytes']
                assert raw[a:b] == b'Federal Court'
                spans.append([a, b])
            cursor = response['next_cursor']
            if cursor is None:
                break
        expected, position = [], 0
        while True:
            position = raw.find(b'Federal Court', position)
            if position < 0:
                break
            expected.append([position, position + len(b'Federal Court')])
            position += 1
        assert spans == expected
        identity = session.search_identity('Federal Court', case_id=case, limit=5)
        assert identity['hits']
        assert all(h['identity_status'] == 'observed_not_identity_verified' for h in identity['hits'])
        empty = session.search_phrase('M3_SOURCE_TOOLS_NO_MATCH_20261111', case_scan_limit=2)
        assert not empty['hits'] and not empty['exhausted'] and empty['next_cursor']
        resumed = session.search_phrase('M3_SOURCE_TOOLS_NO_MATCH_20261111', case_scan_limit=3,
                                        cursor=empty['next_cursor'])
        assert not resumed['hits'] and resumed['coverage']['next_case_index'] == 5
        record['phases']['query_tools'] = {
            'status': 'PASS', 'seconds': time.perf_counter() - t,
            'case_map_total': mapped['total'], 'source_anchors_total': anchors['total'],
            'lexical_hits': len(lexical['hits']), 'phrase_matches_all_pages': len(spans),
            'identity_hits': len(identity['hits']), 'no_hit_corpus_cases_scanned': 5}
        for case, handle in (('041666.txt', 'p000417'), ('055641.txt', 'p000351')):
            t = time.perf_counter()
            raw = (ROOT / 'data/task1_train_files_2026/cases' / case).read_bytes()
            passages = json.loads((session.passages_bundle / f'sources/{case[:-4]}.json').read_bytes())
            nav = json.loads((session.navigation_bundle / f'sources/{case[:-4]}.json').read_bytes())
            m1 = json.loads((session.m1_bundle / f'sources/{case[:-4]}.json').read_bytes())
            rows = {r['handle']: r for r in nav['navigation']}
            parent = rows[handle]
            children = sorted((p for p in passages['passages'] if p['parent_handle'] == handle),
                              key=lambda p: p['span_bytes'])
            child = children[len(children) // 2]
            refs = parent['reading_expansion']
            window = [rows[refs[key]]['span_bytes'] for key in ('previous_ref', 'parent_ref', 'next_ref')
                      if refs[key] is not None]
            expected = [[min(a for a, b in window), max(b for a, b in window)]]
            originals = {u['unit_id']: u for u in m1['units']}
            cursor, delivered, page_count, delivered_bytes = None, [], 0, 0
            while True:
                page = session.open_source(case, session.sources[case], passage_ids=[child['passage_id']],
                                           byte_budget=4096, cursor=cursor)
                check_fragments(page, raw)
                assert page['requested_spans'] == expected
                for component in page['components']:
                    original = originals.get(component.get('unit_id'))
                    if original is not None:
                        for field in ('unit_kind', 'language_region', 'observed_marker', 'order'):
                            assert component[field] == original[field]
                if page_count == 0 and len(children) > 2:
                    parent_pending = [[max(a, parent['span_bytes'][0]), min(b, parent['span_bytes'][1])]
                                      for a, b in page['pending_spans']
                                      if max(a, parent['span_bytes'][0]) < min(b, parent['span_bytes'][1])]
                    assert len(parent_pending) == 2
                delivered.extend(page['delivered_spans'])
                delivered_bytes += page['delivered_bytes']
                page_count += 1
                assert page_count < 100
                cursor = page['next_cursor']
                if cursor is None:
                    assert page['complete'] and not page['pending_spans']
                    break
            assert union(delivered) == expected
            assert delivered_bytes == sum(b - a for a, b in expected)
            record['phases'][case + ':' + handle] = {
                'status': 'PASS', 'seconds': time.perf_counter() - t,
                'pages': page_count, 'bytes': delivered_bytes,
                'passage_id': child['passage_id'], 'requested_spans': expected}
            print(json.dumps({'stage': case, **record['phases'][case + ':' + handle]}), flush=True)
        record['status'] = 'PASS'
    except BaseException as exc:
        record.update(status='FAIL', error_type=type(exc).__name__, error=str(exc),
                      traceback=traceback.format_exc())
    finally:
        if session is not None:
            session.close()
        record['elapsed_seconds'] = time.perf_counter() - started
        record['finished_utc'] = datetime.now(timezone.utc).isoformat()
        output.write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({'report': str(output), **record}), flush=True)
    return 0 if record['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
