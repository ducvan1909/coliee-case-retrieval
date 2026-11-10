"""Actual Qdrant/SQLite timing using accepted document vectors as probes.

This isolates the local path. Probe vectors are not instruction-rendered query
embeddings, so this is neither semantic quality nor full query latency.
"""
import json
from pathlib import Path
import time

from pipeline_v2.optimization.index import FastSession


def main():
    root=Path(__file__).resolve().parents[3]
    directory="pipeline_v2/artifacts/m3_opt_index_20261107_v2"
    started=time.perf_counter();session=FastSession(root,directory)
    initialization=time.perf_counter()-started
    rows=[]
    try:
        for index in (0,512,1023):
            passage=session.passages[index]
            query="standard of review" if index!=1023 else "décision n'est pas raisonnable under s. 97(1)"
            timings=[]
            for repeat in range(3):
                start=time.perf_counter()
                result=session.search_vector(query,session.vectors[index],passage["case_id"],10)
                timings.append(time.perf_counter()-start)
                assert all(r["case_id"]!=passage["case_id"] for r in result["results"])
            rows.append({"probe_passage":passage["passage_id"],"excluded_case":passage["case_id"],
                         "query_for_lexical_channel":query,"local_seconds":timings,
                         "unique_case_results":len(result["results"]),"guard_contract":result["guards"]})
    finally:session.close()
    result={"status":"PASS","session_init_seconds":initialization,"probes":rows,"model_requests":0,
            "actual_Qdrant":True,"actual_SQLite":True,
            "scope":"local_retrieval_path_using_document_vector_probes_not_full_query_latency_or_quality"}
    output=Path(__file__).with_name("local_retrieval_probe_benchmark.json")
    with output.open("x",encoding="utf-8") as f:json.dump(result,f,indent=2);f.write("\n")
    print(json.dumps(result))


if __name__=="__main__":main()
