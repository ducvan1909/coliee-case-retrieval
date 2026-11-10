"""Persistent lexical index and bounded verified search over accepted vectors."""
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import sqlite3
import time

import numpy as np

from ..retrieval.bm25 import analyze, fuse_case_ranks, rank_cases
from ..retrieval.cache import Cache, validate_vectors
from ..retrieval.common import implementation as baseline_implementation
from ..retrieval.pilot import load_run
from ..retrieval.qdrant import QdrantStore
from ..retrieval.runtime import ModalEmbedder, call_embedding
from ..passages import PinnedTokenizer
from ..source.core import canonical, digest
from .common import M3Error, PROFILE, artifact, implementation, load_profile, read, seal, validate_seal, write_json


class PersistentBM25:
    """SQLite postings; query cost depends on matching postings, not all text."""
    def __init__(self, path, readonly=True):
        self.path = Path(path)
        self.db = sqlite3.connect(self.path.as_uri()+"?mode=ro", uri=True) if readonly else sqlite3.connect(self.path)

    @staticmethod
    def create(path, channels, k1=1.5, b=.75):
        path = Path(path)
        if path.exists():
            raise M3Error("Lexical index already exists")
        db = sqlite3.connect(path)
        db.executescript("CREATE TABLE documents(kind TEXT, id TEXT, case_id TEXT, length INTEGER, metadata TEXT, PRIMARY KEY(kind,id));"
                         "CREATE TABLE postings(kind TEXT,term TEXT,id TEXT,tf INTEGER,PRIMARY KEY(kind,term,id));"
                         "CREATE TABLE stats(kind TEXT PRIMARY KEY,n INTEGER,avg REAL,k1 REAL,b REAL);"
                         "CREATE TABLE terms(kind TEXT,term TEXT,df INTEGER,PRIMARY KEY(kind,term));")
        with db:
            for kind, docs in channels.items():
                docs = list(docs)
                frequencies = [Counter(analyze(d["text"])) for d in docs]
                df = Counter(t for f in frequencies for t in f)
                lengths = [sum(f.values()) for f in frequencies]
                db.execute("INSERT INTO stats VALUES(?,?,?,?,?)",(kind,len(docs),sum(lengths)/len(docs) if docs else 1,k1,b))
                for d, terms, length in zip(docs,frequencies,lengths):
                    ident = d.get("passage_id",d["case_id"])
                    db.execute("INSERT INTO documents VALUES(?,?,?,?,?)",(kind,ident,d["case_id"],length,json.dumps(d,ensure_ascii=False)))
                    db.executemany("INSERT INTO postings VALUES(?,?,?,?)",[(kind,t,ident,tf) for t,tf in terms.items()])
                db.executemany("INSERT INTO terms VALUES(?,?,?)",[(kind,t,n) for t,n in df.items()])
        db.close()
        return PersistentBM25(path)

    def search(self, query, kind, limit=1024, exclude_case=None):
        if type(limit) is not int or limit<1:
            raise M3Error("Invalid lexical limit")
        stats = self.db.execute("SELECT n,avg,k1,b FROM stats WHERE kind=?",(kind,)).fetchone()
        if stats is None:
            raise M3Error("Unknown lexical channel")
        n, avg, k1, b = stats
        scores = defaultdict(float)
        for term in sorted(set(analyze(query))):
            row = self.db.execute("SELECT df FROM terms WHERE kind=? AND term=?",(kind,term)).fetchone()
            if row is None:
                continue
            idf = math.log(1+(n-row[0]+.5)/(row[0]+.5))
            rows = self.db.execute("SELECT p.id,p.tf,d.length FROM postings p JOIN documents d ON d.kind=p.kind AND d.id=p.id WHERE p.kind=? AND p.term=? AND (? IS NULL OR d.case_id!=?)",(kind,term,exclude_case,exclude_case))
            for ident,tf,length in rows:
                scores[ident] += idf*tf*(k1+1)/(tf+k1*(1-b+b*length/(avg or 1)))
        chosen = sorted(scores,key=lambda ident:(-scores[ident],ident))[:limit]
        result = []
        for ident in chosen:
            d = json.loads(self.db.execute("SELECT metadata FROM documents WHERE kind=? AND id=?",(kind,ident)).fetchone()[0])
            result.append({**{k:v for k,v in d.items() if k!="text"},"score":scores[ident]})
        return result

    def documents(self, kind):
        return [json.loads(r[0]) for r in self.db.execute("SELECT metadata FROM documents WHERE kind=? ORDER BY id",(kind,))]

    def close(self):
        self.db.close()


def readonly_vectors(run, manifest):
    arrays = []
    ids = manifest["passage_ids"]
    hashes = manifest["input_hashes"]
    size = manifest["profile"]["batch_size"]
    for i in range(0,len(ids),size):
        batch_ids, batch_hashes = ids[i:i+size],hashes[i:i+size]
        base = run/"vectors"/digest(canonical([manifest["embedding_fingerprint"],batch_ids]))
        meta = read(base.with_suffix(".json"))
        raw = base.with_suffix(".npz").read_bytes()
        if meta != {"fingerprint":manifest["embedding_fingerprint"],"ids":batch_ids,"input_hashes":batch_hashes,"array_sha256":digest(raw)}:
            raise M3Error("Baseline committed shard identity mismatch")
        with np.load(base.with_suffix(".npz"),allow_pickle=False) as z:
            if z["ids"].tolist()!=batch_ids or z["input_hashes"].tolist()!=batch_hashes or str(z["fingerprint"])!=manifest["embedding_fingerprint"]:
                raise M3Error("Baseline embedded shard identity mismatch")
            arrays.append(validate_vectors(z["vectors"],len(batch_ids),manifest["profile"]["embedding"]["dimensions"]).copy())
    return np.concatenate(arrays)


def upstream_fingerprints(root, baseline):
    """Capture small manifests/config/code/assets, never parse M1 per query."""
    paths=set()
    bundle=artifact(root,baseline["profile"]["passages_bundle"])
    while True:
        for name in ("manifest.json","seal.json","source_registry.json"):
            p=bundle/name
            if p.exists():paths.add(p)
        if not (bundle/"manifest.json").exists():
            # M0 uses inventory/candidate manifests, not a root manifest.json.
            for name in ("inventory.json","candidate_manifest.json"):
                if (bundle/name).exists():paths.add(bundle/name)
            paths.add(root/"pipeline_v2/configs/m0.json")
            paths.add(root/"pipeline_v2/m0.py")
            break
        manifest=read(bundle/"manifest.json")
        for name in manifest.get("implementation",{}):paths.add(root/name)
        if manifest.get("profile_path"):paths.add(root/manifest["profile_path"])
        next_bundle=manifest.get("m1",{}).get("bundle") if "m1" in manifest else manifest.get("m0",{}).get("bundle")
        if next_bundle is None:break
        bundle=artifact(root,next_bundle)
    lock_path=root/"pipeline_v2/configs/qwen3_embedding_4b_tokenizer.lock.json"
    paths.add(lock_path)
    lock=read(lock_path)
    paths.update(root/lock["assets_dir"]/name for name in lock["files"])
    # Navigation metadata/identity is part of parent/context provenance too.
    m2=read(artifact(root,baseline["profile"]["passages_bundle"])/"manifest.json")
    nav=artifact(root,m2["navigation"]["bundle"])
    for name in ("manifest.json","seal.json","source_registry.json"):paths.add(nav/name)
    navm=read(nav/"manifest.json")
    paths.update(root/name for name in navm["implementation"])
    paths.add(root/navm["profile_path"])
    return {p.relative_to(root).as_posix():digest(p.read_bytes()) for p in sorted(paths)}


def build_index(root, output):
    started = time.perf_counter()
    root = Path(root).resolve()
    target = artifact(root,output)
    if target.exists():
        raise M3Error("Optimization output exists; choose a new directory")
    profile, code = load_profile(root), implementation()
    baseline = artifact(root,profile["baseline_run"])
    _,_,m,corpus,passages = load_run(root,profile["baseline_run"])
    if digest(canonical(baseline_implementation()))!=profile["baseline_code_sha256"]:
        raise M3Error("Accepted baseline code drift")
    vectors = readonly_vectors(baseline,m)
    cases = []
    for case_id,expected in sorted(m["source_hashes"].items()):
        raw = (root/"data/task1_train_files_2026/cases"/case_id).read_bytes()
        if digest(raw)!=expected:
            raise M3Error("Raw source drift while building index")
        cases.append({"case_id":case_id,"text":raw.decode("utf-8"),"source_hash":expected})
    target.mkdir(parents=True,exist_ok=False)
    p = m["profile"]["bm25"]
    lexical = PersistentBM25.create(target/"lexical.sqlite3",{"case":cases,"passage":passages},p["k1"],p["b"])
    lexical.close()
    with (target/"vectors.npy").open("xb") as f:
        np.save(f,vectors,allow_pickle=False)
    result = {"schema_version":"pipeline-v2-m3-opt-index-1","profile":profile,"optimization_implementation":code,
              "upstream_fingerprints":upstream_fingerprints(root,m),
              "baseline_manifest_sha256":digest((baseline/"pilot_manifest.json").read_bytes()),
              "baseline_manifest":m,"passage_ids":m["passage_ids"],"source_hashes":m["source_hashes"],
              "source_scope":"selected_pilot_only","model_requests":0,"vectors_reused_without_inference":len(passages),
              "local_build_seconds":time.perf_counter()-started}
    if code!=implementation() or profile!=load_profile(root):
        raise M3Error("Optimization code/profile changed while building")
    write_json(target/"manifest.json",result)
    write_json(target/"seal.json",{"files":seal(target,["lexical.sqlite3","vectors.npy","manifest.json"])})
    return {"status":"persistent_index_built","index_dir":str(target),"passages":len(passages),"cases":len(cases),"model_requests":0,"seconds":time.perf_counter()-started}


class FastSession:
    def __init__(self,root,index_dir,store=None):
        self.root = Path(root).resolve()
        self.directory = artifact(self.root,index_dir)
        self.sealed = read(self.directory/"seal.json")["files"]
        validate_seal(self.directory,self.sealed)
        self.manifest = read(self.directory/"manifest.json")
        self.base = self.manifest["baseline_manifest"]
        self.guard()
        self.lexical = PersistentBM25(self.directory/"lexical.sqlite3")
        self.passages = self.lexical.documents("passage")
        byid = {p["passage_id"]:p for p in self.passages}
        self.passages = [byid[i] for i in self.manifest["passage_ids"]]
        self.byid = {p["passage_id"]:i for i,p in enumerate(self.passages)}
        self.vectors = np.load(self.directory/"vectors.npy",allow_pickle=False,mmap_mode="r")
        validate_vectors(self.vectors,len(self.passages),self.base["profile"]["embedding"]["dimensions"])
        q = self.base["profile"]["qdrant"]
        self.store = store or QdrantStore(q["url"],self.base["collection"],self.base["embedding_fingerprint"],self.base["profile"]["embedding"]["dimensions"])

    def guard(self):
        m = self.manifest
        if m["profile"]!=load_profile(self.root) or m["optimization_implementation"]!=implementation():
            raise M3Error("Optimization code/profile drift")
        baseline = artifact(self.root,m["profile"]["baseline_run"])
        if digest((baseline/"pilot_manifest.json").read_bytes())!=m["baseline_manifest_sha256"] or m["baseline_manifest"]["implementation"]!=baseline_implementation():
            raise M3Error("Baseline manifest/code drift")
        if read(self.root/"pipeline_v2/configs/m3.json")!=m["baseline_manifest"]["profile"]:
            raise M3Error("Baseline profile drift")
        for name,expected in m["upstream_fingerprints"].items():
            if digest((self.root/name).read_bytes())!=expected:
                raise M3Error("Upstream source/config/tokenizer provenance drift")
        # Hash bytes, not timestamps. No M1 structure rebuilding or tokenization.
        for case_id,expected in m["source_hashes"].items():
            if digest((self.root/"data/task1_train_files_2026/cases"/case_id).read_bytes())!=expected:
                raise M3Error("Raw source content drift")
        validate_seal(self.directory,self.sealed)

    def cheap_db_check(self):
        info = self.store.info()
        if info is None:
            raise M3Error("Baseline vector collection missing")
        shape = info["config"]["params"]["vectors"]
        if shape.get("size")!=self.vectors.shape[1] or shape.get("distance")!="Cosine":
            raise M3Error("Collection schema mismatch")
        count = self.store._request("POST",self.store.path+"/points/count",{"exact":True})
        if count["count"]!=len(self.passages):
            raise M3Error("Collection point-count drift")

    def search_vector(self,query,vector,query_case=None,limit=10):
        started = time.perf_counter()
        if not isinstance(query,str) or not query.strip() or type(limit) is not int or not 1<=limit<=100:
            raise M3Error("Invalid query/limit")
        self.guard()
        vector = validate_vectors([vector],1,self.vectors.shape[1])[0]
        self.cheap_db_check()
        scan = self.base["profile"]["fusion"]["scan_cap"]
        dense = self.store.search(vector,scan,query_case)
        if len({h["passage_id"] for h in dense})!=len(dense):
            raise M3Error("Duplicate dense hit IDs")
        for h in dense:
            if h["passage_id"] not in self.byid:
                raise M3Error("Dense hit outside immutable pilot")
            i = self.byid[h["passage_id"]]
            p = self.passages[i]
            for key in ("case_id","source_hash","exact_input_sha256","span_bytes","parent_handle","policy_hash","tokenizer_fingerprint"):
                if h.get(key)!=p[key]:
                    raise M3Error("Dense returned payload mismatch")
            if h.get("embedding_fingerprint")!=self.base["embedding_fingerprint"] or h["case_id"]==query_case:
                raise M3Error("Dense hit profile/query-case mismatch")
            if not np.isfinite(h["score"]) or abs(float(self.vectors[i]@vector)-h["score"])>self.manifest["profile"]["search"]["score_atol"]:
                raise M3Error("Returned dense score differs from accepted vector")
        channels = {"case_bm25":self.lexical.search(query,"case",scan,query_case),
                    "passage_bm25":self.lexical.search(query,"passage",scan,query_case),"dense_passage":dense}
        return {"scope":"accepted_pilot_snapshot_only","query_case_excluded":query_case,
                "results":fuse_case_ranks(channels,limit,self.base["profile"]["fusion"]["k"]),
                "channels":{name:rank_cases(hits,limit) for name,hits in channels.items()},
                "seconds":time.perf_counter()-started,"must_open_before_citing":True,
                "guards":{"raw_content_hashes":"all_selected_cases","index":"sealed_content_hashes",
                          "database":"schema_count_and_returned_hits_only_not_full_membership_attestation"}}

    def search(self,query,query_case=None,limit=10,embedder=None):
        if not isinstance(query,str) or not query.strip() or type(limit) is not int or not 1<=limit<=100:
            raise M3Error("Invalid query/limit")
        self.guard()
        self.cheap_db_check()
        runtime = self.directory.parent/(self.directory.name+"_runtime")
        cache = Cache(runtime,self.base["embedding_fingerprint"],self.vectors.shape[1])
        tok = PinnedTokenizer(self.root,"pipeline_v2/configs/qwen3_embedding_4b_tokenizer.lock.json")
        vector,response = call_embedding(embedder or ModalEmbedder(self.base["profile"]),[query],"query",self.base["profile"],tok,self.base["implementation"],cache,"optimized-search-query")
        result = self.search_vector(query,vector[0],query_case,limit)
        result["usage"] = cache.usage()
        result["execution_mode"] = "simulated" if embedder is not None else "real_remote_query"
        return result

    def open(self,passage_id):
        self.guard()
        if passage_id not in self.byid:
            raise M3Error("Passage outside pilot snapshot")
        # Existing raw opener is safe; expensive rebuilding only for the hit case.
        from ..passages import PassageReader
        return PassageReader(self.root,self.base["profile"]["passages_bundle"]).open_context(self.passages[self.byid[passage_id]]["case_id"],passage_id)

    def verify(self,full_db=False):
        self.guard()
        self.cheap_db_check()
        result = {"status":"snapshot_and_query_health_checks_passed","full_db_verified":False}
        if full_db:
            result["database"] = self.store.verify(self.passages,self.vectors)
            result["full_db_verified"] = True
        return result

    def close(self):
        self.lexical.close()
