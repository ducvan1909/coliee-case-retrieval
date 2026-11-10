"""Deterministic full plan and resumable bounded-memory document ingestion."""
from collections import OrderedDict
from pathlib import Path
import json
import math
import sqlite3
import time

from ..optimization_v2.index import PersistentBM25
from ..optimization_v2.runtime import OptModalEmbedder,request_embedding
from ..optimization_v2.common import implementation as opt_implementation
from ..retrieval.cache import run_lock
from ..retrieval.corpus import Corpus
from ..passages import PinnedTokenizer
from ..source.core import canonical,digest
from .common import artifact,compatibility,file_digest,fingerprint,implementation,load_profile,read,seal,validate_seal,write_json,M3Error
from .storage import FullCache,ReadonlyCache,FullQdrant

def source_path(root,case):
    if not isinstance(case,str) or len(case)!=10 or not case[:6].isdigit() or case[6:]!='.txt':raise M3Error('Unsafe case ID')
    return Path(root)/'data/task1_train_files_2026/cases'/case

def plan_full(root,output):
    root=Path(root).resolve();target=artifact(root,output)
    if target.exists():raise M3Error('Full plan output exists; select a new directory')
    started=time.perf_counter();profile=load_profile(root);code=implementation();binding=compatibility(root,profile)
    corpus=Corpus(root,profile['passages_bundle'],profile['accepted_m2_seal_sha256'])
    sources={case:row['source_hash'] for case,row in corpus.reader.rows.items()}
    if len(sources)!=profile['expected_cases']:raise M3Error('Full case count differs')
    def cases():
        for case,expected in sorted(sources.items()):
            raw=source_path(root,case).read_bytes()
            if digest(raw)!=expected:raise M3Error('Source changed during full planning')
            yield {'case_id':case,'source_hash':expected,'text':raw.decode('utf-8')}
    def passages():
        for p in corpus.iter_passages():
            if type(p['full_input_tokens']) is not int or not 1<=p['full_input_tokens']<=448:raise M3Error('Passage token cap differs')
            yield p
    target.mkdir(parents=True,exist_ok=False)
    lexical=PersistentBM25.create(target/'lexical.sqlite3',{'case':cases(),'passage':passages()},profile['bm25']['k1'],profile['bm25']['b']);lexical.close()
    db=sqlite3.connect(target/'lexical.sqlite3')
    try:
        count=db.execute("SELECT COUNT(*) FROM documents WHERE kind='passage'").fetchone()[0]
        if count!=profile['expected_passages']:raise M3Error('Full passage count differs')
        db.execute('CREATE TABLE schedule(ordinal INTEGER PRIMARY KEY,passage_id TEXT UNIQUE NOT NULL,batch INTEGER NOT NULL)')
        ids=db.execute("SELECT id FROM documents WHERE kind='passage' ORDER BY CAST(json_extract(metadata,'$.full_input_tokens') AS INTEGER),id")
        with db:
            for ordinal,(ident,) in enumerate(ids):db.execute('INSERT INTO schedule VALUES(?,?,?)',(ordinal,ident,ordinal//profile['batch_size']))
            db.execute('CREATE INDEX schedule_batch ON schedule(batch,ordinal)')
    finally:db.close()
    manifest={'schema_version':'pipeline-v2-m3-full-manifest-1','scope':'all_train_passages','profile':profile,'implementation':code,
              'compatibility':binding,'embedding_fingerprint':fingerprint(profile),'source_hashes':sources,
              'passages':count,'cases':len(sources),'batches':math.ceil(count/profile['batch_size']),
              'batching':'ascending_full_input_tokens_then_passage_id_contiguous64',
              'collection':profile['qdrant']['collection_prefix']+digest(canonical([fingerprint(profile),target.name,code]))[:16],
              'labels_accessed':False,'test_sources_accessed':False,'model_requests':0,'planned_only':True}
    if code!=implementation() or profile!=load_profile(root) or binding!=compatibility(root,profile):raise M3Error('Plan dependencies changed')
    # A plan with no final seal is incomplete and cannot be executed.
    write_json(target/'manifest.json',manifest)
    write_json(target/'seal.json',seal(target,['manifest.json','lexical.sqlite3']))
    return {'status':'planned_local_no_inference','passages':count,'cases':len(sources),'batches':manifest['batches'],
            'collection':manifest['collection'],'elapsed_seconds':time.perf_counter()-started,'model_requests':0}

def load_plan(root,run_dir):
    root=Path(root).resolve();run=artifact(root,run_dir);validate_seal(run);m=read(run/'manifest.json')
    p=load_profile(root)
    if m.get('schema_version')!='pipeline-v2-m3-full-manifest-1' or m.get('scope')!='all_train_passages' or m['profile']!=p or m['implementation']!=implementation():raise M3Error('Full run code/profile/manifest drift')
    if m['embedding_fingerprint']!=fingerprint(p) or m['compatibility']!=compatibility(root,p):raise M3Error('Full compatibility drift')
    corpus=Corpus(root,p['passages_bundle'],p['accepted_m2_seal_sha256'])
    sources={case:row['source_hash'] for case,row in corpus.reader.rows.items()}
    if sources!=m['source_hashes'] or len(sources)!=p['expected_cases'] or m['passages']!=p['expected_passages']:raise M3Error('Full source scope differs')
    for case,expected in sources.items():
        if file_digest(source_path(root,case))!=expected:raise M3Error('Full raw source drift')
    lexical=PersistentBM25(run/'lexical.sqlite3')
    counts=lexical.db.execute('SELECT COUNT(*),COUNT(DISTINCT passage_id),MAX(batch) FROM schedule').fetchone()
    if counts!=(m['passages'],m['passages'],m['batches']-1):
        lexical.close();raise M3Error('Invalid full schedule')
    return root,run,m,lexical

def batches(lexical):
    current=[];batch=None
    for number,ident in lexical.db.execute('SELECT batch,passage_id FROM schedule ORDER BY ordinal'):
        if current and number!=batch:
            yield batch,lexical.get_many('passage',current);current=[]
        batch=number;current.append(ident)
    if current:yield batch,lexical.get_many('passage',current)

class RawReader:
    def __init__(self,root,sources,max_cases=8):self.root=root;self.sources=sources;self.cache=OrderedDict();self.max_cases=max_cases
    def text(self,p):
        case=p['case_id']
        if case not in self.cache:
            raw=source_path(self.root,case).read_bytes()
            if digest(raw)!=self.sources[case] or p['source_hash']!=self.sources[case]:raise M3Error('Source drift before embedding')
            self.cache[case]=raw
            if len(self.cache)>self.max_cases:self.cache.popitem(last=False)
        else:self.cache.move_to_end(case)
        raw=self.cache[case][slice(*p['span_bytes'])]
        if digest(raw)!=p['exact_input_sha256']:raise M3Error('Passage input hash drift')
        return raw.decode('utf-8')

def make_store(m):
    q=m['profile']['qdrant'];return FullQdrant(q['url'],m['collection'],m['embedding_fingerprint'],m['profile']['embedding']['dimensions'],timeout=q['timeout_seconds'])

def guard(root,m):
    if m['profile']!=load_profile(root) or m['implementation']!=implementation():raise M3Error('Full code/profile changed during run')

def execution_state(run,m,mode):
    return {'schema_version':'pipeline-v2-m3-full-execution-1','execution_mode':mode,
            'manifest_sha256':file_digest(run/'manifest.json'),'embedding_fingerprint':m['embedding_fingerprint']}

def verify_batches(lexical,cache,store,m):
    store.check_schema()
    if store.count()!=m['passages']:raise M3Error('Full DB count differs from exact scope')
    count=0
    for number,docs in batches(lexical):
        vectors=cache.get_batch([p['passage_id'] for p in docs],[p['exact_input_sha256'] for p in docs])
        if vectors is None:raise M3Error('Full cache incomplete')
        if not store.matches(docs,vectors):raise M3Error('Missing expected full DB points')
        count+=len(docs)
    if count!=m['passages'] or store.count()!=count:raise M3Error('Full DB changed during verify')
    return {'status':'PASS','points':count,'collection':m['collection'],'method':'all_expected_unique_ids_payload_vectors_plus_exact_count_batched64'}

def run_full(root,run_dir,embedder=None,store=None,max_batches=None):
    """Stop after max_batches needing upsert, including cached DB repairs.

    Already cached and DB-matching batches do not consume the limit. A remote
    failure stops immediately; retry is an explicit new invocation with every
    prior attempt retained in the ledger. Both injections are required for tests.
    """
    if max_batches is not None and (type(max_batches) is not int or max_batches<1):raise M3Error('max_batches must be positive')
    if (embedder is None)!=(store is None):raise M3Error('Simulation requires both embedder and store injections; mixed real/simulated execution is forbidden')
    root,run,m,lexical=load_plan(root,run_dir);simulated=embedder is not None or store is not None
    lock=run_lock(run);acquired=False
    cache=None;started=time.perf_counter();result={'status':'running','execution_mode':'simulated' if simulated else 'real_modal','batches_processed_this_run':0,'new_inference_batches':0,'cached_batches':0}
    try:
        lock.__enter__();acquired=True
        mode='simulated' if simulated else 'real_modal'
        state=execution_state(run,m,mode);state_path=run/'execution_state.json'
        if state_path.exists():
            if read(state_path)!=state:raise M3Error('Cannot change full run execution identity or simulated/real mode')
        else:
            if any((run/name).exists() for name in ('ledger.sqlite3','vectors','run_result.json','progress.json')):raise M3Error('Execution state missing from an existing runtime; refuse cache adoption')
            write_json(state_path,state)
        cache=FullCache(run,m['embedding_fingerprint'],m['profile']['embedding']['dimensions'])
        cache.db.execute('CREATE TABLE IF NOT EXISTS full_batches(batch INTEGER PRIMARY KEY,committed INTEGER NOT NULL)');cache.db.commit()
        db=store or make_store(m)
        if db.server_info()['version']!=m['profile']['qdrant']['version']:raise M3Error('Qdrant version differs')
        db.ensure()
        if hasattr(db,'validate_existing'):db.validate_existing(lexical)
        if db.count()>m['passages']:raise M3Error('Unexpected full DB membership count')
        tok=PinnedTokenizer(root,'pipeline_v2/configs/qwen3_embedding_4b_tokenizer.lock.json');raw=RawReader(root,m['source_hashes']);remote=embedder
        for number,docs in batches(lexical):
            ids=[p['passage_id'] for p in docs];hashes=[p['exact_input_sha256'] for p in docs]
            committed=cache.db.execute('SELECT committed FROM full_batches WHERE batch=?',(number,)).fetchone()
            vectors=(ReadonlyCache(run,m['embedding_fingerprint'],m['profile']['embedding']['dimensions']).get_batch(ids,hashes)
                     if committed else cache.get_batch(ids,hashes))
            if vectors is None and committed:raise M3Error('Committed cache shard is missing; refuse re-inference')
            if vectors is not None and db.matches(docs,vectors):
                with cache.db:cache.db.execute('INSERT OR REPLACE INTO full_batches VALUES(?,1)',(number,))
                result['cached_batches']+=1;continue
            if vectors is None:
                texts=[raw.text(p) for p in docs]
                guard(root,m)
                if remote is None:remote=OptModalEmbedder(m['profile'])
                vectors,_=request_embedding(remote,texts,'document',m['profile'],tok,opt_implementation(),cache,f'full-documents-{number}')
                guard(root,m)
                cache.commit_batch(ids,hashes,vectors)
                result['new_inference_batches']+=1
            else:result['cached_batches']+=1
            with cache.db:cache.db.execute('INSERT OR REPLACE INTO full_batches VALUES(?,1)',(number,))
            db.upsert(docs,vectors)
            result['batches_processed_this_run']+=1
            result.update(status='partial',usage=cache.usage(),last_batch=number)
            write_json(run/'progress.json',result,replace=True)
            if max_batches is not None and result['batches_processed_this_run']>=max_batches:
                result['status']='simulated_partial' if simulated else 'stopped_at_batch_boundary';return result
        checked=verify_batches(lexical,cache,db,m)
        result.update(status='simulated' if simulated else 'full_vectors_ingested_verified',verification=checked)
        return result
    except BaseException as exc:
        result.update(status='interrupted_partial' if isinstance(exc,(KeyboardInterrupt,SystemExit)) else 'failed_partial',error_type=type(exc).__name__);raise
    finally:
        try:
            result['elapsed_seconds']=time.perf_counter()-started
            if cache is not None:
                result['usage']=cache.usage()
                write_json(run/'invocations'/f'{time.time_ns()}.json',result)
                write_json(run/'run_result.json',result,replace=True)
        finally:
            if cache is not None:cache.db.close()
            lexical.close()
            if acquired:lock.__exit__(None,None,None)

def verify_full(root,run_dir,store=None):
    root,run,m,lexical=load_plan(root,run_dir)
    try:
        mode='simulated' if store is not None else 'real_modal'
        if not (run/'execution_state.json').exists() or read(run/'execution_state.json')!=execution_state(run,m,mode):raise M3Error('Verification execution identity missing or differs')
        cache=ReadonlyCache(run,m['embedding_fingerprint'],m['profile']['embedding']['dimensions'])
        result=verify_batches(lexical,cache,store or make_store(m),m)
        result['execution_mode']='simulated' if store is not None else 'real_local_DB';return result
    finally:lexical.close()

def status_full(root,run_dir):
    root,run,m,lexical=load_plan(root,run_dir)
    try:
        result={'status':'planned','passages':m['passages'],'batches':m['batches'],'collection':m['collection'],'model_requests':0}
        if (run/'run_result.json').exists():
            result['last_run']=read(run/'run_result.json');result['status']=result['last_run']['status']
        snapshots=[run/name for name in ('run_result.json','progress.json') if (run/name).exists()]
        if snapshots:
            latest=max(snapshots,key=lambda path:path.stat().st_mtime_ns)
            result['latest_checkpoint']=read(latest);result['latest_checkpoint_file']=latest.name
            result['status']=result['latest_checkpoint']['status']
        result['database_reverified']=False
        result['active_run_proven']=False
        path=run/'ledger.sqlite3'
        if path.exists():
            db=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
            try:
                row=db.execute('SELECT COUNT(*),COALESCE(SUM(tokens),0),SUM(tokens IS NULL) FROM attempts').fetchone()
                result.update(model_requests=row[0],known_input_tokens=row[1],unknown_token_attempts=row[2] or 0,status_counts=dict(db.execute('SELECT status,COUNT(*) FROM attempts GROUP BY status')))
            finally:db.close()
        return result
    finally:lexical.close()

def open_full(root,run_dir,passage_id):
    root,run,m,lexical=load_plan(root,run_dir)
    try:
        p=lexical.get_many('passage',[passage_id])[0]
        RawReader(root,m['source_hashes']).text(p)
        from ..passages import PassageReader
        return PassageReader(root,m['profile']['passages_bundle']).open_context(p['case_id'],passage_id)
    finally:lexical.close()
