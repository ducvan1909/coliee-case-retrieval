"""Source-linked paired comparison; overlap is a review cue, not a quality score."""

from __future__ import annotations

import json
from pathlib import Path

from .source import load_source, save


def _inventory(path: Path) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        columns = [part.strip().strip("`") for part in line.strip().strip("|").split("|")]
        if len(columns) == 4 and columns[0].isdigit() and columns[1].isdigit():
            result.setdefault(columns[0], []).append({
                "start": int(columns[1]), "anchor": columns[2].strip("“”"),
                "opportunity": columns[3]})
    return result


def _arm(experiment: Path, case_id: str, ledger: dict) -> tuple[dict, dict]:
    path = experiment / "calibration" / case_id / "case.json"
    case = json.loads(path.read_text(encoding="utf-8"))
    text, source_hash = load_source(case["source"])
    if source_hash != case["source_hash"]:
        raise ValueError(f"source_changed:{case_id}")
    for item in [*case.get("brief", []), *case.get("aus", []),
                 *case.get("unresolved_items", []), *case.get("deleted_items", [])]:
        for excerpt in item.get("excerpts", []):
            if text[excerpt["start"]:excerpt["end"]] != excerpt["text"]:
                raise ValueError(f"excerpt_mismatch:{case_id}:{item['id']}")
    calls = [call for call in ledger.get("calls", [])
             if call.get("case_id") == case_id and
             call.get("experiment", "").split(":", 1)[0] == experiment.name]
    usage = {"requests": len(calls),
             "prompt_tokens": sum(call.get("usage", {}).get("prompt_tokens", 0)
                                  for call in calls),
             "completion_tokens": sum(call.get("usage", {}).get("completion_tokens", 0)
                                      for call in calls),
             "elapsed_seconds": round(sum(call.get("elapsed_seconds", 0)
                                          for call in calls), 3),
             "internal_reserve_usd": round(sum(call.get("reserve_usd", 0) -
                 call.get("reserve_released_usd", 0) for call in calls), 3)}
    coverage = case["source_coverage"]
    return {"schema_version": case["schema_version"],
            "execution_status": case["execution_status"],
            "protocol_status": case["protocol_status"],
            "brief_count": len(case["brief"]), "au_count": len(case["aus"]),
            "covered_fraction": coverage["covered_fraction"],
            "unread_window_ids": case.get("unread_window_ids"),
            "read_actions": case.get("counts", {}).get("read_actions"),
            "reread_actions": case.get("counts", {}).get("reread_actions"),
            "usage": usage}, case


def export_pair(control: Path, guided: Path, inventory: Path,
                ledger_path: Path, output: Path) -> Path:
    references = _inventory(inventory)
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    cases = []
    for case_id in ("099980", "013948", "045155", "011904", "013009"):
        control_stats, old = _arm(control, case_id, ledger)
        guided_stats, new = _arm(guided, case_id, ledger)
        if old["source_hash"] != new["source_hash"]:
            raise ValueError(f"different_source:{case_id}")
        opportunities = []
        for reference in references[case_id]:
            matches = {}
            for label, case in (("control", old), ("guided", new)):
                matches[label] = [item["id"] for item in case["aus"]
                    if any(excerpt["start"] <= reference["start"] < excerpt["end"]
                           for excerpt in item.get("excerpts", []))]
            opportunities.append({**reference,
                "source_overlap_candidates": matches,
                "control_review": None, "guided_review": None,
                "review_note": None})
        cases.append({"case_id": case_id, "source_hash": old["source_hash"],
                      "control": control_stats, "guided": guided_stats,
                      "opportunities": opportunities,
                      "semantic_review_status": "pending_agent_review"})
    bundle = {"schema_version": 1, "comparison": "paired_v10_v11_reading",
              "source_inventory": str(inventory.resolve()),
              "warning": "Source overlap only nominates an AU for review. It does not prove the legal opportunity was captured. Inventory is agent review, not human gold.",
              "cases": cases}
    save(output, bundle)
    return output
