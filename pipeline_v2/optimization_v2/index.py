"""Text-free metadata, streamed lexical postings and immutable read sessions."""
from collections import Counter, defaultdict
import json
import math
import re
from pathlib import Path
import sqlite3
import time

import numpy as np

from ..optimization.index import readonly_vectors, upstream_fingerprints
from ..retrieval.bm25 import analyze, fuse_case_ranks, rank_cases
from ..retrieval.cache import validate_vectors
from ..retrieval.common import implementation as baseline_implementation
from ..retrieval.pilot import load_run
from ..retrieval.qdrant import QdrantStore
from ..source.core import canonical, digest
from .common import M3Error, artifact, file_digest, implementation, load_profile, read, seal, validate_seal, write_json


class PersistentBM25:
    """No source text in metadata; one Counter at a time during creation."""
    def __init__(self,path,readonly=True):
        self.path=Path(path).resolve()
        self.db=sqlite3.connect(self.path.as_uri()+"?mode=ro",uri=True) if readonly else sqlite3.connect(self.path)

    @staticmethod
    def create(path,channels,k1=1.5,b=.75):
        path=Path(path).resolve()
        if path.exists():raise M3Error("Lexical index already exists")
        if not math.isfinite(k1) or k1<=0 or not math.isfinite(b) or not 0<=b<=1:raise M3Error("Invalid BM25 parameters")
        path.parent.mkdir(parents=True,exist_ok=True)
        db=sqlite3.connect(path)
        try:
            db.executescript("CREATE TABLE documents(kind TEXT,id TEXT,case_id TEXT,length INTEGER,metadata TEXT,PRIMARY KEY(kind,id));"
                             "CREATE TABLE postings(kind TEXT,term TEXT,id TEXT,tf INTEGER,PRIMARY KEY(kind,term,id));"
                             "CREATE TABLE stats(kind TEXT PRIMARY KEY,n INTEGER,avg REAL,k1 REAL,b REAL);"
                             "CREATE TABLE terms(kind TEXT,term TEXT,df INTEGER,PRIMARY KEY(kind,term));")
            with db:
                for kind,documents in channels.items():
                    count=total=0
                    for doc in documents:
                        terms=Counter(analyze(doc["text"]))
                        length=sum(terms.values());ident=doc.get("passage_id",doc["case_id"])
                        metadata={k:v for k,v in doc.items() if k!="text"}
                        db.execute("INSERT INTO documents VALUES(?,?,?,?,?)",(kind,ident,doc["case_id"],length,json.dumps(metadata,ensure_ascii=False)))
                        # Bounded parameter batches, no corpus-wide list of Counters.
                        pending=[]
                        for term,tf in terms.items():
                            pending.append((kind,term,ident,tf))
                            if len(pending)==512:
                                db.executemany("INSERT INTO postings VALUES(?,?,?,?)",pending);pending.clear()
                        if pending:db.executemany("INSERT INTO postings VALUES(?,?,?,?)",pending)
                        count+=1;total+=length
                    db.execute("INSERT INTO stats VALUES(?,?,?,?,?)",(kind,count,total/count if count else 1,k1,b))
                    db.execute("INSERT INTO terms SELECT kind,term,COUNT(*) FROM postings WHERE kind=? GROUP BY kind,term",(kind,))
        finally:db.close()
        return PersistentBM25(path)

    def get_many(self,kind,ids):
        ids=list(ids);found={}
        for offset in range(0,len(ids),256):
            block=ids[offset:offset+256]
            if not block:continue
            query="SELECT id,metadata FROM documents WHERE kind=? AND id IN ("+",".join("?" for _ in block)+")"
            found.update((ident,json.loads(meta)) for ident,meta in self.db.execute(query,[kind,*block]))
        if set(found)!=set(ids):raise M3Error("Missing lexical document metadata")
        return [found[i] for i in ids]

    def search(self,query,kind,limit=1024,exclude_case=None):
        if not isinstance(query,str) or type(limit) is not int or limit<1:raise M3Error("Invalid lexical query/limit")
        stats=self.db.execute("SELECT n,avg,k1,b FROM stats WHERE kind=?",(kind,)).fetchone()
        if stats is None:raise M3Error("Unknown lexical channel")
        n,avg,k1,b=stats;scores=defaultdict(float)
        for term in sorted(set(analyze(query))):
            row=self.db.execute("SELECT df FROM terms WHERE kind=? AND term=?",(kind,term)).fetchone()
            if row is None:continue
            idf=math.log(1+(n-row[0]+.5)/(row[0]+.5))
            rows=self.db.execute("SELECT p.id,p.tf,d.length FROM postings p JOIN documents d ON d.kind=p.kind AND d.id=p.id WHERE p.kind=? AND p.term=? AND (? IS NULL OR d.case_id!=?)",(kind,term,exclude_case,exclude_case))
            for ident,tf,length in rows:scores[ident]+=idf*tf*(k1+1)/(tf+k1*(1-b+b*length/(avg or 1)))
        ids=sorted(scores,key=lambda ident:(-scores[ident],ident))[:limit]
        return [{**doc,"score":scores[ident]} for ident,doc in zip(ids,self.get_many(kind,ids))]

    def iter_documents(self,kind):
        for row in self.db.execute("SELECT metadata FROM documents WHERE kind=? ORDER BY id",(kind,)):yield json.loads(row[0])

    def close(self):self.db.close()


def build_index(root,output):
    root=Path(root).resolve();target=artifact(root,output);started=time.perf_counter()
    if target.exists():raise M3Error("Index output exists; select a new directory")
    profile,code=load_profile(root),implementation()
    baseline=artifact(root,profile["baseline_run"])
    _,_,base,corpus,passages=load_run(root,profile["baseline_run"])
    if digest(canonical(baseline_implementation()))!=profile["baseline_code_sha256"]:raise M3Error("Baseline implementation drift")
    vectors=readonly_vectors(baseline,base)
    def cases():
        for case,expected in sorted(base["source_hashes"].items()):
            raw=(root/"data/task1_train_files_2026/cases"/case).read_bytes()
            if digest(raw)!=expected:raise M3Error("Source content drift during index build")
            yield {"case_id":case,"source_hash":expected,"text":raw.decode("utf-8")}
    target.mkdir(parents=True,exist_ok=False)
    params=base["profile"]["bm25"]
    lexical=PersistentBM25.create(target/"lexical.sqlite3",{"case":cases(),"passage":iter(passages)},params["k1"],params["b"]);lexical.close()
    with (target/"vectors.npy").open("xb") as f:np.save(f,vectors,allow_pickle=False)
    manifest={"schema_version":"pipeline-v2-m3-opt-index-2","profile":profile,"optimization_implementation":code,
              "baseline_manifest_sha256":file_digest(baseline/"pilot_manifest.json"),"baseline_manifest":base,
              "upstream_fingerprints":upstream_fingerprints(root,base),"passage_ids":base["passage_ids"],
              "source_hashes":base["source_hashes"],"source_scope":"selected_pilot_only",
              "metadata_policy":"text_free_raw_source_refs","session_contract":"immutable_snapshot_full_revalidate_at_open_or_verify_evidence_hash_at_open",
              "model_requests":0,"vectors_reused_without_inference":len(passages),"local_build_seconds":time.perf_counter()-started}
    if code!=implementation() or profile!=load_profile(root):raise M3Error("Build implementation/profile changed")
    write_json(target/"manifest.json",manifest)
    write_json(target/"seal.json",{"files":seal(target,["lexical.sqlite3","vectors.npy","manifest.json"])})
    return {"status":"persistent_index_v2_built","index_dir":str(target),"passages":len(passages),"cases":len(base["source_hashes"]),"model_requests":0,"seconds":time.perf_counter()-started}


class FastSession:
    """An explicitly immutable snapshot: no large-file rehash in hot queries.

    Caller must close/reopen or call revalidate if the workspace changes. A live
    mutation is not guaranteed detectable by ranking; evidence open hashes raw.
    """
    def __init__(self,root,index_dir,store=None):
        start=time.perf_counter();self.root=Path(root).resolve();self.directory=artifact(self.root,index_dir)
        self.sealed=read(self.directory/"seal.json")["files"]
        self.manifest=read(self.directory/"manifest.json");self.base=self.manifest["baseline_manifest"]
        self.invalidated=False
        self.revalidate()
        self.lexical=PersistentBM25(self.directory/"lexical.sqlite3")
        self.ids=list(self.manifest["passage_ids"])
        if len(set(self.ids))!=len(self.ids):raise M3Error("Duplicate snapshot passage IDs")
        self.byid={ident:i for i,ident in enumerate(self.ids)}
        count=self.lexical.db.execute("SELECT COUNT(*) FROM documents WHERE kind='passage'").fetchone()[0]
        actual_ids={r[0] for r in self.lexical.db.execute("SELECT id FROM documents WHERE kind='passage'")}
        if count!=len(self.ids) or actual_ids!=set(self.ids):raise M3Error("Lexical passage universe mismatch")
        self.vectors=np.load(self.directory/"vectors.npy",allow_pickle=False,mmap_mode="r")
        if self.vectors.shape!=(len(self.ids),self.base["profile"]["embedding"]["dimensions"]) or self.vectors.dtype!=np.dtype("float32"):
            raise M3Error("Unexpected mapped vector shape/dtype")
        q=self.base["profile"]["qdrant"]
        self.store=store or QdrantStore(q["url"],self.base["collection"],self.base["embedding_fingerprint"],self.vectors.shape[1])
        self.initialization_seconds=time.perf_counter()-start

    def guard(self):
        if self.invalidated:raise M3Error("Session invalidated; reopen the snapshot")
        if self.manifest["profile"]!=load_profile(self.root) or self.manifest["optimization_implementation"]!=implementation():
            self.invalidated=True;raise M3Error("Session profile/code drift")

    def revalidate(self):
        try:
            self.guard();validate_seal(self.directory,self.sealed)
            m=self.manifest;baseline=artifact(self.root,m["profile"]["baseline_run"])
            if file_digest(baseline/"pilot_manifest.json")!=m["baseline_manifest_sha256"] or read(baseline/"pilot_manifest.json")!=m["baseline_manifest"]:
                raise M3Error("Baseline manifest identity drift")
            if self.base["implementation"]!=baseline_implementation() or read(self.root/"pipeline_v2/configs/m3.json")!=self.base["profile"]:
                raise M3Error("Baseline code/profile drift")
            for name,expected in m["upstream_fingerprints"].items():
                if file_digest(self.root/name)!=expected:raise M3Error("Upstream provenance drift")
            for case,expected in m["source_hashes"].items():self.raw_case(case,expected)
        except Exception:
            self.invalidated=True;raise
        return {"status":"immutable_snapshot_revalidated","raw_cases":len(self.manifest["source_hashes"])}

    def raw_case(self,case,expected=None):
        if case not in self.manifest["source_hashes"]:raise M3Error("Source outside snapshot")
        path=self.root/"data/task1_train_files_2026/cases"/case
        if path.is_symlink():raise M3Error("Source symlink is not permitted")
        raw=path.read_bytes()
        if digest(raw)!=(expected or self.manifest["source_hashes"][case]):
            self.invalidated=True;raise M3Error("Current evidence source hash drift")
        return raw

    def passage_metadata(self,ids):return self.lexical.get_many("passage",ids)

    def full_passages(self,ids):
        result=[]
        for p in self.passage_metadata(ids):
            raw=self.raw_case(p["case_id"]);body=raw[slice(*p["span_bytes"])]
            if digest(body)!=p["exact_input_sha256"]:raise M3Error("Passage body differs from immutable input")
            result.append({**p,"text":body.decode("utf-8")})
        return result

    def cheap_db_check(self):
        info=self.store.info()
        if info is None:raise M3Error("Accepted vector collection is missing")
        shape=info["config"]["params"]["vectors"]
        if shape.get("size")!=self.vectors.shape[1] or shape.get("distance")!="Cosine":raise M3Error("DB vector schema mismatch")
        count=self.store._request("POST",self.store.path+"/points/count",{"exact":True})
        if count["count"]!=len(self.ids):raise M3Error("DB point-count drift")

    def search_vector(self,query,vector,query_case=None,limit=10):
        start=time.perf_counter();self.guard()
        if not isinstance(query,str) or not query.strip() or type(limit) is not int or not 1<=limit<=100:raise M3Error("Invalid query/limit")
        if query_case is not None and (not isinstance(query_case,str) or re.fullmatch(r"[0-9]{6}\.txt",query_case) is None):raise M3Error("Invalid query case ID")
        vector=validate_vectors([vector],1,self.vectors.shape[1])[0];self.cheap_db_check()
        scan=self.base["profile"]["fusion"]["scan_cap"];dense=self.store.search(vector,scan,query_case)
        ids=[h["passage_id"] for h in dense]
        if len(set(ids))!=len(ids) or not set(ids).issubset(self.byid):raise M3Error("Duplicate/outside dense IDs")
        metadata=self.passage_metadata(ids)
        for h,p in zip(dense,metadata):
            if h.get("embedding_fingerprint")!=self.base["embedding_fingerprint"] or h["case_id"]==query_case:raise M3Error("Dense profile/query filter mismatch")
            for k in ("case_id","source_hash","exact_input_sha256","span_bytes","parent_handle","policy_hash","tokenizer_fingerprint"):
                if h.get(k)!=p[k]:raise M3Error("Dense payload differs from snapshot")
            v=validate_vectors([self.vectors[self.byid[h["passage_id"]]]],1,self.vectors.shape[1])[0]
            if not np.isfinite(h["score"]) or abs(float(v@vector)-h["score"])>self.manifest["profile"]["search"]["score_atol"]:
                raise M3Error("Dense score differs from accepted vector")
        channels={"case_bm25":self.lexical.search(query,"case",scan,query_case),"passage_bm25":self.lexical.search(query,"passage",scan,query_case),"dense_passage":dense}
        return {"scope":"selected_pilot_immutable_snapshot","results":fuse_case_ranks(channels,limit,self.base["profile"]["fusion"]["k"]),
                "channels":{name:rank_cases(hits,limit) for name,hits in channels.items()},"local_retrieval_seconds":time.perf_counter()-start,
                "query_case_excluded":query_case,"must_open_before_citing":True,
                "guards":{"snapshot":"validated_once_at_session_open_explicit_revalidate_required_after_changes",
                          "evidence":"current_source_hash_checked_when_opened","database":"schema_count_and_returned_hits_not_full_attestation"}}

    def search(self,query,query_case=None,limit=10,compatibility=None,embedder=None):
        from .runtime import query_embedding, require_compatibility
        start=time.perf_counter();self.guard();self.cheap_db_check()
        if not isinstance(query,str) or not query.strip() or type(limit) is not int or not 1<=limit<=100:raise M3Error("Invalid query/limit")
        if query_case is not None and (not isinstance(query_case,str) or re.fullmatch(r"[0-9]{6}\.txt",query_case) is None):raise M3Error("Invalid query case ID")
        require_compatibility(self,compatibility,allow_simulated=embedder is not None)
        vector,receipt=query_embedding(self,query,embedder)
        result=self.search_vector(query,vector,query_case,limit)
        result.update({"warm_session_request_seconds":time.perf_counter()-start,"query_embedding":receipt,
                       "execution_mode":"simulated" if embedder is not None else "unified_v2_modal_query"})
        return result

    def open(self,ident):
        self.guard()
        if ident not in self.byid:raise M3Error("Passage outside snapshot")
        p=self.passage_metadata([ident])[0];self.raw_case(p["case_id"])
        from ..passages import PassageReader
        return PassageReader(self.root,self.base["profile"]["passages_bundle"]).open_context(p["case_id"],ident)

    def verify(self,full_db=False):
        result=self.revalidate();self.cheap_db_check()
        if full_db:
            validate_vectors(self.vectors,len(self.ids),self.vectors.shape[1])
            result["database"]=self.store.verify(self.passage_metadata(self.ids),self.vectors)
        result["full_db_verified"]=bool(full_db)
        return result

    def close(self):
        self.lexical.close()
        mapped=getattr(self.vectors,"_mmap",None)
        if mapped is not None:mapped.close()
