"""Read-only real pilot lexical equivalence; no model or Qdrant calls."""
import json
from pathlib import Path
import time

import numpy as np

from pipeline_v2.optimization.index import PersistentBM25
from pipeline_v2.retrieval.bm25 import BM25


def main():
    root=Path(__file__).resolve().parents[3]
    index=root/"pipeline_v2/artifacts/m3_opt_index_20261107_v2"
    actual=PersistentBM25(index/"lexical.sqlite3")
    queries=[("standard of review",None),("standard of review","079659.txt"),
             ("décision n'est pas raisonnable under s. 97(1)",None)]
    rows=[]
    try:
        for kind in ("case","passage"):
            docs=actual.documents(kind)
            start=time.perf_counter()
            oracle=BM25(docs)
            build_seconds=time.perf_counter()-start
            for query,excluded in queries:
                start=time.perf_counter(); expected=oracle.search(query,1024,excluded); reference_seconds=time.perf_counter()-start
                start=time.perf_counter(); observed=actual.search(query,kind,1024,excluded); persisted_seconds=time.perf_counter()-start
                key=lambda p:p.get("passage_id",p["case_id"])
                assert [key(p) for p in observed]==[key(p) for p in expected]
                assert np.allclose([p["score"] for p in observed],[p["score"] for p in expected],atol=1e-10,rtol=1e-10)
                rows.append({"channel":kind,"query":query,"excluded_case":excluded,"hits":len(observed),
                             "reference_build_seconds":build_seconds,"reference_search_seconds":reference_seconds,
                             "persistent_search_seconds":persisted_seconds,"ranking_and_scores":"PASS"})
    finally:actual.close()
    result={"status":"PASS","checks":rows,"model_requests":0,"Qdrant_accessed":False,
            "scope":"same_pilot_lexical_equivalence_not_whole_hybrid_latency"}
    out=Path(__file__).with_name("real_lexical_equivalence.json")
    with out.open("x",encoding="utf-8") as f:json.dump(result,f,indent=2);f.write("\n")
    print(json.dumps(result))


if __name__=="__main__":main()
