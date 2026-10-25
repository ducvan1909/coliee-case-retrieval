"""Finite source selections; metadata references text already in the read view.

No semantic adjudication. v2 witnesses require a unique quote within their atom.
"""
from __future__ import annotations

import copy

from jsonschema import Draft202012Validator

from ..au_candidate_store.core import _hash
from .core import CONTRACTS, load

VERSION = "repair-selection-v1"
CATALOG_LIMIT = 128
SUBSPANS_PER_ATOM = 0


def evidence_catalog(task, read_ids):
    atoms = task["supplied_atom_catalog"] + task.get("expansion_atom_catalog", [])
    by_id = {a["atom_id"]: a for a in atoms}
    if len(by_id) != len(atoms) or len(read_ids) != len(set(read_ids)):
        raise ValueError("duplicate_selection_atom")
    if not set(read_ids) <= by_id.keys():
        raise ValueError("selection_atom_not_read")
    read = [by_id[aid] for aid in sorted(read_ids)]
    for a in read:
        if (a["case_id"] != task["case_id"] or a["source_hash"] != task["source_hash"] or
                type(a["start_char"]) is not int or type(a["end_char"]) is not int or
                not 0 <= a["start_char"] < a["end_char"] or
                len(a["quote"]) != a["end_char"] - a["start_char"]):
            raise ValueError("selection_source_identity_or_bounds")
    for t in task["raw_targets"]:
        if t["case_id"] != task["case_id"] or t["source_hash"] != task["source_hash"]:
            raise ValueError("selection_target_identity")
    view = _hash([VERSION, task["task_id"], task["case_id"], task["source_hash"],
                  task["raw_targets"], read])
    candidates = []
    # Whole atoms and clipped targets precede optional sentence subspans.
    for a in read:
        candidates.append((a, 0, len(a["quote"])))
        for t in task["raw_targets"]:
            lo = max(a["start_char"], t["start_char"]) - a["start_char"]
            hi = min(a["end_char"], t["end_char"]) - a["start_char"]
            if lo < hi: candidates.append((a, lo, hi))
    entries, seen = [], set()
    ambiguous = 0
    for a, lo, hi in candidates:
        key = (a["atom_id"], lo, hi)
        if key in seen: continue
        seen.add(key)
        quote = a["quote"][lo:hi]
        position = a["quote"].find(quote)
        if position != lo or a["quote"].find(quote, position + 1) >= 0:
            ambiguous += 1
            continue
        start, end = a["start_char"] + lo, a["start_char"] + hi
        entries.append(dict(evidence_id="e-" + _hash([view, key])[:16], atom_id=a["atom_id"],
            relative_start=lo, relative_end=hi,
            target_eligible=any(t["start_char"] <= start < end <= t["end_char"] for t in task["raw_targets"]),
            case_id=a["case_id"], source_hash=a["source_hash"], start_char=start,
            end_char=end, quote=quote))
    if len({e["evidence_id"] for e in entries}) != len(entries):
        raise ValueError("selection_id_collision")
    return dict(version=VERSION, view_sha256=view, entries=entries[:CATALOG_LIMIT],
                limit=CATALOG_LIMIT, subspans_per_atom=SUBSPANS_PER_ATOM,
                truncated=len(entries) > CATALOG_LIMIT, ambiguous_omitted=ambiguous,
                fallback="uncertain_if_no_suitable_selection")


def model_catalog(task, read_ids):
    catalog = evidence_catalog(task, read_ids)
    # Indexes refer to the supplied_atom_catalog order in this exact prompt.
    indexes = {aid: i for i, aid in enumerate(read_ids)}
    return dict(columns=["id", "atom_index", "relative_start", "relative_end", "target_eligible"],
        entries=[[e["evidence_id"], indexes[e["atom_id"]], e["relative_start"],
                  e["relative_end"], int(e["target_eligible"])] for e in catalog["entries"]],
        truncated=catalog["truncated"], ambiguous_omitted=catalog["ambiguous_omitted"])


def selection_schema(task, arm, turn, read_ids):
    from .wire import wire_schema
    schema = load(CONTRACTS / "repair_selection_wire.v1.json")
    # Keep shared enum/identity/turn binding identical to the preserved v2 path.
    full = wire_schema(task, arm, turn, read_ids)
    calls = schema["properties"]["tool_calls"]["items"]["oneOf"]
    allowed = {c["properties"]["name"]["const"] for c in full["properties"]["tool_calls"]["items"]["oneOf"]}
    calls[:] = [c for c in calls if c["properties"]["name"]["const"] in allowed]
    catalog = evidence_catalog(task, read_ids)
    ids = [e["evidence_id"] for e in catalog["entries"]]
    primary_ids = [e["evidence_id"] for e in catalog["entries"] if e["target_eligible"]]
    for call in calls:
        if call["properties"]["name"]["const"] == "submit_revision":
            variants = call["properties"]["arguments"]["properties"]["decisions"]["items"]["oneOf"]
            if not primary_ids:
                variants[:] = [v for v in variants if v["properties"]["verdict"]["const"] != "supported"]
                for v in variants:
                    if "correction" in v["properties"]:
                        corrections = v["properties"]["correction"]["oneOf"]
                        corrections[:] = [c for c in corrections if c["properties"]["action"]["const"] == "reject"]
            if not ids:
                variants[:] = [v for v in variants if v["properties"]["verdict"]["const"] == "uncertain"]
    if not ids:
        calls[:] = [c for c in calls if c["properties"]["name"]["const"] != "open_span"]
    def bind(node, key=None):
        if not isinstance(node, dict): return
        if key == "task_id": node.update(const=task["task_id"])
        if key in {"proposal_id", "retained_proposal_id"}:
            node.update(enum=[p["proposal_id"] for p in task["original_proposals"]])
        if key == "primary_proposition": node.update(enum=primary_ids)
        if key == "span_selection_id": node.update(enum=ids)
        if key == "witnesses": node["items"].update(enum=ids)
        if key == "evidence_ref_ids": node["items"].update(enum=sorted(read_ids))
        if key == "decisions": node.update(minItems=len(task["original_proposals"]), maxItems=len(task["original_proposals"]))
        for k, v in node.get("properties", {}).items(): bind(v, k)
        for k in ("oneOf", "anyOf", "allOf"):
            for v in node.get(k, []): bind(v)
        if "items" in node: bind(node["items"])
    bind(schema)
    return schema


def normalize_selection(output, task, arm, turn, read_ids):
    """Strict transport boundary: never accept a legacy full witness here."""
    from .wire import normalize
    Draft202012Validator(selection_schema(task, arm, turn, read_ids)).validate(output)
    entries = {e["evidence_id"]: e for e in evidence_catalog(task, read_ids)["entries"]}
    full = copy.deepcopy(output)
    del full["schema_version"]
    call = full["tool_calls"][0]
    def witness(eid):
        e = entries[eid]
        return dict(atom_id=e["atom_id"], quote=e["quote"])
    if call["name"] == "open_span":
        e = entries[call["arguments"]["span_selection_id"]]
        call["arguments"] = {k: e[k] for k in ("atom_id", "start_char", "end_char", "quote")}
    elif call["name"] == "submit_revision":
        for d in call["arguments"]["decisions"]:
            if "primary_proposition" in d: d["primary_proposition"] = witness(d["primary_proposition"])
            if "witnesses" in d: d["witnesses"] = [witness(eid) for eid in d["witnesses"]]
            for r in d.get("correction", {}).get("replacements", []):
                r["primary_proposition"] = witness(r["primary_proposition"])
    full = normalize(full, task, arm, turn, read_ids)
    if call["name"] == "submit_revision":
        originals = {p["proposal_id"]: p["proposal"] for p in task["original_proposals"]}
        from ..au_candidate_store.reviews import _quote
        atoms = {a["atom_id"]: a for a in task["supplied_atom_catalog"] + task.get("expansion_atom_catalog", []) if a["atom_id"] in read_ids}
        for d in full["tool_calls"][0]["arguments"]["decisions"]:
            pairs = [(d["primary_proposition"], originals[d["proposal_id"]])] if d["verdict"] == "supported" else []
            pairs += [(r["primary_proposition"], r["au"]) for r in d.get("correction", {}).get("replacements", [])]
            for primary, au in pairs:
                if primary["atom_id"] not in au["evidence_ref_ids"]:
                    raise ValueError("primary_not_selected_evidence")
                if not set(au["evidence_ref_ids"]) <= set(read_ids):
                    raise ValueError("evidence_id_not_read")
                _quote(primary, atoms, task["raw_targets"], primary=True)
    return full


def selection_decoding(task, arm, turn, read_ids, **forced):
    from .wire import force_branches
    from .grammar import Compiler
    schema = selection_schema(task, arm, turn, read_ids)
    force_branches(schema, **forced)
    return {"ebnf": Compiler(allow_duplicate=len(task["original_proposals"]) > 1).compile(schema)}
