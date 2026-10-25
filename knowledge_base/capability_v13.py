"""Exercise every V13 structured-output phase before a real case run."""

from __future__ import annotations

import json
from pathlib import Path

from . import schema_v12, schema_v13
from .source import digest, save


def probe(endpoint, config: dict, experiment: Path, fingerprint: dict) -> dict:
    path = experiment / "capability_probe.json"
    results = []
    if path.exists():
        previous = json.loads(path.read_text(encoding="utf-8"))
        if (previous.get("fingerprint") != fingerprint or
                previous.get("status") not in {"passed", "in_progress"}):
            raise ValueError("capability_probe_not_reusable")
        if previous["status"] == "passed":
            return previous
        results = previous["results"]
    item = {"handle": "I0000", "status": "active", "collection": "aus",
            "source_ids": ["S0001", "S0002"]}
    cases = [
        ("reader_extract", [], ["S0001"], None, None,
         "Create one AU anchored at S0001; assess this source batch."),
        ("reader_extract", [], ["S0001"], None, None,
         "Create no item and explain in batch_assessment why this source does not support one."),
        ("selection_extract", [item], ["S0001", "S0002"], None, None,
         "Choose scan_sources for I0000; assess the source batch."),
        ("reader_navigate", [item], [], [2], [2],
         "Read window 2 to inspect the remaining legal rule."),
        ("reader_navigate", [item], [], [], [2],
         "Finish reader; assess unread window 2."),
        ("source_scan", [item], [f"S{n:04d}" for n in range(
            schema_v12.SOURCE_BATCH_SIZE)], None, None,
         "Include C0 and C11 and exclude every other candidate."),
        ("classification", [item], ["S0001", "S0002"], None, None,
         "Classify I0000: S0001 primary, S0002 context, both current_court."),
        ("treatment", [item], ["S0001", "S0002"], None, None,
         "Choose applies and label S0001 authority and S0002 response."),
        ("finalizer", [item], ["S0001", "S0002"], None, None,
         "Keep I0000 with a reason."),
    ]
    for index, (phase, items, handles, readable, unread, instruction) in enumerate(cases):
        if phase.endswith("_extract"):
            schema = schema_v13.extraction_schema(items, handles)
        elif phase.endswith("_navigate"):
            schema = schema_v13.navigation_schema(readable, unread)
        elif phase == "source_scan":
            schema = schema_v13.build_source_scan_schema(len(handles))
        elif phase == "classification":
            schema = schema_v13.classification_schema(items)
        else:
            schema = schema_v12.build_schema(phase, items, handles)
        if index < len(results):
            saved = results[index]
            if (saved["phase"] != phase or saved["schema_hash"] !=
                    schema_v13.schema_hash(schema) or saved["errors"]):
                raise ValueError("capability_probe_identity_mismatch")
            continue
        payload = {"phase": phase, "items": items, "schema": schema,
                   "instruction": instruction}
        if phase.endswith("_extract"):
            payload["opened_sources"] = [{"source_id": handle,
                "text": ("The court applies the notice rule to the facts."
                         if handle == "S0001" else
                         "Notice is required by the cited rule.")}
                for handle in handles]
        elif phase.endswith("_navigate"):
            payload.update(readable_window_ids=readable, unread_window_ids=unread,
                last_batch_assessment={"reason": "Need to check the remaining rule.",
                                       "unresolved_needs": ["Rule in window 2"]})
        elif phase == "source_scan":
            payload["candidate_sources"] = [{"key": f"C{number}",
                "source_id": handle, "text": f"Legal proposition {number}."}
                for number, handle in enumerate(handles)]
        elif phase == "treatment":
            payload["source_context"] = {
                "S0001": "The cited authority requires notice.",
                "S0002": "The court applies that notice rule to this case."}
        identity = {"experiment": str(experiment.resolve()),
                    "fingerprint": fingerprint, "index": index,
                    "schema_hash": schema_v13.schema_hash(schema)}
        request_id = ("v13:capability:" + str(index) + ":" + digest(json.dumps(
            identity, sort_keys=True).encode("utf-8"))[:20])
        answer = endpoint.complete(config["reader"],
            "Return one valid JSON object matching the supplied schema. " + instruction,
            payload, request_id=request_id,
            metadata={"experiment": experiment.name, "stage": "capability_probe",
                "schema_version": schema_v13.SCHEMA_VERSION,
                "prompt_version": schema_v13.PROMPT_VERSION,
                "schema_hash": schema_v13.schema_hash(schema), "turn": index},
            cache_path=experiment / "capability" / f"probe_{index}.json",
            response_format=schema_v13.response_format(schema))
        errors = schema_v13.validate(answer, schema)
        if not errors and phase.endswith("_navigate"):
            errors.extend(schema_v13.validate_reading_decision(answer, unread))
        if not errors and phase == "treatment":
            errors.extend(schema_v13.validate_treatment_evidence(answer, items))
        if not errors and phase == "classification":
            errors.extend(schema_v13.validate_classification(answer, items))
        if not errors:
            expected = ("read" if index == 3 else "finish_phase" if index == 4
                        else None)
            if phase.endswith("_navigate") and answer[
                    "reading_decision"]["action"] != expected:
                errors.append({"path": "$.reading_decision.action",
                               "error_code": "probe_branch_not_exercised"})
            if index == 0 and (len(answer["new_items"]) != 1 or
                    answer["new_items"][0]["anchor_source_id"] != "S0001"):
                errors.append({"path": "$.new_items", "error_code": "probe_anchor_not_exercised"})
            if index == 1 and answer["new_items"]:
                errors.append({"path": "$.new_items", "error_code": "probe_empty_not_exercised"})
            if index == 2 and answer["decisions"]["I0000"]["choice"] != "scan_sources":
                errors.append({"path": "$.decisions.I0000.choice",
                               "error_code": "probe_revision_not_exercised"})
            if index == 5 and (answer["choices"]["C0"] != "include" or
                    answer["choices"]["C11"] != "include"):
                errors.append({"path": "$.choices", "error_code": "probe_scan_not_exercised"})
            if index == 6 and answer["decisions"]["I0000"]["choice"] != "classify":
                errors.append({"path": "$.decisions.I0000.choice",
                               "error_code": "probe_classification_not_exercised"})
            if index == 7 and answer["decisions"]["I0000"]["choice"] != "applies":
                errors.append({"path": "$.decisions.I0000.choice",
                               "error_code": "probe_treatment_not_exercised"})
        results.append({"phase": phase, "schema_hash": schema_v13.schema_hash(schema),
                        "response": answer, "errors": errors})
        save(path, {"status": "failed" if errors else "in_progress",
                    "fingerprint": fingerprint, "results": results})
        if errors:
            raise ValueError(f"endpoint_did_not_enforce_v13_schema:{phase}:{index}")
    result = {"status": "passed", "fingerprint": fingerprint, "results": results}
    save(path, result)
    return result
