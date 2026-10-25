"""Four-arm, source-grounded diagnostic of V14 selection failures.

The predeclared opportunities are saved outside every model payload. This does
not build a KB, and its agent-review labels are not human gold.
"""

from __future__ import annotations

import json
from pathlib import Path

from .endpoint import ModelProtocolError
from .schema_v10 import obj, string_enum, validate
from .schema_v14 import (extraction_schema, response_format, schema_hash,
                         validate_extraction)
from .source import (compact_opened_sources, digest, load_source, save,
                     source_handles, source_structure)

VERSION = "v14-real-source-selection-2x2-2"
CASE_ID = "099980"
SMALL_IDS = ("P0000", "P0003", "P0193", "P0204")
LARGE_IDS = tuple(f"P{index:04d}" for index in range(19)) + tuple(
    f"P{index:04d}" for index in range(193, 205))
OPPORTUNITIES = (
    ("P0000", "negative_heading", "Heading alone has no brief or AU content"),
    ("P0003", "au_rule", "Statutory grounds and conditions for Commission action"),
    ("P0193", "au_reasoning", "Court's reasoning on increased costs"),
    ("P0204", "brief_disposition", "Operative declaration and orders"),
)
SYSTEM = (
    "Examine the supplied judgment source for a source-grounded Case brief and "
    "legal authority units (AUs). A brief may preserve facts, posture, issues "
    "or disposition. An AU preserves a legal rule, condition, exception, "
    "application, evidence assessment or procedural reasoning; it need not cite "
    "another authority. A bare heading is neither. Choose only supported "
    "source handles; do not generate text or infer unseen source. If sentence "
    "selection is offered, use it when a whole paragraph mixes functions. "
    "For a paragraph-and-sentence schema, a paragraph chosen as skip, "
    "uncertain, brief, aus or both requires all its child sentence keys to be "
    "skip. Choose paragraph=sentences only when selecting at least one child "
    "sentence; do not select a parent and its children together. "
    "Return only the object required by response_format."
)
LABELS = ("skip", "uncertain", "brief", "aus", "both")


def source_groups(row: dict) -> tuple[dict, dict[str, list[dict]]]:
    if row["case_id"] != CASE_ID:
        raise ValueError("selection_diagnostic_case_mismatch")
    text, source_hash = load_source(row["source"])
    if source_hash != row["source_hash"]:
        raise ValueError("selection_diagnostic_source_hash_mismatch")
    _, units = source_structure(text, source_hash)
    source_map = {unit["source_id"]: unit for unit in units}
    handles, reverse = source_handles(units)
    groups = {}
    for name, selected in (("small", SMALL_IDS), ("large", LARGE_IDS)):
        opened = set()
        for alias in selected:
            paragraph = source_map[reverse[alias]]
            opened.add(paragraph["source_id"])
            opened.update(paragraph["sentence_ids"])
        groups[name] = compact_opened_sources(source_map, opened, handles)
        if [paragraph["source_id"] for paragraph in groups[name]] != list(selected):
            raise ValueError("selection_diagnostic_group_mismatch")
    inventory = {"case_id": CASE_ID, "source": str(Path(row["source"]).resolve()),
        "source_hash": source_hash, "annotation_type": "agent_review_not_gold",
        "small_paragraph_ids": list(SMALL_IDS),
        "large_paragraph_ids": list(LARGE_IDS),
        "opportunities": [{"source_id": alias, "review_label": label,
            "note": note, "start": source_map[reverse[alias]]["start"],
            "end": source_map[reverse[alias]]["end"],
            "text_hash": digest(source_map[reverse[alias]]["text"].encode("utf-8"))}
            for alias, label, note in OPPORTUNITIES]}
    return inventory, groups


def cases(row: dict) -> tuple[dict, list[dict]]:
    inventory, groups = source_groups(row)
    arms = []
    for size, shape in (("small", "paragraph"), ("small", "paragraph_sentence"),
                        ("large", "paragraph"), ("large", "paragraph_sentence")):
        paragraphs = groups[size]
        payload = {"case_id": CASE_ID, "source_hash": row["source_hash"],
            "opened_sources": paragraphs,
            "source_scope_note": "Only fully supplied source may be selected."}
        if shape == "paragraph":
            schema = obj({"choices": obj({paragraph["source_id"]: string_enum(LABELS)
                for paragraph in paragraphs})})
        else:
            schema = extraction_schema([], paragraphs, {})
        arms.append({"name": f"{size}_{shape}", "size": size, "shape": shape,
                     "payload": payload, "schema": schema})
    return inventory, arms


def assess(answer: dict, arm: dict, inventory: dict) -> dict:
    choices = answer["choices"]
    paragraphs = {paragraph["source_id"]: paragraph for paragraph in
                  arm["payload"]["opened_sources"]}
    observations = []
    for opportunity in inventory["opportunities"]:
        alias, label = opportunity["source_id"], opportunity["review_label"]
        parent_choice = choices[alias]
        selected = [parent_choice]
        if parent_choice == "sentences":
            selected = [choices[sentence["source_id"]] for sentence in
                        paragraphs[alias]["sentences"]]
        expected = ({"au_rule": {"aus", "both"},
                     "au_reasoning": {"aus", "both"},
                     "brief_disposition": {"brief", "both"},
                     "negative_heading": {"skip"}}[label])
        matched = (parent_choice == "skip" if label == "negative_heading"
                   else bool(set(selected) & expected))
        observations.append({"source_id": alias, "review_label": label,
            "parent_choice": parent_choice, "selected_labels": selected,
            "matches_predeclared_opportunity": matched})
    return {"opportunities": observations,
        "positive_hits": sum(entry["matches_predeclared_opportunity"] for entry in
                             observations if entry["review_label"] != "negative_heading"),
        "heading_skipped": observations[0]["matches_predeclared_opportunity"],
        "non_skip_fields": sum(value != "skip" for value in choices.values()),
        "choice_fields": len(choices)}


def _usage(cache_path: Path) -> dict:
    raw_path = cache_path.with_suffix(".raw.json")
    if not raw_path.exists():
        return {}
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    return {"finish_reason": raw.get("finish_reason"),
            "usage": raw.get("provider_response", {}).get("usage", {})}


def probe(endpoint, config: dict, experiment: Path, fingerprint: dict,
          row: dict, *, large_only: bool = False) -> dict:
    inventory, arms = cases(row)
    indexed_arms = [(index, arm) for index, arm in enumerate(arms)
                    if not large_only or arm["size"] == "large"]
    inventory_path = experiment / "locked_opportunities.json"
    if inventory_path.exists():
        if json.loads(inventory_path.read_text(encoding="utf-8")) != inventory:
            raise ValueError("selection_diagnostic_inventory_changed")
    else:
        save(inventory_path, inventory)
    report_path = experiment / "selection_diagnostic.json"
    report = {"status": "in_progress", "fingerprint": fingerprint,
              "inventory_hash": digest(json.dumps(inventory, sort_keys=True).encode()),
              "results": []}
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if report.get("fingerprint") != fingerprint or report.get(
                "inventory_hash") != digest(json.dumps(inventory, sort_keys=True).encode()):
            raise ValueError("selection_diagnostic_fingerprint_mismatch")
        if report["status"] in {"complete", "failed"}:
            return report
    for position, (index, arm) in enumerate(indexed_arms):
        signature = schema_hash(arm["schema"])
        if position < len(report["results"]):
            previous = report["results"][position]
            if previous["name"] != arm["name"] or previous[
                    "schema_hash"] != signature or previous["protocol_errors"]:
                raise ValueError("selection_diagnostic_arm_mismatch")
            continue
        identity = {"experiment": str(experiment.resolve()),
            "fingerprint": fingerprint, "index": index,
            "name": arm["name"], "schema_hash": signature,
            "payload_hash": digest(json.dumps(arm["payload"], sort_keys=True,
                ensure_ascii=False).encode("utf-8")), "system_hash": digest(SYSTEM.encode())}
        request_id = "v14:selection-diagnostic:" + str(index) + ":" + digest(
            json.dumps(identity, sort_keys=True).encode())[:20]
        cache_path = experiment / "responses" / f"arm_{index}.json"
        try:
            answer = endpoint.complete(config["reader"], SYSTEM, arm["payload"],
                request_id=request_id, metadata={"experiment": experiment.name,
                    "stage": "selection_diagnostic", "case_id": CASE_ID,
                    "turn": index, "schema_version": 14,
                    "diagnostic_version": VERSION, "schema_hash": signature},
                cache_path=cache_path,
                response_format=response_format(arm["schema"]))
        except ModelProtocolError:
            report["status"] = "failed"
            report["failure"] = {"arm": arm["name"], "code": "truncated_or_invalid_json",
                "raw_response": str(cache_path.with_suffix(".raw.json"))}
            save(report_path, report)
            return report
        errors = validate(answer, arm["schema"])
        if not errors and arm["shape"] == "paragraph_sentence":
            errors.extend(validate_extraction(answer,
                          arm["payload"]["opened_sources"]))
        result = {"name": arm["name"], "arm_index": index, "size": arm["size"],
            "shape": arm["shape"], "schema_hash": signature,
            "paragraph_count": len(arm["payload"]["opened_sources"]),
            "source_characters": sum(len(paragraph["text"]) for paragraph in
                                     arm["payload"]["opened_sources"]),
            "response": answer, "protocol_errors": errors,
            "provider": _usage(cache_path)}
        if not errors:
            result["assessment"] = assess(answer, arm, inventory)
        report["results"].append(result)
        report["status"] = "failed" if errors else "in_progress"
        save(report_path, report)
        if errors:
            return report
    report["status"] = "complete"
    save(report_path, report)
    return report
