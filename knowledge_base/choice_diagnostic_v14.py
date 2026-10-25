"""Two-request controlled probe of whole-paragraph versus direct sentence keys.

This diagnostic is deliberately separate from the KB builder and capability gate.
It never changes an item, source manifest, or an existing V14 experiment.
"""

from __future__ import annotations

import json
from pathlib import Path

from .endpoint import ModelProtocolError
from .schema_v10 import obj, string_enum, validate
from .schema_v14 import response_format, schema_hash
from .source import digest, save

VERSION = "v14-minimal-whole-vs-sentences-1"
SYSTEM = ("Read the supplied paragraph. Assign only the legal functions requested "
          "by the response schema. A legal rule is AU; a case fact is brief. "
          "Return only the JSON object required by response_format.")
RULE = "The Court holds that a party must receive notice before removal."
FACT = "The applicant received no notice."
SOURCE = {
    "source_id": "P0001",
    "text": RULE + " " + FACT,
    "sentences": [
        {"source_id": "S0001", "start_offset": 0, "end_offset": len(RULE)},
        {"source_id": "S0002", "start_offset": len(RULE) + 1,
         "end_offset": len(RULE) + 1 + len(FACT)},
    ],
}
LABELS = ("skip", "brief", "aus", "both")


def cases() -> list[dict]:
    payload = {"opened_source": SOURCE}
    return [
        {"name": "whole", "schema": obj({"choices": obj({
            "P0001": string_enum(LABELS)})}), "payload": payload},
        {"name": "sentences", "schema": obj({"choices": obj({
            "S0001": string_enum(LABELS), "S0002": string_enum(LABELS)})}),
         "payload": payload},
    ]


def _expected(name: str, answer: dict) -> bool:
    choices = answer["choices"]
    if name == "whole":
        return choices["P0001"] in {"aus", "both"}
    return choices == {"S0001": "aus", "S0002": "brief"}


def probe(endpoint, config: dict, experiment: Path, fingerprint: dict) -> dict:
    path = experiment / "choice_diagnostic.json"
    results = []
    if path.exists():
        previous = json.loads(path.read_text(encoding="utf-8"))
        if previous.get("fingerprint") != fingerprint:
            raise ValueError("choice_diagnostic_fingerprint_mismatch")
        if previous["status"] in {"passed", "failed"}:
            return previous
        results = previous["results"]
    for index, case in enumerate(cases()):
        name, schema, payload = case["name"], case["schema"], case["payload"]
        signature = schema_hash(schema)
        if index < len(results):
            if results[index]["name"] != name or results[index][
                    "schema_hash"] != signature or results[index]["errors"]:
                raise ValueError("choice_diagnostic_identity_mismatch")
            continue
        identity = {"experiment": str(experiment.resolve()),
                    "fingerprint": fingerprint, "index": index,
                    "schema_hash": signature, "diagnostic": VERSION}
        request_id = "v14:choice-diagnostic:" + str(index) + ":" + digest(
            json.dumps(identity, sort_keys=True).encode("utf-8"))[:20]
        cache_path = experiment / "choice_diagnostic" / f"probe_{index}.json"
        try:
            answer = endpoint.complete(config["reader"], SYSTEM, payload,
                request_id=request_id,
                metadata={"experiment": experiment.name,
                    "stage": "choice_diagnostic", "turn": index,
                    "schema_version": 14, "diagnostic_version": VERSION,
                    "schema_hash": signature},
                cache_path=cache_path, response_format=response_format(schema))
        except ModelProtocolError:
            result = {"status": "failed", "fingerprint": fingerprint,
                "results": results, "failure": {"probe": name,
                    "code": "invalid_or_truncated_response",
                    "raw_response": str(cache_path.with_suffix(".raw.json"))}}
            save(path, result)
            return result
        errors = validate(answer, schema)
        if not errors and not _expected(name, answer):
            errors.append({"path": "$.choices", "error_code":
                           "expected_legal_function_not_selected"})
        results.append({"name": name, "schema_hash": signature,
                        "response": answer, "errors": errors})
        result = {"status": "failed" if errors else "in_progress",
                  "fingerprint": fingerprint, "results": results}
        save(path, result)
        if errors:
            return result
    result = {"status": "passed", "fingerprint": fingerprint,
              "results": results}
    save(path, result)
    return result
