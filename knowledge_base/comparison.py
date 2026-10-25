"""Offline review bundle; historical KOS never enters construction prompts."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .source import load_source, save, source_spans, source_structure


def _legacy_evidence(markdown: str) -> str | None:
    match = re.search(r"^## Evidence span\s*$([\s\S]*?)(?=^## |\Z)", markdown, re.MULTILINE)
    if not match:
        return None
    lines = [line[1:].lstrip() for line in match.group(1).splitlines() if line.startswith(">")]
    return "\n".join(lines) if lines else None


def _legacy_record(path: Path, text: str, addresses: list[dict], id_key: str) -> dict:
    markdown = path.read_text(encoding="utf-8-sig")
    quote = _legacy_evidence(markdown)
    location = {"status": "missing_evidence_section", "start": None, "end": None,
                "source_ids": []}
    if quote:
        count = text.count(quote)
        if count == 1:
            start = text.index(quote)
            end = start + len(quote)
            location = {"status": "exact", "start": start, "end": end,
                        "source_ids": [address[id_key] for address in addresses
                                       if address["start"] < end and address["end"] > start]}
        else:
            location["status"] = "absent" if count == 0 else "ambiguous"
    return {"path": str(path.resolve()), "markdown": markdown, "source_location": location}


def export_review(experiment: str | Path, kos: str | Path) -> Path:
    experiment, kos = Path(experiment), Path(kos)
    rows = []
    for path in sorted(experiment.glob("*/*/case.json")):
        result = json.loads(path.read_text(encoding="utf-8"))
        text, source_hash = load_source(result["source"])
        if source_hash != result["source_hash"]:
            raise ValueError("Comparison source hash changed")
        if result.get("schema_version") in {3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15}:
            _, addresses = source_structure(text, source_hash)
            id_key = "source_id"
        else:
            addresses = source_spans(text, source_hash)
            id_key = "span_id"
        case_dir = kos / "cases" / result["case_id"]
        case_markdown = (case_dir / "CASE.md").read_text(encoding="utf-8-sig")
        role_match = re.search(r"^role:\s*([^\r\n]+)", case_markdown, re.MULTILINE)
        legacy_paths = sorted((case_dir / "authority_units").glob("*.md"))
        legacy = [_legacy_record(legacy_path, text, addresses, id_key)
                  for legacy_path in legacy_paths]
        rows.append({"case_id": result["case_id"], "split": path.parent.parent.name,
                     "source": result["source"], "source_hash": source_hash,
                     "kos_role": role_match.group(1).strip() if role_match else "unknown",
                     "kos_has_authority_units": bool(legacy),
                     "kos_nn_only_or_query_case": not legacy and "notice_need_ids:" in case_markdown,
                     "extractive_result": result, "legacy_aus": legacy,
                     "final_source_locations": [{"item_id": item["id"],
                         "collection": item["collection"],
                         "sources": [{"source_id": excerpt["source_id"],
                                      "start": excerpt["start"], "end": excerpt["end"]}
                                     for excerpt in item.get("excerpts", [])]}
                         for item in [*result.get("brief", []), *result.get("aus", [])]]
                         if result.get("schema_version") in {6, 7, 8, 9, 10, 11, 12, 13, 14, 15} else [],
                     "human_review": {"reviewer_1": None, "reviewer_2": None,
                                      "adjudication": None,
                                      "criteria": ["selection", "attribution", "treatment",
                                                   "conditions", "omissions", "reading_actions"]}})
    destination = experiment / "comparison/review_bundle.json"
    save(destination, {"schema_version": max((
        row["extractive_result"].get("schema_version", 10) for row in rows), default=10),
                       "warning": "Historical KOS is a comparison, not gold; query/NN-only cases are explicit.",
                       "cases": rows})
    return destination
