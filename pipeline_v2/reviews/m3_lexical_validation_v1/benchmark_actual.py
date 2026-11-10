"""Readonly full workload parity vs independent scalar no-JOIN BM25."""
from collections import defaultdict
import json
import math
from pathlib import Path
import random
import re
import sqlite3
import statistics
import time

ROOT=Path(__file__).resolve().parents[3]
HERE=Path(__file__).resolve().parent


def scalar(db,maps,query,kind,exclude,limit=4096):
    scores=defaultdict(float)
    n,avg,k1,b=db.execute('SELECT n,avg,k1,b FROM stats WHERE kind=?',(kind,)).fetchone()
    for term in sorted(set(re.findall(r'\w+',query.casefold(),re.UNICODE))):
        row=db.execute('SELECT df FROM terms WHERE kind=? AND term=?',(kind,term)).fetchone()
        if row is None:continue
        idf=math.log(1+(n-row[0]+.5)/(row[0]+.5))
        cursor=db.execute('SELECT id,tf FROM postings WHERE kind=? AND term=?',(kind,term))
        while True:
            rows=cursor.fetchmany(4096)
            if not rows:break
            for ident,tf in rows:
                case,length=maps[kind][ident]
                if case==exclude:continue
                scores[ident]+=idf*tf*(k1+1)/(tf+k1*(1-b+b*length/(avg or 1)))
    return sorted(scores.items(),key=lambda p:(-p[1],p[0]))[:limit]


def main():
    from pipeline_v2.full_search.lexical import LexicalSession,implementation
    from pipeline_v2.source.core import canonical,digest
    run='pipeline_v2/artifacts/m3_full_train_20261108_v1'
    manifest=json.loads((ROOT/'pipeline_v2/reviews/m3_search_latency_diagnostic_v1/workload_manifest.json').read_bytes())
    started=time.perf_counter();session=LexicalSession(ROOT,run)
    startup=time.perf_counter()-started
    db=sqlite3.connect((ROOT/run/'lexical.sqlite3').as_uri()+'?mode=ro',uri=True)
    # Identical SQLite settings for current reader and scalar comparator.
    profile=json.loads((ROOT/'pipeline_v2/configs/m3_lexical.json').read_bytes())
    db.execute('PRAGMA query_only=ON')
    db.execute('PRAGMA cache_size=-131072');db.execute('PRAGMA mmap_size=536870912')
    t=time.perf_counter()
    maps={kind:{i:(case,length) for i,case,length in db.execute('SELECT id,case_id,length FROM documents WHERE kind=?',(kind,))} for kind in ('case','passage')}
    ref_preload=time.perf_counter()-t
    result={'status':'running','startup_seconds':startup,'scalar_preload_seconds':ref_preload,
            'scope':'same_exposed_AG_workload_local_readonly_no_RPC','configuration':profile,
            'implementation_sha256':digest(canonical(implementation())),'rows':[]}
    try:
        for kind in ('case','passage'):
            for q in manifest['queries']:
                timings={};expected=actual=None
                order=['scalar','vectorized'];random.Random(20261109+q['ordinal']).shuffle(order)
                for method in order:
                    t=time.perf_counter()
                    if method=='scalar':expected=scalar(db,maps,q['text'],kind,q['query_case'])
                    else:
                        response=session.search(q['text'],kind,4096,q['query_case'])
                        hits=response['hits']
                        actual=[(h.get('passage_id',h['case_id']),h['score']) for h in hits]
                    timings[method]=time.perf_counter()-t
                assert [i for i,s in actual]==[i for i,s in expected],(q['query_id'],kind,'ranked_IDs_differ')
                deviation=max((abs(a[1]-e[1]) for a,e in zip(actual,expected)),default=0)
                assert all(math.isclose(a[1],e[1],abs_tol=1e-10,rel_tol=1e-10) for a,e in zip(actual,expected))
                t=time.perf_counter();response=session.search(q['text'],kind,4096,q['query_case']);repeat=time.perf_counter()-t
                assert [(h.get('passage_id',h['case_id']),h['score']) for h in response['hits']]==actual
                row={'query_id':q['query_id'],'kind':kind,'execution_order':order,'seconds':timings,
                     'vectorized_repeat_seconds':repeat,'ranked_ids_exact':True,'hits':len(actual),'max_abs_score_diff':deviation}
                result['rows'].append(row)
                (HERE/'actual_benchmark_progress.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
                print(json.dumps(row),flush=True)
        result['status']='PASS_actual_full_workload_rank_score_parity'
        result['summary']={kind:{'scalar_median_seconds':statistics.median(r['seconds']['scalar'] for r in result['rows'] if r['kind']==kind),
                                 'vectorized_median_seconds':statistics.median(r['seconds']['vectorized'] for r in result['rows'] if r['kind']==kind),
                                 'vectorized_repeat_median_seconds':statistics.median(r['vectorized_repeat_seconds'] for r in result['rows'] if r['kind']==kind)} for kind in ('case','passage')}
        assert digest(canonical(implementation()))==result['implementation_sha256']
    finally:
        db.close();session.close();result['elapsed_seconds']=time.perf_counter()-started
        with (HERE/'actual_benchmark.json').open('x',encoding='utf-8') as f:json.dump(result,f,indent=2)
    print(json.dumps(result.get('summary',{})))


if __name__=='__main__':main()
