"""Create an evidence-linked, deliberately unlabelled calibration worksheet."""

from __future__ import annotations

import json
from pathlib import Path

from .source import save


def _component(item: dict, name: str, proposed: object) -> dict:
    return {"component": name, "proposed": proposed,
            "evidence_source_ids": [], "reviewer_1": None, "reviewer_2": None,
            "adjudication": "pending", "reason": None}


def create_adjudication(source_experiment: str | Path,
                        destination: str | Path) -> Path:
    source_experiment, destination = Path(source_experiment), Path(destination)
    cases = []
    for path in sorted(source_experiment.glob("*/*/case.json")):
        result = json.loads(path.read_text(encoding="utf-8"))
        items = []
        final_items = [*result.get("brief", []), *result.get("aus", [])]
        for item in final_items:
            components = [_component(item, "selection",
                                     [ref["source_id"] for ref in item["source_refs"]])]
            if item.get("collection") == "brief" or "kind" in item:
                components.append(_component(item, "kind", item["kind"]))
            else:
                components.extend([_component(item, "relation", "selected_refs_cohere"),
                                   _component(item, "treatment", item["treatment"])])
            components.extend(_component(item, f"attribution:{ref['source_id']}",
                                         ref["attribution"])
                              for ref in item["source_refs"])
            items.append({"item_id": item["id"], "revision": item["revision"],
                          "collection": item.get("collection",
                              "brief" if "kind" in item else "aus"),
                          "source_refs": item["source_refs"], "components": components,
                          "omission_review": {"status": "pending", "reason": None,
                                              "evidence_source_ids": []}})
        unresolved = [{"item_id": item["id"], "revision": item["revision"],
                       "collection": item["collection"], "status": "pending",
                       "reason": None, "source_refs": item["source_refs"]}
                      for item in result.get("unresolved_items", [])]
        deleted = [{"item_id": item["id"], "revision": item["revision"],
                    "collection": item["collection"], "status": "pending",
                    "reason": None, "source_refs": item["source_refs"]}
                   for item in result.get("deleted_items", [])]
        cases.append({"case_id": result["case_id"], "source": result["source"],
                      "source_hash": result["source_hash"], "items": items,
                      "unresolved_item_review": unresolved,
                      "deleted_item_review": deleted,
                      "draft_to_final_review": {"fixed": [], "persisted_errors": [],
                          "new_errors": [], "correct_content_lost": []},
                      "au_opportunities": [],
                      "au_opportunity_review_status": "pending",
                      "unread_source_review": {"status": "pending", "notes": None}})
    worksheet = {"schema_version": 1, "source_experiment": str(source_experiment.resolve()),
        "status": "pending_adjudication",
        "allowed_decisions": ["definite_error", "defensible_alternative",
                              "insufficient_context"],
        "warning": "This blank worksheet is external evaluation, not gold. Review final source and KB before logs; never provide it to reader or repair prompts.",
        "cases": cases}
    save(destination, worksheet)
    return destination
