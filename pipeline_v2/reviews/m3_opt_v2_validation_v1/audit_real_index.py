"""Independent readonly metadata/vector/BM25 audit on actual pilot sources."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import time

import numpy as np


def sha(data):return hashlib.sha256(data).hexdigest()
def load(path):return json.loads(path.read_bytes())
def tokens(text):return re.findall(r"\w+",text.casefold(),re.UNICODE)


def reference(docs,query,excluded):
    frequencies=[Counter(tokens(d["text"])) for d in docs]
    lengths=[sum(x.values()) for x in frequencies]
    df=Counter(term for row in frequencies for term in row)
    avg=sum(lengths)/len(lengths) if lengths else 1
    results=[]
    for d,tf,length in zip(docs,frequencies,lengths):
        if d["case_id"]==excluded:continue
        score=0.
        for term in sorted(set(tokens(query))):
            f=tf[term]
            if f:score+=math.log(1+(len(docs)-df[term]+.5)/(df[term]+.5))*f*2.5/(f+1.5*(.25+.75*length/(avg or 1)))
        if score>0:results.append((d.get("passage_id",d["case_id"]),score))
    return sorted(results,key=lambda x:(-x[1],x[0]))


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--index-dir",required=True);parser.add_argument("--output",required=True);args=parser.parse_args()
    root=Path(__file__).resolve().parents[3];directory=root/args.index_dir;started=time.perf_counter()
    manifest=load(directory/"manifest.json");seal=load(directory/"seal.json")["files"]
    for name,expected in seal.items():
        raw=(directory/name).read_bytes();assert expected=={"sha256":sha(raw),"byte_length":len(raw)}
    db=sqlite3.connect((directory/"lexical.sqlite3").resolve().as_uri()+"?mode=ro",uri=True)
    metadata={kind:[json.loads(x[0]) for x in db.execute("SELECT metadata FROM documents WHERE kind=? ORDER BY id",(kind,))] for kind in ("case","passage")}
    db.close()
    assert all("text" not in d for rows in metadata.values() for d in rows)
    base=manifest["baseline_manifest"];assert len(metadata["case"])==len(base["source_hashes"])
    assert {p["passage_id"] for p in metadata["passage"]}==set(base["passage_ids"])
    source={case:(root/"data/task1_train_files_2026/cases"/case).read_bytes() for case in base["source_hashes"]}
    assert all(sha(raw)==base["source_hashes"][case] for case,raw in source.items())
    docs={"case":[{**p,"text":source[p["case_id"]].decode("utf-8")} for p in metadata["case"]],"passage":[]}
    for p in metadata["passage"]:
        raw=source[p["case_id"]][slice(*p["span_bytes"])];assert sha(raw)==p["exact_input_sha256"]
        docs["passage"].append({**p,"text":raw.decode("utf-8")})
    vectors=np.load(directory/"vectors.npy",allow_pickle=False,mmap_mode="r")
    assert vectors.shape==(len(base["passage_ids"]),2560) and vectors.dtype==np.float32
    assert np.isfinite(vectors).all() and np.allclose(np.linalg.norm(vectors,axis=1),1,atol=.002,rtol=0)
    for i in range(0,len(base["passage_ids"]),base["profile"]["batch_size"]):
        ids=base["passage_ids"][i:i+base["profile"]["batch_size"]]
        key=sha((json.dumps([base["embedding_fingerprint"],ids],sort_keys=True,separators=(",",":"),ensure_ascii=False)+"\n").encode())
        shard=root/manifest["profile"]["baseline_run"]/"vectors"/(key+".npz")
        with np.load(shard,allow_pickle=False) as cached:
            assert cached["ids"].tolist()==ids
            assert np.array_equal(vectors[i:i+len(ids)],cached["vectors"])
    from pipeline_v2.optimization_v2.index import PersistentBM25
    index=PersistentBM25(directory/"lexical.sqlite3");checks=[]
    try:
        for kind in ("case","passage"):
            for query,excluded in [("standard of review",None),("standard of review","079659.txt"),("décision n'est pas raisonnable under s. 97(1)",None)]:
                expected=reference(docs[kind],query,excluded);t=time.perf_counter();actual=index.search(query,kind,1024,excluded);seconds=time.perf_counter()-t
                assert [p.get("passage_id",p["case_id"]) for p in actual]==[p[0] for p in expected]
                assert np.allclose([p["score"] for p in actual],[p[1] for p in expected],atol=1e-10,rtol=1e-10)
                checks.append({"kind":kind,"query":query,"excluded_case":excluded,"hits":len(actual),"query_seconds":seconds,"status":"PASS"})
    finally:index.close()
    result={"status":"PASS","case_metadata":len(metadata["case"]),"passage_metadata":len(metadata["passage"]),"metadata_has_raw_text":False,
            "vectors_shape":list(vectors.shape),"vectors_exactly_equal_baseline_shards":True,"sqlite_bytes":(directory/"lexical.sqlite3").stat().st_size,"lexical_checks":checks,
            "elapsed_seconds":time.perf_counter()-started,"modal_requests":0,"Qdrant_accessed":False,"scope":"local_index_integrity_and_actual_BM25_equivalence_only"}
    with (root/args.output).open("x",encoding="utf-8") as stream:json.dump(result,stream,indent=2);stream.write("\n")
    print(json.dumps(result))


if __name__=="__main__":main()
