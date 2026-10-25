"""Replaceable rule workers for Plan 05 sidecars."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Callable

from ..sentence_atoms.segmenter import canonical_hash, span

SUPPRESSION_RE = re.compile(r"(?:<|\[)(FRAGMENT_SUPPRESSED|REFERENCE_SUPPRESSED|CITATION_SUPPRESSED)(?:>|\])")
SPEAKER_PATTERNS = [
    (re.compile(r"(?i)\b(?:the applicant|the respondent|counsel)\s+(?:submits?|argues?|contends?|states?|says?)\b"), "party_language_cue"),
    (re.compile(r"(?i)\b(?:the Court|this Court|the Board|the officer)\s+(?:finds?|found|holds?|held|concludes?|concluded|determines?|determined)\b"), "institutional_language_cue"),
    (re.compile(r"(?i)\bI\s+(?:find|conclude|hold|determine)\b"), "first_person_decision_cue"),
]
FORMAL_HEADING_RE = re.compile(r"^(?:[IVXLC]+\.\s+.+|INTRODUCTION|BACKGROUND|FACTS|ISSUES?|ANALYSIS|CONCLUSION|ORDER|DECISION|LEGAL PROCEEDINGS|STANDARD OF REVIEW|REASONS(?: FOR (?:JUDGMENT|ORDER))?)$", re.IGNORECASE)


def _deps(sourceblocks: dict[str, Any], atoms: dict[str, Any], policy_hash: str) -> dict[str, str]:
    return {"sourceblock_cache_key": sourceblocks["cache_key"], "sentence_atom_cache_key": atoms["cache_key"], "sourceblock_policy_sha256": sourceblocks["policy_sha256"], "sentence_policy_sha256": atoms["policy_sha256"], "sidecar_policy_sha256": policy_hash}


def _atom_refs(atom_map: dict[str, Any], start: int, end: int) -> list[str]:
    return [atom["atom_id"] for atom in atom_map["atoms"] if atom["span"]["start_char"] < end and atom["span"]["end_char"] > start]


def _annotation(*, case_id: str, source_hash: str, start: int, end: int, block_id: str, atom_map: dict[str, Any], worker: str, annotation_type: str, value_code: str, status: str, version: str, evidence_refs: list[str], dependencies: dict[str, str]) -> dict[str, Any]:
    payload = {"identity_contract": "annotation-id-v1", "case_id": case_id, "source_hash": source_hash, "span": {"start_char": start, "end_char": end}, "block_id": block_id, "atom_refs": _atom_refs(atom_map, start, end), "worker_type": worker, "annotation_type": annotation_type, "value_code": value_code, "status": status, "producer_version": version, "evidence_refs": sorted(set(evidence_refs)), "dependencies": dependencies}
    return {"record_type": "Annotation", "annotation_id": f"an-{canonical_hash(payload)[:24]}", **{key: value for key, value in payload.items() if key != "identity_contract"}, "span": span(case_id, source_hash, start, end)}


def marker_worker(text: str, sourceblocks: dict[str, Any], atom_map: dict[str, Any], policy: dict[str, Any], policy_hash: str) -> list[dict[str, Any]]:
    case_id, source_hash = sourceblocks["case_id"], sourceblocks["source_hash"]
    version, dependencies = policy["workers"]["marker_rule"], _deps(sourceblocks, atom_map, policy_hash)
    output = []
    for block in sourceblocks["blocks"]:
        marker = block["marker_span"]
        if marker is not None:
            output.append(_annotation(case_id=case_id, source_hash=source_hash, start=marker["start_char"], end=marker["end_char"], block_id=block["block_id"], atom_map=atom_map, worker="marker_rule", annotation_type="paragraph_marker", value_code="numbered_paragraph_marker", status="observed", version=version, evidence_refs=[block["block_id"]], dependencies=dependencies))
        start, end = block["span"]["start_char"], block["span"]["end_char"]
        for match in SUPPRESSION_RE.finditer(text[start:end]):
            absolute_start, absolute_end = start + match.start(), start + match.end()
            output.append(_annotation(case_id=case_id, source_hash=source_hash, start=absolute_start, end=absolute_end, block_id=block["block_id"], atom_map=atom_map, worker="marker_rule", annotation_type="suppression_marker", value_code=match.group(1).lower(), status="observed", version=version, evidence_refs=[block["block_id"]], dependencies=dependencies))
    return output


def citation_worker(text: str, sourceblocks: dict[str, Any], atom_map: dict[str, Any], policy: dict[str, Any], policy_hash: str) -> list[dict[str, Any]]:
    case_id, source_hash = sourceblocks["case_id"], sourceblocks["source_hash"]
    version, dependencies = policy["workers"]["citation_reference_rule"], _deps(sourceblocks, atom_map, policy_hash)
    blocks = {block["block_id"]: block for block in sourceblocks["blocks"]}
    mapping = {"citation_year": ("citation_year", "bracketed_citation_year"), "reporter_citation": ("reporter_citation", "reporter_or_neutral_citation"), "section_reference": ("section_reference", "section_or_paragraph_reference"), "case_name": ("case_reference", "case_name_with_v")}
    grouped: dict[tuple[Any, ...], list[str]] = defaultdict(list)
    for protected in atom_map["protected_spans"]:
        if protected["span_type"] not in mapping:
            continue
        annotation_type, value_code = mapping[protected["span_type"]]
        ref = protected["span"]
        if annotation_type == "reporter_citation" and re.match(r"\d{4}\s+(?:SCC|FC|FCA|FCT|CanLII)\s+\d+", text[ref["start_char"]:ref["end_char"]]):
            annotation_type, value_code = "neutral_citation", "neutral_citation_pattern"
        key = (protected["parent_block_id"], ref["start_char"], ref["end_char"], annotation_type, value_code)
        grouped[key].extend([protected["protected_span_id"], blocks[protected["parent_block_id"]]["block_id"]])
    return [_annotation(case_id=case_id, source_hash=source_hash, start=start, end=end, block_id=block_id, atom_map=atom_map, worker="citation_reference_rule", annotation_type=annotation_type, value_code=value_code, status="candidate", version=version, evidence_refs=evidence, dependencies=dependencies) for (block_id, start, end, annotation_type, value_code), evidence in grouped.items()]


def nested_worker(text: str, sourceblocks: dict[str, Any], atom_map: dict[str, Any], policy: dict[str, Any], policy_hash: str) -> list[dict[str, Any]]:
    case_id, source_hash = sourceblocks["case_id"], sourceblocks["source_hash"]
    version, dependencies = policy["workers"]["nested_structure_inheritance"], _deps(sourceblocks, atom_map, policy_hash)
    grouped: dict[tuple[Any, ...], list[str]] = defaultdict(list)
    for protected in atom_map["protected_spans"]:
        if protected["span_type"] not in {"balanced_quotation", "unbalanced_quotation", "list_marker"}:
            continue
        ref = protected["span"]
        annotation_type = "nested_list" if protected["span_type"] == "list_marker" else "nested_quote"
        value_code = protected["span_type"]
        status = "review" if protected["span_type"] == "unbalanced_quotation" else "observed"
        key = (protected["parent_block_id"], ref["start_char"], ref["end_char"], annotation_type, value_code, status)
        grouped[key].append(protected["protected_span_id"])
    return [_annotation(case_id=case_id, source_hash=source_hash, start=start, end=end, block_id=block_id, atom_map=atom_map, worker="nested_structure_inheritance", annotation_type=annotation_type, value_code=value_code, status=status, version=version, evidence_refs=evidence, dependencies=dependencies) for (block_id, start, end, annotation_type, value_code, status), evidence in grouped.items()]


def quote_balance_worker(text: str, sourceblocks: dict[str, Any], atom_map: dict[str, Any], policy: dict[str, Any], policy_hash: str) -> list[dict[str, Any]]:
    case_id, source_hash = sourceblocks["case_id"], sourceblocks["source_hash"]
    version, dependencies = policy["workers"]["quote_balance_rule"], _deps(sourceblocks, atom_map, policy_hash)
    grouped: dict[tuple[Any, ...], list[str]] = defaultdict(list)
    for protected in atom_map["protected_spans"]:
        if protected["span_type"] not in {"balanced_quotation", "unbalanced_quotation"}:
            continue
        ref, balanced = protected["span"], protected["span_type"] == "balanced_quotation"
        value_code, status = ("balanced", "observed") if balanced else ("unbalanced", "review")
        key = (protected["parent_block_id"], ref["start_char"], ref["end_char"], value_code, status)
        grouped[key].append(protected["protected_span_id"])
    return [_annotation(case_id=case_id, source_hash=source_hash, start=start, end=end, block_id=block_id, atom_map=atom_map, worker="quote_balance_rule", annotation_type="quote_balance", value_code=value_code, status=status, version=version, evidence_refs=evidence, dependencies=dependencies) for (block_id, start, end, value_code, status), evidence in grouped.items()]


def speaker_cue_worker(text: str, sourceblocks: dict[str, Any], atom_map: dict[str, Any], policy: dict[str, Any], policy_hash: str) -> list[dict[str, Any]]:
    case_id, source_hash = sourceblocks["case_id"], sourceblocks["source_hash"]
    version, dependencies = policy["workers"]["speaker_cue_rule"], _deps(sourceblocks, atom_map, policy_hash)
    output = []
    for block in sourceblocks["blocks"]:
        start, end = block["span"]["start_char"], block["span"]["end_char"]
        fragment = text[start:end]
        for regex, value_code in SPEAKER_PATTERNS:
            for match in regex.finditer(fragment):
                absolute_start, absolute_end = start + match.start(), start + match.end()
                output.append(_annotation(case_id=case_id, source_hash=source_hash, start=absolute_start, end=absolute_end, block_id=block["block_id"], atom_map=atom_map, worker="speaker_cue_rule", annotation_type="speaker_cue", value_code=value_code, status="candidate", version=version, evidence_refs=[block["block_id"]], dependencies=dependencies))
    return output


WORKERS: dict[str, Callable[..., list[dict[str, Any]]]] = {
    "marker_rule": marker_worker,
    "citation_reference_rule": citation_worker,
    "nested_structure_inheritance": nested_worker,
    "quote_balance_rule": quote_balance_worker,
    "speaker_cue_rule": speaker_cue_worker,
}


def _relation(case_id: str, source_hash: str, relation_type: str, subtype: str, source_ref: str, target_ref: str, status: str, evidence_spans: list[dict[str, Any]], evidence_refs: list[str], version: str, dependencies: dict[str, str]) -> dict[str, Any]:
    payload = {"identity_contract": "structural-relation-id-v1", "case_id": case_id, "source_hash": source_hash, "relation_type": relation_type, "relation_subtype": subtype, "source_ref": source_ref, "target_ref": target_ref, "direction": "outgoing", "status": status, "evidence_spans": evidence_spans, "evidence_refs": sorted(set(evidence_refs)), "producer_version": version, "dependencies": dependencies, "reconstructable": False}
    return {"record_type": "StructuralRelation", "relation_id": f"sr-{canonical_hash(payload)[:24]}", **{key: value for key, value in payload.items() if key != "identity_contract"}}


def relation_worker(text: str, sourceblocks: dict[str, Any], atom_map: dict[str, Any], annotations: list[dict[str, Any]], policy: dict[str, Any], policy_hash: str) -> list[dict[str, Any]]:
    case_id, source_hash = sourceblocks["case_id"], sourceblocks["source_hash"]
    version, dependencies = policy["workers"]["structural_relation_rule"], _deps(sourceblocks, atom_map, policy_hash)
    blocks = sourceblocks["blocks"]
    block_index = {block["block_id"]: index for index, block in enumerate(blocks)}
    output = []
    for annotation in annotations:
        if annotation["annotation_type"] in {"nested_quote", "nested_list"}:
            output.append(_relation(case_id, source_hash, "containment", annotation["annotation_type"], annotation["annotation_id"], annotation["block_id"], "observed", [annotation["span"]], [annotation["annotation_id"]], version, dependencies))
        if annotation["annotation_type"] == "nested_quote" and annotation["value_code"] == "unbalanced_quotation":
            index = block_index[annotation["block_id"]]
            if index + 1 < len(blocks) and annotation["span"]["end_char"] == blocks[index]["span"]["end_char"]:
                output.append(_relation(case_id, source_hash, "continuation", "open_quote_to_next_block", annotation["block_id"], blocks[index + 1]["block_id"], "candidate", [annotation["span"]], [annotation["annotation_id"]], version, dependencies))
    list_by_block = defaultdict(list)
    for annotation in annotations:
        if annotation["annotation_type"] == "nested_list":
            list_by_block[annotation["block_id"]].append(annotation)
    for index, block in enumerate(blocks[:-1]):
        current = text[block["span"]["start_char"]:block["span"]["end_char"]].rstrip()
        next_block = blocks[index + 1]
        candidates = list_by_block.get(next_block["block_id"], [])
        if current.endswith(":") and candidates:
            colon_start = block["span"]["start_char"] + len(current) - 1
            output.append(_relation(case_id, source_hash, "continuation", "lead_in_to_list", block["block_id"], next_block["block_id"], "candidate", [span(case_id, source_hash, colon_start, colon_start + 1), candidates[0]["span"]], [block["block_id"], candidates[0]["annotation_id"]], version, dependencies))
    active_heading = None
    for block in blocks:
        ref = block["content_span"]
        content = text[ref["start_char"]:ref["end_char"]].strip()
        if block["block_type"] == "heading_candidate":
            active_heading = block if FORMAL_HEADING_RE.fullmatch(content) else None
            continue
        if active_heading is not None:
            output.append(_relation(case_id, source_hash, "governed_by_heading", "formal_heading_candidate", block["block_id"], active_heading["block_id"], "candidate", [active_heading["content_span"]], [active_heading["block_id"]], version, dependencies))
    return output


def _worker_event(case_id: str, source_hash: str, worker: str, exc: Exception) -> dict[str, Any]:
    message_code = "worker_failure_isolated"
    message = f"Worker {worker} failed locally: {type(exc).__name__}"
    payload = {"worker_type": worker, "severity": "error", "status": "error", "case_id": case_id, "source_hash": source_hash, "message_code": message_code, "message": message}
    return {"event_id": f"we-{canonical_hash(payload)[:20]}", **payload}


def run_sidecar_workers(text: str, sourceblocks: dict[str, Any], atom_map: dict[str, Any], policy: dict[str, Any], policy_hash: str, fault_workers: set[str] | None = None) -> dict[str, Any]:
    case_id, source_hash = sourceblocks["case_id"], sourceblocks["source_hash"]
    faults = fault_workers or set()
    annotations: list[dict[str, Any]] = []
    relations: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    runs = []
    for worker, function in WORKERS.items():
        before = len(annotations)
        try:
            if worker in faults:
                raise RuntimeError("injected worker failure")
            annotations.extend(function(text, sourceblocks, atom_map, policy, policy_hash))
            runs.append({"worker_type": worker, "producer_version": policy["workers"][worker], "status": "complete", "output_count": len(annotations) - before})
        except Exception as exc:
            events.append(_worker_event(case_id, source_hash, worker, exc))
            runs.append({"worker_type": worker, "producer_version": policy["workers"][worker], "status": "failed", "output_count": 0})
    annotations.sort(key=lambda item: (item["span"]["start_char"], item["span"]["end_char"], item["worker_type"], item["annotation_id"]))
    try:
        if "structural_relation_rule" in faults:
            raise RuntimeError("injected worker failure")
        relations = relation_worker(text, sourceblocks, atom_map, annotations, policy, policy_hash)
        runs.append({"worker_type": "structural_relation_rule", "producer_version": policy["workers"]["structural_relation_rule"], "status": "complete", "output_count": len(relations)})
    except Exception as exc:
        events.append(_worker_event(case_id, source_hash, "structural_relation_rule", exc))
        runs.append({"worker_type": "structural_relation_rule", "producer_version": policy["workers"]["structural_relation_rule"], "status": "failed", "output_count": 0})
    relations.sort(key=lambda item: (item["relation_type"], item["source_ref"], item["target_ref"], item["relation_id"]))
    dependencies = _deps(sourceblocks, atom_map, policy_hash)
    cache_key = canonical_hash({"case_id": case_id, "source_hash": source_hash, "sourceblock_cache_key": sourceblocks["cache_key"], "sentence_atom_cache_key": atom_map["cache_key"], "worker_bundle_version": policy["worker_bundle_version"], "policy_sha256": policy_hash})
    failed = sorted(run["worker_type"] for run in runs if run["status"] == "failed")
    return {"artifact_type": "SidecarMap", "schema_version": policy["schema_version"], "case_id": case_id, "source_hash": source_hash, "sourceblock_cache_key": sourceblocks["cache_key"], "sentence_atom_cache_key": atom_map["cache_key"], "worker_bundle_version": policy["worker_bundle_version"], "policy_sha256": policy_hash, "cache_key": cache_key, "run_status": "partial" if failed else "complete", "failed_workers": failed, "worker_runs": runs, "annotations": annotations, "relations": relations, "worker_events": sorted(events, key=lambda item: (item["worker_type"], item["event_id"])), "adjacency_policy": policy["adjacency"]}
