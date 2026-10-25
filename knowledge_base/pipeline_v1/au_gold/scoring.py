"""Independent deterministic AU scoring; no model or provider dependency."""
from __future__ import annotations
from collections import defaultdict

def _primary(record):return record["evidence_spans"][0]
def _key(span):return (span["case_id"],span["source_hash"],span["start_char"],span["end_char"])
def _overlap(a,b):return max(0,min(a["end_char"],b["end_char"])-max(a["start_char"],b["start_char"]))
def _iou(a,b):
    inter=_overlap(a,b);return inter/(max(a["end_char"],b["end_char"])-min(a["start_char"],b["start_char"])) if inter else 0.0
def _prf(tp,fp,fn):
    p=tp/(tp+fp) if tp+fp else (1.0 if fn==0 else 0.0);r=tp/(tp+fn) if tp+fn else 1.0;f=2*p*r/(p+r) if p+r else 0.0
    return {"tp":tp,"fp":fp,"fn":fn,"precision":round(p,8),"recall":round(r,8),"f1":round(f,8)}

def _match(gold,pred,exact):
    pairs=[];used=set()
    for gi,g in enumerate(gold):
        best=None
        for pi,p in enumerate(pred):
            if pi in used or _primary(g)["case_id"]!=_primary(p)["case_id"]:continue
            score=1.0 if _key(_primary(g))==_key(_primary(p)) else (0.0 if exact else _iou(_primary(g),_primary(p)))
            if score>0 and (best is None or score>best[0]):best=(score,pi)
        if best is not None:used.add(best[1]);pairs.append((gi,best[1],best[0]))
    return pairs

def _field_witness_ok(gold,pred,field):
    gs=gold.get(field,[]);ps=pred.get(field,[])
    if field=="attributions":
        if not gs:return not ps
        for ga in gs:
            if not any(pa.get("role")==ga.get("role") and pa.get("speaker")==ga.get("speaker") and _overlap(pa["evidence_span"],ga["evidence_span"])>0 for pa in ps):return False
        return True
    if not gs:return not ps
    return all(any(_overlap(g,p)>0 for p in ps) for g in gs)

def score_predictions(gold_records,prediction_records,hard_negatives=None,overlap_threshold=0.1):
    hard_negatives=hard_negatives or [];cases=sorted({x["case_id"] for x in gold_records}|{x["case_id"] for x in prediction_records});per_case={};all_exact=[];all_overlap=[]
    severe=[];kind_correct=kind_total=0;field={name:{"correct":0,"total":0,"severe":0} for name in ("attributions","condition_spans","exception_spans","limit_spans")}
    for case_id in cases:
        gold=[x for x in gold_records if x["case_id"]==case_id];pred=[x for x in prediction_records if x["case_id"]==case_id];exact=_match(gold,pred,True);overlap=[x for x in _match(gold,pred,False) if x[2]>=overlap_threshold];all_exact.extend((case_id,*x) for x in exact);all_overlap.extend((case_id,*x) for x in overlap)
        per_case[case_id]={"exact":_prf(len(exact),len(pred)-len(exact),len(gold)-len(exact)),"overlap":_prf(len(overlap),len(pred)-len(overlap),len(gold)-len(overlap)),"omission_count":len(gold)-len(overlap),"false_positive_count":len(pred)-len(overlap)}
        for gi,pi,score in overlap:
            g,p=gold[gi],pred[pi];kind_total+=1
            if g["kind"]==p["kind"]:kind_correct+=1
            for name in field:
                field[name]["total"]+=1;ok=_field_witness_ok(g,p,name)
                if ok:field[name]["correct"]+=1
                elif name in {"attributions","condition_spans","exception_spans","limit_spans"} and g.get(name):field[name]["severe"]+=1;severe.append({"case_id":case_id,"gold_au_id":g["au_id"],"prediction_au_id":p["au_id"],"type":"missing_or_wrong_"+name,"span_overlap":score})
    exact_metric=_prf(len(all_exact),len(prediction_records)-len(all_exact),len(gold_records)-len(all_exact));overlap_metric=_prf(len(all_overlap),len(prediction_records)-len(all_overlap),len(gold_records)-len(all_overlap))
    hard_fp=[]
    for pred in prediction_records:
        for negative in hard_negatives:
            span=negative["reviewed_span"]
            if _primary(pred)["case_id"]==span["case_id"] and _overlap(_primary(pred),span)>0:hard_fp.append({"prediction_au_id":pred["au_id"],"negative_reason":negative["reason"]});break
    macro={name:round(sum(per_case[c][name][metric] for c in cases)/len(cases),8) if cases else 0.0 for name in ("exact","overlap") for metric in ()}
    macro={name:{metric:round(sum(per_case[c][name][metric] for c in cases)/len(cases),8) if cases else 0.0 for metric in ("precision","recall","f1")} for name in ("exact","overlap")}
    return {"scoring_version":"au-scoring-v1","overlap_threshold":overlap_threshold,"micro":{"exact":exact_metric,"overlap":overlap_metric},"macro":macro,"per_case":per_case,"omission_count":overlap_metric["fn"],"false_positive_count":overlap_metric["fp"],"kind":{"correct":kind_correct,"total":kind_total,"accuracy":round(kind_correct/kind_total,8) if kind_total else 0.0},"field_level":field,"hard_negatives":{"reviewed_count":len(hard_negatives),"false_positive_count":len(hard_fp),"errors":hard_fp},"severe_error_count":len(severe),"severe_errors":severe,"note":"partial span overlap never suppresses attribution/condition/exception/limit severe errors"}
