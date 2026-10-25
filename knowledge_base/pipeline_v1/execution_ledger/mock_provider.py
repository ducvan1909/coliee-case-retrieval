"""Deterministic offline mock provider with explicit fault injection."""
from __future__ import annotations
from typing import Any
from ..sentence_atoms.segmenter import canonical_hash

def call_mock(request: dict[str,Any],attempt_number:int,policy:dict[str,Any],fault:str="success") -> dict[str,Any]:
    latency=policy["provider"]["base_latency_ms"]+int(canonical_hash({"request":request["request_id"],"attempt":attempt_number})[:2],16)%7
    base={"provider_id":policy["provider"]["provider_id"],"request_id":request["request_id"],"attempt_number":attempt_number,"latency_ms":latency}
    if fault=="transient" and attempt_number==1:return {**base,"transport_outcome":"transient_failure","response":None}
    if fault=="permanent":return {**base,"transport_outcome":"permanent_failure","response":None}
    if fault in {"timeout","interrupt"}:return {**base,"transport_outcome":"timeout","response":None}
    work=list(request["expected_work_item_ids"]);targets=list(request["expected_target_ids"])
    if fault=="malformed":response={"unexpected":"shape"}
    elif fault=="missing":response={"processed_work_item_ids":work[:-1],"processed_target_ids":targets}
    elif fault=="duplicate":response={"processed_work_item_ids":work+[work[0]],"processed_target_ids":targets}
    elif fault=="foreign":response={"processed_work_item_ids":work+["foreign-work-item"],"processed_target_ids":targets}
    elif fault=="partial":response={"processed_work_item_ids":work[:max(1,len(work)//2)],"processed_target_ids":targets[:max(1,len(targets)//2)]}
    else:response={"processed_work_item_ids":work,"processed_target_ids":targets,"protocol_only":True}
    return {**base,"transport_outcome":"success","response":response}
