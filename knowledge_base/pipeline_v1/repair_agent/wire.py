"""Compact wire normalization and SGLang EBNF; host guards remain authoritative."""
from __future__ import annotations
import copy
import json
from jsonschema import Draft202012Validator
from .core import CONTRACTS, load, validate, MODEL, POLICY
from .grammar import Compiler


def wire_schema(task, arm, turn, read_ids):
    schema = load(CONTRACTS / "repair_wire.v2.json")
    calls = schema["properties"]["tool_calls"]["items"]["oneOf"]
    if arm == "R1" or turn == 2:
        calls[:] = [c for c in calls if c["properties"]["name"]["const"] == "submit_revision"]
    for call in calls:
        if call["properties"]["name"]["const"] == "submit_revision":
            decisions = call["properties"]["arguments"]["properties"]["decisions"]
            decisions["minItems"] = decisions["maxItems"] = len(task["original_proposals"])
    def bind(node, key=None):
        if not isinstance(node, dict): return
        if key == "task_id": node.update(const=task["task_id"])
        if key in {"proposal_id", "retained_proposal_id"}: node.update(enum=[p["proposal_id"] for p in task["original_proposals"]])
        if key == "atom_id": node.update(enum=sorted(read_ids))
        if key == "evidence_ref_ids": node["items"].update(enum=sorted(read_ids))
        for k,v in node.get("properties", {}).items(): bind(v,k)
        for k in ("oneOf", "anyOf", "allOf"):
            for v in node.get(k, []): bind(v)
        if "items" in node: bind(node["items"])
    bind(schema)
    return schema


def normalize(output, task, arm, turn, read_ids):
    Draft202012Validator(wire_schema(task, arm, turn, read_ids)).validate(output)
    full = copy.deepcopy(output)
    call = full["tool_calls"][0]
    if call["name"] == "submit_revision":
        args = call["arguments"]
        ids = [d["proposal_id"] for d in args["decisions"]]
        if len(ids) != len(set(ids)) or set(ids) != {p["proposal_id"] for p in task["original_proposals"]}:
            raise ValueError("foreign_or_missing_revision_identity")
        supported = {d["proposal_id"] for d in args["decisions"] if d["verdict"] == "supported"}
        for d in args["decisions"]:
            if d["verdict"] == "defect_found":
                if d["defect_type"] == "duplicate" and (d["retained_proposal_id"] == d["proposal_id"] or d["retained_proposal_id"] not in supported):
                    raise ValueError("duplicate_requires_distinct_supported_retained")
                for r in d["correction"].get("replacements", []):
                    r["au"].setdefault("other_kind", None)
                    r["au"].setdefault("needs_context", [])
    Draft202012Validator(wire_schema(task, arm, turn, read_ids)).validate(full)
    return full


def decoding(task, arm, turn, read_ids, *, forced_verdict=None, forced_action=None):
    schema=wire_schema(task, arm, turn, read_ids)
    force_branches(schema, forced_verdict=forced_verdict, forced_action=forced_action)
    return {"ebnf": Compiler(allow_duplicate=len(task["original_proposals"]) > 1).compile(schema)}


def force_branches(schema, *, forced_verdict=None, forced_action=None):
    if forced_verdict is not None or forced_action is not None:
        if forced_verdict not in {None, "supported", "uncertain", "defect_found"}: raise ValueError("invalid_probe_verdict")
        if forced_action not in {None, "replace", "reject"}: raise ValueError("invalid_probe_action")
        if forced_action is not None and forced_verdict in {"supported", "uncertain"}:
            raise ValueError("invalid_probe_action_for_verdict")
        for call in schema["properties"]["tool_calls"]["items"]["oneOf"]:
            if call["properties"]["name"]["const"] == "submit_revision":
                variants = call["properties"]["arguments"]["properties"]["decisions"]["items"]["oneOf"]
                variants[:] = [v for v in variants if v["properties"]["verdict"]["const"] == (forced_verdict or "defect_found")]
                if not variants: raise ValueError("unavailable_probe_verdict")
                if forced_action:
                    correction = variants[0]["properties"]["correction"]["oneOf"]
                    correction[:] = [v for v in correction if v["properties"]["action"]["const"] == forced_action]
                    if not correction: raise ValueError("unavailable_probe_action")



def bound_messages(messages, attempt_id):
    return copy.deepcopy(messages)+[{"role":"user","content":"Attempt binding: "+attempt_id}]


def payload(messages, task, arm, turn, attempt_id, read_ids):
    from .selection import selection_decoding
    return {"model":MODEL,"messages":bound_messages(messages,attempt_id),"temperature":0,
            "max_tokens":POLICY["output_tokens"],"chat_template_kwargs":{"enable_thinking":False},
            **selection_decoding(task,arm,turn,read_ids)}
