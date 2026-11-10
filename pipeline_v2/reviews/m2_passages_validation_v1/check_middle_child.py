"""Independent tester-proposed real middle-child expansion regression."""
import json
from pathlib import Path
import time

from pipeline_v2.passages import PassageReader


def main():
    root = Path(__file__).resolve().parents[3]
    bundle = "pipeline_v2/artifacts/m2_passages_20261106_v1"
    case, handle = "041666.txt", "p000417"
    started = time.perf_counter()
    record = json.loads((root / bundle / "sources/041666.json").read_bytes())
    parent = next(x for x in record["parents"] if x["handle"] == handle)
    refs = parent["passage_refs"]
    assert len(refs) > 2
    pid = refs[len(refs)//2]
    hit = next(x for x in record["passages"] if x["passage_id"] == pid)
    assert hit["previous_sibling_ref"] and hit["next_sibling_ref"]
    assert hit["span_bytes"] != parent["span_bytes"]
    reader = PassageReader(root, bundle)
    opened = reader.open_context(case, pid)
    raw = (root / "data/task1_train_files_2026/cases" / case).read_bytes()
    a, b = opened["span_bytes"]
    assert opened["text"] == raw[a:b].decode("utf-8")
    assert opened["hit_span_bytes"] == hit["span_bytes"]
    assert opened["hit_text"] == raw[slice(*hit["span_bytes"])].decode("utf-8")
    assert opened["diagnostic_only"] is True and opened["M4_delivery_recorded"] is False
    assert opened["hit_is_distinct_from_context"] is True
    components = {x["kind"]: x for x in opened["components"]}
    assert components["parent"]["span_bytes"] == hit["parent_span_bytes"] == parent["span_bytes"]
    expected = hit["reading_expansion"]
    expected_labels = []
    for label, field in (("previous_context","previous_ref"),("parent","parent_ref"),("next_context","next_ref")):
        if expected[field] is None:
            assert label not in components
            assert expected[label.replace("_context", "")+"_absence_reason"] == "source_boundary"
        else:
            assert components[label]["handle"] == expected[field]
            expected_labels.append(label)
    assert [x["kind"] for x in opened["components"]] == expected_labels
    assert all(a <= x["span_bytes"][0] < x["span_bytes"][1] <= b for x in opened["components"])
    interior = next(p for p in record["passages"] if p["split_order"] > 0 and p["next_sibling_ref"]
                    and p["reading_expansion"]["previous_ref"] and p["reading_expansion"]["next_ref"])
    context2 = reader.open_context(case, interior["passage_id"])
    c2 = {x["kind"]:x for x in context2["components"]}
    assert list(c2) == ["previous_context", "parent", "next_context"]
    assert c2["parent"]["span_bytes"] == interior["parent_span_bytes"]
    assert c2["previous_context"]["handle"] == interior["reading_expansion"]["previous_ref"]
    assert c2["next_context"]["handle"] == interior["reading_expansion"]["next_ref"]
    assert context2["text"] == raw[slice(*context2["span_bytes"])].decode("utf-8")
    result = {"status":"PASS","case_id":case,"parent_handle":handle,"split_count":len(refs),
              "hit_id":pid,"hit_span_bytes":hit["span_bytes"],"parent_span_bytes":parent["span_bytes"],
              "context_span_bytes":opened["span_bytes"],"neighbor_handles":{k:v["handle"] for k,v in components.items()},
              "elapsed_seconds":time.perf_counter()-started,
              "scope":"diagnostic_raw_context_not_M4_delivery_or_semantic_quality",
              "interior_middle_child":{"parent_handle":interior["parent_handle"],"passage_id":interior["passage_id"],
                                       "neighbor_handles":{k:v["handle"] for k,v in c2.items()}},
              "prior_attempt":{"status":"FAIL","cause":"checker_assumed_next_neighbor_at_source_end","production_changed":False}}
    output = root / "pipeline_v2/reviews/m2_passages_validation_v1/middle_child_result.json"
    with output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
