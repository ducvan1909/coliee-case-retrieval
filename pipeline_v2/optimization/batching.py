"""Deterministic length bucketing, preserving original passage identities."""
from ..retrieval.common import M3Error


def batches(passages, batch_size, ordered=True):
    if type(batch_size) is not int or not 1 <= batch_size <= 128:
        raise M3Error("Batch size must be 1..128")
    values = list(passages)
    if len({p["passage_id"] for p in values}) != len(values):
        raise M3Error("Duplicate batching passage IDs")
    if any(type(p["full_input_tokens"]) is not int or not 1 <= p["full_input_tokens"] <= 448 for p in values):
        raise M3Error("Invalid full token count")
    if ordered:
        values.sort(key=lambda p:(p["full_input_tokens"], p["passage_id"]))
    return [values[i:i+batch_size] for i in range(0,len(values),batch_size)]


def padding_stats(groups):
    return {"documents":sum(len(g) for g in groups),
            "input_tokens":sum(p["full_input_tokens"] for g in groups for p in g),
            "padded_tokens":sum(len(g)*max(p["full_input_tokens"] for p in g) for g in groups if g)}
