"""Pilot-only orchestration. No labels, no full-corpus inference entry point."""
from collections import Counter
import heapq
import json
from pathlib import Path
import re
import time

import numpy as np

from ..passages import PinnedTokenizer
from ..source.core import canonical,digest
from ..source.store import contained,read_json
from .bm25 import BM25,fuse_case_ranks,rank_cases
from .cache import Cache,run_lock
from .common import M3Error,fingerprint,implementation,load_profile,write_json
from .corpus import Corpus
from .qdrant import QdrantStore
from .runtime import ModalEmbedder,call_embedding


def sample_passages(passages,size=1024,seed=20261106):
    """Hash-priority sample plus bounded risk representatives, one stream pass."""
    if type(size) is not int or size<1:raise M3Error("Invalid sample size")
    heap=[]; risk={}; seen=set()
    for p in passages:
        ident=p["passage_id"]
        if ident in seen:raise M3Error("Duplicate corpus passage ID")
        seen.add(ident)
        priority=int(digest(f"{seed}:{ident}".encode()),16)
        item=(-priority,ident,p)
        if len(heap)<size:heapq.heappush(heap,item)
        elif priority < -heap[0][0]:heapq.heapreplace(heap,item)
        tags=["tokens_"+str(min(448,p["full_input_tokens"]//64*64)),"role_"+str(p.get("paragraph_role")),"kind_"+p["unit_kind"]]
        if p["split_count"]>1:tags.append("split_"+("first" if p["split_order"]==0 else "last" if p["split_order"]==p["split_count"]-1 else "middle"))
        if any(ord(c)>127 for c in p["text"]):tags.append("unicode")
        if p.get("navigation_preview_count")==0:tags.append("no_preview")
        for tag in tags:
            if tag not in risk or priority<risk[tag][0]:risk[tag]=(priority,p)
    if len(seen)<size:raise M3Error("Corpus smaller than requested pilot")
    chosen={p["passage_id"]:p for _,p in sorted(risk.values(),key=lambda x:(x[0],x[1]["passage_id"]))[:size]}
    for _,ident,p in sorted(heap,key=lambda x:(-x[0],x[1])):
        if len(chosen)==size:break
        chosen.setdefault(ident,p)
    return sorted(chosen.values(),key=lambda p:p["passage_id"])


def plan_pilot(root,output):
    root=Path(root).resolve(); target=contained(root,output,"pipeline_v2/artifacts")
    if target.exists():raise M3Error("Pilot output exists; choose a new run directory")
    profile=load_profile(root); code=implementation(); corpus=Corpus(root,profile["passages_bundle"],profile["accepted_m2_seal_sha256"])
    passages=sample_passages(corpus.iter_passages(),profile["pilot_size"],profile["seed"])
    current=Corpus(root,profile["passages_bundle"],profile["accepted_m2_seal_sha256"])
    if corpus.seal_sha256!=current.seal_sha256 or profile!=load_profile(root) or code!=implementation():raise M3Error("Plan inputs changed while sampling")
    target.mkdir(parents=True,exist_ok=False)
    fp=fingerprint(profile)
    manifest={"schema_version":"pipeline-v2-m3-pilot-manifest-1","scope":"pilot_only","profile":profile,"implementation":code,
              "m2_seal_sha256":corpus.seal_sha256,"embedding_fingerprint":fp,"passage_ids":[p["passage_id"] for p in passages],
              "input_hashes":[p["exact_input_sha256"] for p in passages],"source_hashes":{p["case_id"]:p["source_hash"] for p in passages},
              "collection":profile["qdrant"]["collection_prefix"]+"_"+digest(canonical([fp,[p["passage_id"] for p in passages],target.name]))[:16],
              "selection":{"seed":profile["seed"],"method":"hash_priority_plus_risk_v1","strata_actual":{"split_children":sum(p["split_count"]>1 for p in passages),"unicode":sum(any(ord(c)>127 for c in p["text"]) for p in passages),"no_preview":sum(p.get("navigation_preview_count")==0 for p in passages)}},
              "labels_accessed":False,"test_sources_accessed":False,"model_requests":0,"pilot_executed":False}
    write_json(target/"pilot_manifest.json",manifest)
    write_json(target/"manifest.sha256.json",{"sha256":digest((target/"pilot_manifest.json").read_bytes())})
    return {"status":"planned_not_executed","run_dir":str(target),"passages":len(passages),"collection":manifest["collection"]}


def load_run(root,run_dir):
    root=Path(root).resolve(); run=contained(root,run_dir,"pipeline_v2/artifacts")
    manifest=read_json(run/"pilot_manifest.json")
    if read_json(run/"manifest.sha256.json")!={"sha256":digest((run/"pilot_manifest.json").read_bytes())}:raise M3Error("Pilot manifest drift")
    if manifest["profile"]!=load_profile(root) or manifest["implementation"]!=implementation():raise M3Error("M3 code/profile drift since plan")
    if manifest["scope"]!="pilot_only" or len(manifest["passage_ids"])!=manifest["profile"]["pilot_size"] or len(set(manifest["passage_ids"]))!=len(manifest["passage_ids"]):raise M3Error("Unexpected or duplicate pilot universe")
    corpus=Corpus(root,manifest["profile"]["passages_bundle"],manifest["profile"]["accepted_m2_seal_sha256"])
    if corpus.seal_sha256!=manifest["m2_seal_sha256"]:raise M3Error("M2 bundle drift since pilot plan")
    passages=corpus.selected(manifest["passage_ids"])
    if [p["exact_input_sha256"] for p in passages]!=manifest["input_hashes"] or {p["case_id"]:p["source_hash"] for p in passages}!=manifest["source_hashes"]:raise M3Error("Pilot source inputs drift")
    return root,run,manifest,corpus,passages


def resources(root,run,manifest,embedder=None,store=None):
    p=manifest["profile"]
    tok=PinnedTokenizer(root,"pipeline_v2/configs/qwen3_embedding_4b_tokenizer.lock.json")
    cache=Cache(run,manifest["embedding_fingerprint"],p["embedding"]["dimensions"])
    store=store or QdrantStore(p["qdrant"]["url"],manifest["collection"],manifest["embedding_fingerprint"],p["embedding"]["dimensions"])
    return tok,cache,embedder or ModalEmbedder(p),store


def preflight(root,run_dir,embedder=None):
    root,run,m,corpus,passages=load_run(root,run_dir)
    with run_lock(run):
        write_json(run/"preflight.json",{"status":"in_progress","embedding_fingerprint":m["embedding_fingerprint"],
                   "implementation":m["implementation"],"m2_seal_sha256":m["m2_seal_sha256"]},replace=True)
        q=m["profile"]["qdrant"]
        server=QdrantStore(q["url"],m["collection"],m["embedding_fingerprint"],m["profile"]["embedding"]["dimensions"])
        db_info=server.server_info()
        if db_info["version"]!=q["version"]:raise M3Error("Qdrant version differs from pinned pilot profile")
        server.ensure()
        tok,cache,emb,_=resources(root,run,m,embedder)
        texts=["hello", "\ufeff[1] \u00e9l\u00e9ment\r\n\u6cd5\U0001f9d1\u200d\u2696\ufe0f", "<|endoftext|> <|im_start|> <FRAGMENT_SUPPRESSED>","word "*446]
        batch,resp=call_embedding(emb,texts,"document",m["profile"],tok,m["implementation"],cache,"preflight-batch")
        deviations=[]
        for i,text in enumerate(texts):
            vec,_=call_embedding(emb,[text],"document",m["profile"],tok,m["implementation"],cache,"preflight-single-"+str(i))
            deviations.append(float(1-np.dot(vec[0],batch[i])))
        call_embedding(emb,["source relied on by a court"],"query",m["profile"],tok,m["implementation"],cache,"preflight-query")
        if max(deviations)>m["profile"]["numerics"]["batch_cosine_atol"]:raise M3Error("Singleton/batch pooling consistency failed")
        result={"status":"simulated" if embedder is not None else "PASS","embedding_fingerprint":m["embedding_fingerprint"],
                "implementation":m["implementation"],"m2_seal_sha256":m["m2_seal_sha256"],"descriptor":resp["descriptor"],"qdrant_server":db_info,"max_batch_cosine_deviation":max(deviations),"usage":cache.usage()}
        write_json(run/"preflight.json",result,replace=True)
        return result


def _batches(passages,profile):
    n=profile["batch_size"]
    return [passages[i:i+n] for i in range(0,len(passages),n)]


def run_pilot(root,run_dir,embedder=None,store=None,stop_after_batches=None):
    root,run,m,corpus,passages=load_run(root,run_dir)
    simulated=embedder is not None or store is not None
    with run_lock(run):
        pre=read_json(run/"preflight.json")
        if pre.get("embedding_fingerprint")!=m["embedding_fingerprint"] or pre.get("implementation")!=m["implementation"] or pre.get("m2_seal_sha256")!=m["m2_seal_sha256"] or (pre.get("status")!="PASS" and not simulated):raise M3Error("Matching real preflight is required before pilot")
        tok,cache,emb,db=resources(root,run,m,embedder,store)
        db.ensure(); completed=0
        started=time.perf_counter()
        for index,batch in enumerate(_batches(passages,m["profile"])):
            ids=[p["passage_id"] for p in batch]; hashes=[p["exact_input_sha256"] for p in batch]
            vectors=cache.get_batch(ids,hashes)
            if vectors is None:
                vectors,_=call_embedding(emb,[p["text"] for p in batch],"document",m["profile"],tok,m["implementation"],cache,f"documents-{index}")
                cache.commit_batch(ids,hashes,vectors)
            db.upsert(batch,vectors); completed+=1
            write_json(run/"progress.json",{"completed_batches":completed,"status":"partial","embedding_fingerprint":m["embedding_fingerprint"],"usage":cache.usage()},replace=True)
            if stop_after_batches is not None and completed>=stop_after_batches:
                return {"status":"stopped_at_batch_boundary","completed_batches":completed,"usage":cache.usage()}
        vectors=load_vectors(cache,passages,m["profile"])
        checked=db.verify(passages,vectors)
        result={"status":"simulated" if simulated else "vectors_ingested_verified_not_full_pilot_acceptance","passages":len(passages),"db_verification":checked,
                "elapsed_seconds":time.perf_counter()-started,"usage":cache.usage(),"remaining_checks":["search_reference","snapshot_restore","container_restart_persistence","independent_AG_tests"],"full_corpus_executed":False}
        write_json(run/"run_result.json",result,replace=True)
        return result


def load_vectors(cache,passages,profile):
    arrays=[]
    for batch in _batches(passages,profile):
        a=cache.get_batch([p["passage_id"] for p in batch],[p["exact_input_sha256"] for p in batch])
        if a is None:raise M3Error("Incomplete vector cache")
        arrays.append(a)
    return np.concatenate(arrays)


def verify_pilot(root,run_dir,store=None,restore=False):
    root,run,m,corpus,passages=load_run(root,run_dir)
    p=m["profile"]
    cache=Cache(run,m["embedding_fingerprint"],p["embedding"]["dimensions"])
    vectors=load_vectors(cache,passages,p)
    db=store or QdrantStore(p["qdrant"]["url"],m["collection"],m["embedding_fingerprint"],p["embedding"]["dimensions"])
    checked=db.verify(passages,vectors)
    comparisons=[]
    for i in sorted({0,len(passages)//2,len(passages)-1}):
        excluded=passages[i]["case_id"]
        scores=vectors@vectors[i]
        valid=[j for j,pas in enumerate(passages) if pas["case_id"]!=excluded]
        expected=sorted(valid,key=lambda j:(-float(scores[j]),passages[j]["passage_id"]))[:10]
        hits=db.search(vectors[i],10,excluded)
        if len(hits)!=len(expected):raise M3Error("Dense reference count mismatch")
        byid={pas["passage_id"]:j for j,pas in enumerate(passages)}
        if any(h["passage_id"] not in byid or h["case_id"]==excluded for h in hits):raise M3Error("Dense search scope mismatch")
        if len({h["passage_id"] for h in hits})!=len(hits):raise M3Error("Dense search returned duplicate IDs")
        threshold=float(scores[expected[-1]]) if expected else 0
        required={passages[j]["passage_id"] for j in valid if float(scores[j])>threshold+p["numerics"]["search_score_atol"]}
        if not required.issubset({h["passage_id"] for h in hits}):raise M3Error("Dense search missed an untied top-k result")
        for h in hits:
            actual=float(scores[byid[h["passage_id"]]])
            if abs(actual-h["score"])>p["numerics"]["search_score_atol"] or actual<threshold-p["numerics"]["search_score_atol"]:raise M3Error("Dense search differs from exact cosine reference")
        comparisons.append({"query_passage":passages[i]["passage_id"],"exclude_case":excluded,"hits":len(hits),"tie_aware":"PASS"})
    recovery=None
    if restore:
        restored,recovery=db.restore_test()
        recovery["verification"]=restored.verify(passages,vectors)
    result={"status":"simulated" if store is not None else "PASS_local_DB_reference_scope_only","db":checked,"exact_reference":comparisons,"snapshot_restore":recovery,
            "restart_persistence":"must_run_verify_again_after_user_or_AG_container_restart","full_corpus_executed":False}
    write_json(run/"verification.json",result,replace=True)
    return result


def search_pilot(root,run_dir,query,query_case=None,limit=10,embedder=None,store=None):
    root,run,m,corpus,passages=load_run(root,run_dir)
    if type(limit) is not int or not 1<=limit<=100:raise M3Error("Invalid search limit")
    with run_lock(run):
        pre=read_json(run/"preflight.json")
        if pre.get("embedding_fingerprint")!=m["embedding_fingerprint"] or pre.get("implementation")!=m["implementation"] or pre.get("m2_seal_sha256")!=m["m2_seal_sha256"] or (pre.get("status")!="PASS" and embedder is None):raise M3Error("Matching preflight required before search")
        cache_check=Cache(run,m["embedding_fingerprint"],m["profile"]["embedding"]["dimensions"])
        cached_vectors=load_vectors(cache_check,passages,m["profile"])
        tok,cache,emb,db=resources(root,run,m,embedder,store)
        db.verify(passages,cached_vectors)
        vector,_=call_embedding(emb,[query],"query",m["profile"],tok,m["implementation"],cache,"search-query")
        scan=m["profile"]["fusion"]["scan_cap"]
        dense=db.search(vector[0],scan,query_case)
        bm=BM25(passages,**{k:m["profile"]["bm25"][k] for k in ("k1","b")})
        cases=[]
        for case_id in sorted({p["case_id"] for p in passages}):
            raw,_=corpus.reader.nav.source._source(case_id)
            cases.append({"case_id":case_id,"text":raw.decode("utf-8"),"source_hash":digest(raw)})
        case_hits=BM25(cases,**{k:m["profile"]["bm25"][k] for k in ("k1","b")}).search(query,scan,query_case)
        passage_hits=bm.search(query,scan,query_case)
        channels={"case_bm25":case_hits,"passage_bm25":passage_hits,"dense_passage":dense}
        return {"scope":"pilot_cases_and_passages_only","execution_mode":"simulated" if embedder is not None or store is not None else "real_remote_model_and_local_Qdrant","case_bm25_body":"whole_raw_selected_cases","query_case_excluded":query_case,
                "results":fuse_case_ranks(channels,limit,m["profile"]["fusion"]["k"]),
                "channels":{name:rank_cases(hits,limit) for name,hits in channels.items()},"must_open_before_citing":True,"usage":cache.usage()}


def literal_search(root,run_dir,text,case_sensitive=True):
    root,run,m,corpus,passages=load_run(root,run_dir)
    if not text:raise M3Error("Empty literal search")
    results=[]
    for case_id in sorted({p["case_id"] for p in passages}):
        raw,_=corpus.reader.nav.source._source(case_id); decoded=raw.decode("utf-8")
        for match in re.finditer(re.escape(text),decoded,0 if case_sensitive else re.IGNORECASE):
            a=len(decoded[:match.start()].encode("utf-8")); b=len(decoded[:match.end()].encode("utf-8"))
            results.append({"case_id":case_id,"source_hash":digest(raw),"span_bytes":[a,b],"text":raw[a:b].decode("utf-8")})
    return {"scope":"whole_raw_selected_pilot_cases","matches":results,"normalized_text_is_not_quote_source":True}
