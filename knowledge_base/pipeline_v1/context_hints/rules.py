"""Deterministic local ContextHint rules and cap/dedup policy."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Callable

from ..sentence_atoms.segmenter import canonical_hash, span

REFERENCE_RE = re.compile(
    r"\b(?:as\s+(?:noted|stated|discussed|set\s+out|mentioned)\s+(?:above|previously)|"
    r"the\s+foregoing|previous\s+paragraph|preceding\s+paragraph)\b",
    re.IGNORECASE,
)
CITATION_CONTINUATION_RE = re.compile(r"(?i)(?<!\w)(?:ibid\.?|id\.)(?!\w)")
LEAD_IN_RE = re.compile(r"(?s)(:|—|--)[ \t]*$")
LIST_START_RE = re.compile(r"^[ \t]*(?:\([a-zA-Z0-9ivxIVX]+\)|[-*•])(?=[ \t]+)")


def _deps(blocks: dict[str, Any], atoms: dict[str, Any], sidecars: dict[str, Any], policy_hash: str) -> dict[str, str]:
    return {
        "sourceblock_cache_key": blocks["cache_key"],
        "sentence_atom_cache_key": atoms["cache_key"],
        "sidecar_cache_key": sidecars["cache_key"],
        "sourceblock_policy_sha256": blocks["policy_sha256"],
        "sentence_policy_sha256": atoms["policy_sha256"],
        "sidecar_policy_sha256": sidecars["policy_sha256"],
        "context_hint_policy_sha256": policy_hash,
    }


def _hint(*, blocks: dict[str, Any], atoms: dict[str, Any], sidecars: dict[str, Any], policy_hash: str,
          target: dict[str, Any], hint_type: str, direction: str, related: list[dict[str, Any]],
          evidence: list[dict[str, Any]], status: str, rule_id: str, rule_version: str) -> dict[str, Any]:
    payload = {
        "identity_contract": "context-hint-id-v1",
        "case_id": blocks["case_id"], "source_hash": blocks["source_hash"],
        "target_block_id": target["block_id"], "target_span": target["span"],
        "hint_type": hint_type, "direction": direction,
        "related_block_ids": [item["block_id"] for item in related],
        "related_spans": [item["span"] for item in related],
        "evidence_spans": evidence, "status": status,
        "rule_id": rule_id, "rule_version": rule_version,
        "producer": "deterministic_local_rule",
        "dependencies": _deps(blocks, atoms, sidecars, policy_hash),
    }
    identity = canonical_hash(payload)
    return {"record_type": "ContextHint", "hint_id": f"ch-{identity[:24]}", **{k: v for k, v in payload.items() if k != "identity_contract"}}


def _continuation_hints(text: str, blocks: dict[str, Any], atoms: dict[str, Any], sidecars: dict[str, Any], policy: dict[str, Any], policy_hash: str) -> list[dict[str, Any]]:
    by_id = {item["block_id"]: item for item in blocks["blocks"]}; output = []
    for relation in sidecars["relations"]:
        if relation["relation_type"] != "continuation":
            continue
        source, target = by_id[relation["source_ref"]], by_id[relation["target_ref"]]
        if relation["relation_subtype"] == "open_quote_to_next_block":
            output.append(_hint(blocks=blocks, atoms=atoms, sidecars=sidecars, policy_hash=policy_hash,
                target=target, hint_type="quote_continuation", direction="previous", related=[source],
                evidence=relation["evidence_spans"], status="accepted_by_contract",
                rule_id="quote_continuation", rule_version=policy["rules"]["quote_continuation"]))
            output.append(_hint(blocks=blocks, atoms=atoms, sidecars=sidecars, policy_hash=policy_hash,
                target=source, hint_type="open_quote", direction="next", related=[target],
                evidence=relation["evidence_spans"], status="accepted_by_contract",
                rule_id="open_quote", rule_version=policy["rules"]["open_quote"]))
        elif relation["relation_subtype"] == "lead_in_to_list":
            output.append(_hint(blocks=blocks, atoms=atoms, sidecars=sidecars, policy_hash=policy_hash,
                target=target, hint_type="open_list", direction="previous", related=[source],
                evidence=relation["evidence_spans"], status="accepted_by_contract",
                rule_id="open_list", rule_version=policy["rules"]["open_list"]))
    return output


def _lead_in_hints(text: str, blocks: dict[str, Any], atoms: dict[str, Any], sidecars: dict[str, Any], policy: dict[str, Any], policy_hash: str) -> list[dict[str, Any]]:
    output = []; rows = blocks["blocks"]
    for index, source in enumerate(rows[:-1]):
        raw = text[source["content_span"]["start_char"]:source["content_span"]["end_char"]].rstrip()
        match = LEAD_IN_RE.search(raw)
        if not match:
            continue
        target = rows[index + 1]
        start = source["content_span"]["start_char"] + match.start(1)
        output.append(_hint(blocks=blocks, atoms=atoms, sidecars=sidecars, policy_hash=policy_hash,
            target=target, hint_type="dependent_lead_in", direction="previous", related=[source],
            evidence=[span(blocks["case_id"], blocks["source_hash"], start, start + len(match.group(1)))], status="candidate",
            rule_id="dependent_lead_in", rule_version=policy["rules"]["dependent_lead_in"]))
    return output


def _reference_hints(text: str, blocks: dict[str, Any], atoms: dict[str, Any], sidecars: dict[str, Any], policy: dict[str, Any], policy_hash: str) -> list[dict[str, Any]]:
    output = []; rows = blocks["blocks"]
    for index, target in enumerate(rows):
        ref = target["content_span"]; raw = text[ref["start_char"]:ref["end_char"]]
        match = REFERENCE_RE.search(raw)
        if not match:
            continue
        evidence = [span(blocks["case_id"], blocks["source_hash"], ref["start_char"] + match.start(), ref["start_char"] + match.end())]
        related = [rows[index - 1]] if index else []
        output.append(_hint(blocks=blocks, atoms=atoms, sidecars=sidecars, policy_hash=policy_hash,
            target=target, hint_type="reference_to_previous", direction="previous", related=related,
            evidence=evidence, status="candidate" if related else "unresolved",
            rule_id="reference_to_previous", rule_version=policy["rules"]["reference_to_previous"]))
    return output


def _citation_hints(text: str, blocks: dict[str, Any], atoms: dict[str, Any], sidecars: dict[str, Any], policy: dict[str, Any], policy_hash: str) -> list[dict[str, Any]]:
    output = []; rows = blocks["blocks"]
    for index, target in enumerate(rows):
        ref = target["content_span"]; raw = text[ref["start_char"]:ref["end_char"]]
        match = CITATION_CONTINUATION_RE.search(raw[:80])
        if not match:
            continue
        evidence = [span(blocks["case_id"], blocks["source_hash"], ref["start_char"] + match.start(), ref["start_char"] + match.end())]
        related = [rows[index - 1]] if index else []
        output.append(_hint(blocks=blocks, atoms=atoms, sidecars=sidecars, policy_hash=policy_hash,
            target=target, hint_type="citation_continuation", direction="previous", related=related,
            evidence=evidence, status="candidate" if related else "unresolved",
            rule_id="citation_continuation", rule_version=policy["rules"]["citation_continuation"]))
    return output


def _speaker_hints(text: str, blocks: dict[str, Any], atoms: dict[str, Any], sidecars: dict[str, Any], policy: dict[str, Any], policy_hash: str) -> list[dict[str, Any]]:
    rows = blocks["blocks"]; by_block: dict[str, list[dict[str, Any]]] = defaultdict(list); output = []
    for item in sidecars["annotations"]:
        if item["annotation_type"] == "speaker_cue": by_block[item["block_id"]].append(item)
    for index in range(1, len(rows)):
        previous, target = rows[index - 1], rows[index]
        left, right = by_block[previous["block_id"]], by_block[target["block_id"]]
        common = sorted({item["value_code"] for item in left} & {item["value_code"] for item in right})
        if not common: continue
        evidence = [next(item["span"] for item in left if item["value_code"] == common[0]), next(item["span"] for item in right if item["value_code"] == common[0])]
        output.append(_hint(blocks=blocks, atoms=atoms, sidecars=sidecars, policy_hash=policy_hash,
            target=target, hint_type="speaker_continuity_candidate", direction="previous", related=[previous],
            evidence=evidence, status="candidate", rule_id="speaker_continuity_candidate",
            rule_version=policy["rules"]["speaker_continuity_candidate"]))
    return output


RULES: dict[str, Callable[..., list[dict[str, Any]]]] = {
    "quote_continuation": _continuation_hints,
    "open_quote": lambda *args: [],
    "open_list": lambda *args: [],
    "dependent_lead_in": _lead_in_hints,
    "reference_to_previous": _reference_hints,
    "citation_continuation": _citation_hints,
    "speaker_continuity_candidate": _speaker_hints,
}


def _event(case_id: str, source_hash: str, rule: str, rule_version: str, policy_hash: str, exc: Exception) -> dict[str, Any]:
    payload = {"event_type": "rule_failure", "case_id": case_id, "source_hash": source_hash, "rule_id": rule, "rule_version": rule_version, "producer": "deterministic_local_rule", "policy_sha256": policy_hash, "severity": "error", "status": "error", "message_code": "rule_failure_isolated", "message": f"Rule {rule} failed locally: {type(exc).__name__}"}
    return {"event_id": f"he-{canonical_hash(payload)[:20]}", **payload}


def _apply_policy(candidates: list[dict[str, Any]], policy: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    priority = {name: index for index, name in enumerate(policy["priority"])}
    candidates = sorted(candidates, key=lambda h: (priority[h["hint_type"]], h["target_span"]["start_char"], h["hint_id"]))
    kept, ledger, seen = [], [], set(); target_hints = defaultdict(int); target_related = defaultdict(set); target_chars = defaultdict(int)
    caps = policy["caps"]
    for item in candidates:
        related_key = tuple((r["start_char"], r["end_char"]) for r in item["related_spans"])
        key = (item["target_block_id"], item["hint_type"], item["direction"], related_key)
        reason = None
        if key in seen: reason = "duplicate_canonical_key"
        elif len(kept) >= caps["max_hints_per_case"]: reason = "case_hint_cap"
        elif target_hints[item["target_block_id"]] >= caps["max_hints_per_target"]: reason = "target_hint_cap"
        else:
            new_blocks = set(item["related_block_ids"]) - target_related[item["target_block_id"]]
            new_chars = sum(ref["end_char"] - ref["start_char"] for bid, ref in zip(item["related_block_ids"], item["related_spans"]) if bid in new_blocks)
            if len(target_related[item["target_block_id"]] | new_blocks) > caps["max_related_blocks_per_target"]: reason = "related_block_cap"
            elif target_chars[item["target_block_id"]] + new_chars > caps["max_related_chars_per_target"]: reason = "related_char_cap"
        ledger.append({"proposal_id": item["hint_id"], "target_block_id": item["target_block_id"], "hint_type": item["hint_type"], "action": "dropped" if reason else "kept", "reason": reason or "within_policy"})
        if reason: continue
        seen.add(key); kept.append(item); target_hints[item["target_block_id"]] += 1
        for bid, ref in zip(item["related_block_ids"], item["related_spans"]):
            if bid not in target_related[item["target_block_id"]]: target_chars[item["target_block_id"]] += ref["end_char"] - ref["start_char"]
            target_related[item["target_block_id"]].add(bid)
    return sorted(kept, key=lambda h: (h["target_span"]["start_char"], h["hint_type"], h["hint_id"])), ledger


def run_context_hint_rules(text: str, blocks: dict[str, Any], atoms: dict[str, Any], sidecars: dict[str, Any], policy: dict[str, Any], policy_hash: str | None = None, fault_rules: set[str] | None = None) -> dict[str, Any]:
    policy_hash = policy_hash or canonical_hash(policy); faults = fault_rules or set(); candidates = []; runs = []; events = []
    for rule in policy["priority"]:
        before = len(candidates)
        try:
            if rule in faults: raise RuntimeError("injected rule failure")
            if rule == "quote_continuation":
                produced = _continuation_hints(text, blocks, atoms, sidecars, policy, policy_hash)
            elif rule in {"open_quote", "open_list"}:
                produced = []
            else:
                produced = RULES[rule](text, blocks, atoms, sidecars, policy, policy_hash)
            if rule == "quote_continuation": produced = [h for h in produced if h["hint_type"] == "quote_continuation"]
            elif rule in {"open_quote", "open_list"}: produced = [h for h in _continuation_hints(text, blocks, atoms, sidecars, policy, policy_hash) if h["hint_type"] == rule]
            candidates.extend(produced); runs.append({"rule_id": rule, "rule_version": policy["rules"][rule], "status": "complete", "output_count": len(candidates) - before})
        except Exception as exc:
            events.append(_event(blocks["case_id"], blocks["source_hash"], rule, policy["rules"][rule], policy_hash, exc)); runs.append({"rule_id": rule, "rule_version": policy["rules"][rule], "status": "failed", "output_count": 0})
    hints, ledger = _apply_policy(candidates, policy); failed = sorted(r["rule_id"] for r in runs if r["status"] == "failed")
    cache_payload = {"case_id": blocks["case_id"], "source_hash": blocks["source_hash"], "sourceblock_cache_key": blocks["cache_key"], "sentence_atom_cache_key": atoms["cache_key"], "sidecar_cache_key": sidecars["cache_key"], "rule_bundle_version": policy["rule_bundle_version"], "policy_sha256": policy_hash, "failed_rules": failed}
    return {"artifact_type": "ContextHintMap", "schema_version": policy["schema_version"], "case_id": blocks["case_id"], "source_hash": blocks["source_hash"], "sourceblock_cache_key": blocks["cache_key"], "sentence_atom_cache_key": atoms["cache_key"], "sidecar_cache_key": sidecars["cache_key"], "rule_bundle_version": policy["rule_bundle_version"], "policy_sha256": policy_hash, "cache_key": canonical_hash(cache_payload), "run_status": "partial" if failed else "complete", "failed_rules": failed, "rule_runs": runs, "target_block_ids": [b["block_id"] for b in blocks["blocks"]], "pre_policy_count": len(candidates), "post_policy_count": len(hints), "hints": hints, "policy_ledger": ledger, "rule_events": sorted(events, key=lambda e: e["rule_id"])}
