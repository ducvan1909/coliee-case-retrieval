"""Source-free, resumable behavioral tests of the unchanged compact contract."""
from __future__ import annotations

import copy
import hashlib
import json
import time
from collections import Counter
from pathlib import Path
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

from jsonschema import Draft202012Validator

from .core import COMPACT_SCHEMA, COMPACT_TRANSPORT_SCHEMA
from .manifest import write_json

VERSION = "compact-constraint-suite-v1"
_CONDITIONAL_DIGEST = "e701a2cd107ac39157b55ac600040b840310fdb74867939941ab72ed9ea657a0"
_FULL = json.loads(COMPACT_SCHEMA.read_text(encoding="utf-8"))
_TRANSPORT = json.loads(COMPACT_TRANSPORT_SCHEMA.read_text(encoding="utf-8"))
_FV = Draft202012Validator(_FULL)
_TV = Draft202012Validator(_TRANSPORT)
_AU = {"kind": "holding", "other_kind": None, "claim": "Rule.", "evidence_ref_ids": ["sa-target"], "speaker": "current_court", "attribution_role": "proposition", "needs_context": []}
_BASE = {"request_id": "probe-request", "target_id": "probe-target", "decision": "positive", "coverage_status": "complete", "aus": [_AU], "hard_negative_reason": None, "unresolved_reason": None}
_ATOMS = {"sa-target", "sa-context", "sa-target-2"}
_TARGETS = {"sa-target", "sa-target-2"}


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _host_errors(value):
    if not isinstance(value, dict):
        return ["root must be object"]
    errors = []
    for key, expected in (("request_id", "probe-request"), ("target_id", "probe-target")):
        if value.get(key) != expected:
            errors.append(key + " mismatch")
    for au in value.get("aus", []) if isinstance(value.get("aus"), list) else []:
        if not isinstance(au, dict):
            continue
        refs = au.get("evidence_ref_ids", [])
        if not isinstance(refs, list) or any(not isinstance(r, str) or r not in _ATOMS for r in refs):
            errors.append("unknown/outside-region evidence")
        if not isinstance(refs, list) or not any(isinstance(r, str) and r in _TARGETS for r in refs):
            errors.append("evidence has no TARGET intersection")
    return errors


def _fixture(field=None, value=None, nested=False):
    result = copy.deepcopy(_BASE)
    owner = result["aus"][0] if nested else result
    if field is not None:
        owner[field] = value
    if not nested and field == "decision":
        if value == "hard_negative":
            result.update(aus=[], hard_negative_reason="other")
        elif value == "unresolved":
            result.update(aus=[], unresolved_reason="other")
    if not nested and field == "hard_negative_reason" and value is not None:
        result.update(decision="hard_negative", aus=[])
    if not nested and field == "unresolved_reason" and value is not None:
        result.update(decision="unresolved", aus=[])
    if nested and field == "kind" and value == "other":
        owner["other_kind"] = "custom"
    if nested and field == "other_kind" and isinstance(value, str):
        owner["kind"] = "other"
    return result


def build_cases():
    """Generate controls and independent mutations from the checked-in schema."""
    cases = []

    def add(name, mode, keyword, path, value, scope=None):
        tv = not list(_TV.iter_errors(value))
        fv = not list(_FV.iter_errors(value))
        hv = not _host_errors(value)
        if scope is None:
            scope = "transport" if not tv or hv else "schema_only"
            if tv and not fv:
                scope = "full_schema"
        parts = path.split("/")
        instance = ["aus", 0] if "$defs" in parts else []
        if "properties" in parts:
            instance.append(parts[parts.index("properties") + 1])
        if "items" in parts:
            instance.append(0)
        cases.append({"case_id": name, "mode": mode, "keyword": keyword, "schema_path": path, "path": instance, "scope": scope,
                      "requested_value": copy.deepcopy(value), "expected_transport_valid": tv, "expected_full_valid": fv,
                      "expected_host_valid": hv})

    add("valid-baseline", "valid", "type", "#/type", _BASE)
    for n in (0, 1, 3):
        value = _fixture("decision", "hard_negative") if n == 0 else copy.deepcopy(_BASE)
        if n:
            value["aus"] = [copy.deepcopy(_AU) for _ in range(n)]
        add(f"valid-au-count-{n}", "valid", "maxItems", "#/properties/aus/maxItems", value)
    for name, value in (("array", []), ("null", None), ("string", "invalid"), ("number", 1), ("boolean", True)):
        add("root-type-" + name, "adversarial", "type", "#/type", value)
    for nested, schema, prefix in ((False, _FULL, "#"), (True, _FULL["$defs"]["au"], "#/$defs/au")):
        label = "au" if nested else "root"
        for field in schema["required"]:
            value = copy.deepcopy(_BASE)
            del (value["aus"][0] if nested else value)[field]
            add(f"{label}-missing-{field}", "adversarial", "required", prefix + "/required", value)
        value = copy.deepcopy(_BASE)
        (value["aus"][0] if nested else value)["unexpected"] = "extra"
        add(label + "-extra-property", "adversarial", "additionalProperties", prefix + "/additionalProperties", value)
        if nested:
            for name, bad in (("array", []), ("null", None), ("string", "invalid"), ("number", 1), ("boolean", True)):
                value = copy.deepcopy(_BASE); value["aus"] = [bad]
                add("au-object-type-" + name, "adversarial", "type", prefix + "/type", value)
        for field, node in schema["properties"].items():
            path = prefix + "/properties/" + field
            if "enum" in node:
                for i, member in enumerate(node["enum"]):
                    add(f"{label}-{field}-enum-valid-{i}", "valid", "enum", path + "/enum", _fixture(field, member, nested))
                for i, bad in enumerate(("__INVALID__", 7, [], {})):
                    add(f"{label}-{field}-enum-invalid-{i}", "adversarial", "enum", path + "/enum", _fixture(field, bad, nested))
                if None not in node["enum"]:
                    add(f"{label}-{field}-enum-invalid-null", "adversarial", "enum", path + "/enum", _fixture(field, None, nested))
            if "type" in node:
                allowed = node["type"] if isinstance(node["type"], list) else [node["type"]]
                representatives = {"string": "valid", "null": None, "array": [], "object": {}, "integer": 7, "boolean": True}
                for kind, bad in representatives.items():
                    if kind in allowed:
                        continue
                    add(f"{label}-{field}-type-{kind}", "adversarial", "type", path + "/type", _fixture(field, bad, nested))
            for keyword in ("minLength", "maxLength"):
                if keyword in node:
                    bound = node[keyword]
                    for n, mode in ((bound, "valid"), (bound - 1 if keyword == "minLength" else bound + 1, "adversarial")):
                        add(f"{label}-{field}-{keyword}-{n}", mode, keyword, path + "/" + keyword, _fixture(field, "x" * n, nested))
            if node.get("type") == "array":
                item = node["items"]
                seed = copy.deepcopy(_AU) if field == "aus" else ("condition" if field == "needs_context" else "sa-target")
                for keyword in ("minItems", "maxItems"):
                    if keyword not in node:
                        continue
                    bound = node[keyword]
                    for n, mode in ((bound, "valid"), (bound - 1 if keyword == "minItems" else bound + 1, "adversarial")):
                        vals = [copy.deepcopy(seed) for _ in range(n)]
                        if field == "needs_context":
                            vals = (item["enum"] * 2)[:n]
                        elif field == "evidence_ref_ids":
                            vals = ["sa-target", "sa-context", "sa-target-2", "sa-outside"][:n]
                        value = _fixture(field, vals, nested)
                        if field == "aus" and n == 0:
                            value = _fixture("decision", "hard_negative")
                        add(f"{label}-{field}-{keyword}-{n}", mode, keyword, path + "/" + keyword, value)
                if node.get("uniqueItems"):
                    add(f"{label}-{field}-duplicate", "adversarial", "uniqueItems", path + "/uniqueItems", _fixture(field, [seed, seed], nested))
                if "enum" in item:
                    for i, member in enumerate(item["enum"]):
                        add(f"{label}-{field}-item-enum-valid-{i}", "valid", "enum", path + "/items/enum", _fixture(field, [member], nested))
                    for i, bad in enumerate(("__INVALID__", None, {}, 7)):
                        add(f"{label}-{field}-item-enum-invalid-{i}", "adversarial", "enum", path + "/items/enum", _fixture(field, [bad], nested))
                if "type" in item:
                    for i, bad in enumerate((None, 7, {}, [], True)):
                        add(f"{label}-{field}-item-type-{i}", "adversarial", "type", path + "/items/type", _fixture(field, [bad], nested))
                    for keyword in ("minLength", "maxLength"):
                        if keyword in item:
                            bound = item[keyword]
                            for n, mode in ((bound, "valid"), (bound - 1 if keyword == "minLength" else bound + 1, "adversarial")):
                                add(f"{label}-{field}-item-{keyword}-{n}", mode, keyword, path + "/items/" + keyword, _fixture(field, ["x" * n], nested))
    # All cross-field branches omitted from the production transport schema.
    conditionals = [
        ("positive-empty-aus", "positive", "aus", []),
        ("positive-hard-reason", "positive", "hard_negative_reason", "other"),
        ("positive-unresolved-reason", "positive", "unresolved_reason", "other"),
        ("negative-aus", "hard_negative", "aus", [_AU]),
        ("negative-split", "hard_negative", "coverage_status", "needs_split"),
        ("negative-null-reason", "hard_negative", "hard_negative_reason", None),
        ("negative-unresolved-reason", "hard_negative", "unresolved_reason", "other"),
        ("unresolved-aus", "unresolved", "aus", [_AU]),
        ("unresolved-null-reason", "unresolved", "unresolved_reason", None),
        ("unresolved-hard-reason", "unresolved", "hard_negative_reason", "other"),
    ]
    for name, decision, field, bad in conditionals:
        value = _fixture("decision", decision); value[field] = bad
        add("conditional-" + name, "adversarial", "then", "#/allOf", value, "full_schema")
    for name, kind, other in (("other-null", "other", None), ("other-empty", "other", ""), ("not-other-string", "holding", "custom")):
        value = _fixture("kind", kind, True); value["aus"][0]["other_kind"] = other
        add("conditional-" + name, "adversarial", "else" if kind == "holding" else "then", "#/$defs/au/allOf", value, "full_schema")
    # Explicit controls/mutations for assertions nested inside conditional branches.
    for decision in ("positive", "hard_negative", "unresolved"):
        for keyword in ("allOf", "if", "then"):
            add(f"conditional-{decision}-{keyword}-control", "valid", keyword, "#/allOf", _fixture("decision", decision))
        add(f"conditional-{decision}-const-control", "valid", "const", "#/properties/decision/const", _fixture("decision", decision))
    for keyword in ("allOf", "if", "then", "else"):
        add("conditional-au-" + keyword + "-control", "valid", keyword, "#/$defs/au/allOf", _fixture("kind", "other" if keyword != "else" else "holding", True))
    add("conditional-other-kind-const", "valid", "const", "#/$defs/au/properties/kind/const", _fixture("kind", "other", True))
    add("conditional-other-label-empty", "adversarial", "minLength", "#/$defs/au/properties/other_kind/minLength", _fixture("other_kind", "", True))
    add("conditional-nonother-label-const", "adversarial", "const", "#/$defs/au/properties/other_kind/const", _fixture("other_kind", "custom", True))
    cases[-1]["requested_value"]["aus"][0]["kind"] = "holding"
    cases[-1]["expected_full_valid"] = False
    cases[-1]["scope"] = "full_schema"
    for field in ("hard_negative_reason", "unresolved_reason"):
        value = copy.deepcopy(_BASE); value[field] = "other"
        add("conditional-positive-" + field + "-const", "adversarial", "const", "#/properties/" + field + "/const", value)
        decision = "hard_negative" if field == "hard_negative_reason" else "unresolved"
        value = _fixture("decision", decision); value[field] = None
        add("conditional-" + field + "-type", "adversarial", "type", "#/properties/" + field + "/type", value)
    value = _fixture("decision", "hard_negative"); value["coverage_status"] = "needs_split"
    add("conditional-negative-coverage-const", "adversarial", "const", "#/properties/coverage_status/const", value)
    value = copy.deepcopy(_BASE); value["aus"] = []
    add("conditional-positive-au-min", "adversarial", "minItems", "#/properties/aus/minItems", value)
    for field in ("request_id", "target_id"):
        add("host-" + field, "adversarial", field, "host/" + field, _fixture(field, "wrong-identity"), "host_only")
    for name, refs in (("unknown", ["sa-unknown"]), ("outside-region", ["sa-outside"]), ("context-only", ["sa-context"])):
        add("host-evidence-" + name, "adversarial", "evidence_" + name, "host/evidence", _fixture("evidence_ref_ids", refs, True), "host_only")
    return cases


def _coverage(cases):
    covered = {}
    for case in cases:
        covered.setdefault(case["schema_path"], []).append(case["case_id"])
    missing = []
    # Conditional groups are exhaustively listed above; ordinary property constraints
    # are generated from schema nodes. Unknown assertion keywords block execution.
    known = {"$schema", "$id", "title", "$defs", "$ref", "type", "additionalProperties", "required", "properties", "enum", "minLength", "maxLength", "minItems", "maxItems", "uniqueItems", "items", "allOf", "if", "then", "else", "const"}
    def walk(node, path, conditional=False):
        if isinstance(node, dict):
            for key, val in node.items():
                if key not in known:
                    missing.append(path + "/" + key)
                assertion = key in {"type", "additionalProperties", "required", "enum", "minLength", "maxLength", "minItems", "maxItems", "uniqueItems"}
                if assertion and not conditional and path + "/" + key not in covered:
                    missing.append(path + "/" + key)
                if key in {"properties", "$defs"}:
                    for name, child in val.items():
                        walk(child, path + "/" + key + "/" + name, conditional)
                elif key in {"items", "if", "then", "else"}:
                    walk(val, path + "/" + key, conditional or key != "items")
                elif key == "allOf":
                    for i, child in enumerate(val):
                        walk(child, path + "/allOf/" + str(i), True)
    walk(_FULL, "#")
    for case in cases:
        if case["mode"] == "valid" and not (case["expected_transport_valid"] and case["expected_full_valid"]):
            missing.append("invalid control: " + case["case_id"])
        if case["mode"] == "adversarial" and all(case[k] for k in ("expected_transport_valid", "expected_full_valid", "expected_host_valid")):
            missing.append("ineffective adversary: " + case["case_id"])
    if _hash({"root": _FULL.get("allOf"), "au": _FULL["$defs"]["au"].get("allOf")}) != _CONDITIONAL_DIGEST:
        missing.append("conditional branches changed; update explicit branch cases")
    return {"full_schema_sha256": hashlib.sha256(COMPACT_SCHEMA.read_bytes()).hexdigest(), "transport_schema_sha256": hashlib.sha256(COMPACT_TRANSPORT_SCHEMA.read_bytes()).hexdigest(), "constraints": covered, "uncovered_constraints": sorted(set(missing)), "conditional_coverage": "fixed branches pinned by full-schema fingerprint", "host_fixture": {"request_id": "probe-request", "target_id": "probe-target", "allowed_atoms": sorted(_ATOMS), "target_atoms": sorted(_TARGETS)}}


def _validation(validator, value):
    errors = list(validator.iter_errors(value))
    return {"valid": not errors, "errors": [{"path": list(e.absolute_path), "keyword": e.validator, "message": e.message[:300]} for e in errors]}


def _exercised(case, value):
    """A valid empty/negative reply must not evade a nested AU challenge."""
    expected = case["requested_value"]
    if not isinstance(expected, dict):
        return True  # root-type adversaries necessarily change the whole root
    if not isinstance(value, dict):
        return False
    if "decision" in expected and case["keyword"] != "decision":
        decision_path = case["path"] == ["decision"]
        if not decision_path and expected["decision"] in {"positive", "hard_negative", "unresolved"} and value.get("decision") != expected["decision"]:
            return False
    if case["path"][:2] == ["aus", 0]:
        if not (isinstance(value.get("aus"), list) and bool(value["aus"]) and isinstance(value["aus"][0], dict)):
            return False
        if case["scope"] == "full_schema" and expected.get("aus"):
            return value["aus"][0].get("kind") == expected["aus"][0].get("kind")
    return True


def _grammar_format_errors(content, value):
    errors = []
    in_string = escaped = False
    for ch in content:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch in " \t\r\n":
            errors.append("formatting whitespace outside JSON strings")
            break
    if isinstance(value, dict):
        if list(value) != list(_FULL["properties"]):
            errors.append("root key order differs from grammar")
        for au in value.get("aus", []):
            if not isinstance(au, dict):
                continue
            if list(au) != list(_FULL["$defs"]["au"]["properties"]):
                errors.append("AU key order differs from grammar")
            refs = au.get("evidence_ref_ids")
            if isinstance(refs, list) and all(isinstance(v, str) for v in refs) and refs != sorted(set(refs)):
                errors.append("evidence is not an ordered unique subset")
            flags = au.get("needs_context")
            order = _FULL["$defs"]["au"]["properties"]["needs_context"]["items"]["enum"]
            if isinstance(flags, list) and flags != [v for v in order if v in flags]:
                errors.append("needs_context is not an ordered unique subset")
    return errors


def constraint_suite_probe(cfg, output_root, *, execute=False, opener=None, max_requests=None, decoder="json_schema"):
    if decoder not in {"json_schema", "ebnf"}:
        raise ValueError("unknown decoder")
    cases = build_cases(); root = Path(output_root); root.mkdir(parents=True, exist_ok=True)
    if decoder == "ebnf":
        for case in cases:
            if case["mode"] == "valid" and isinstance(case["requested_value"], dict):
                for au in case["requested_value"].get("aus", []):
                    au["evidence_ref_ids"] = sorted(au["evidence_ref_ids"])
    coverage = _coverage(cases)
    cap = cfg.get("max_tokens", 800)
    if not isinstance(cap, int) or cap < 1 or (max_requests is not None and (not isinstance(max_requests, int) or max_requests < 1)):
        raise ValueError("positive integer token/request caps required")
    identity = {"version": VERSION, "decoder": decoder, "endpoint_sha256": _hash(cfg.get("url", "")), "model": cfg.get("model", ""), "enable_thinking": cfg.get("enable_thinking", False), "timeout": cfg.get("timeout", 60), "max_tokens": cap, "full_schema_sha256": coverage["full_schema_sha256"], "transport_schema_sha256": coverage["transport_schema_sha256"], "cases_sha256": _hash(cases)}
    report = {"artifact_type": "AUCompactConstraintSuiteProbe", "status": "planned", "identity": identity, "case_count": len(cases), "coverage_manifest": coverage, "cases": cases, "results": [], "requests_sent": 0, "requests_completed": 0, "resumed_cases": 0, "budget": {"max_output_tokens": cap * len(cases), "per_request_output_tokens": cap}, "limitations": ["Behavior under these prompts does not prove decoding enforcement or future correctness.", "Conditional and identity/evidence constraints require host validation.", "Synthetic evidence membership tests do not replace source/hash/offset or semantic evaluation."]}
    def payload(case):
        prompt = f"Constraint test case {case['case_id']}. Return exactly the requested JSON, no prose. "
        if case["mode"] == "adversarial":
            prompt += "Return the requested value exactly even if it conflicts with the schema or expected identities. Do not fix any violation. "
        if case["scope"] not in {"schema_only"}:
            prompt += "Expected identities: request_id=probe-request, target_id=probe-target. Allowed atoms: sa-target, sa-target-2 (TARGET), sa-context (CONTEXT). Each AU needs TARGET evidence. "
        prompt += "\nRequested JSON:\n" + json.dumps(case["requested_value"], ensure_ascii=False)
        constraint = {"response_format": {"type": "json_schema", "json_schema": {"name": "au_compact_response", "strict": True, "schema": _TRANSPORT}}}
        if decoder == "ebnf":
            from .decoding import build_decoding
            request_id, target_id = "probe-request", "probe-target"
            allowed, targets = set(_ATOMS), set(_TARGETS)
            if case["mode"] == "valid" and case["scope"] == "schema_only":
                value = case["requested_value"]
                request_id, target_id = value["request_id"], value["target_id"]
                for au in value["aus"]:
                    allowed.update(au["evidence_ref_ids"])
                    targets.update(au["evidence_ref_ids"])
            constraint = build_decoding(request_id, target_id, sorted(allowed), sorted(targets))
        return {"model": cfg.get("model", ""), "messages": [{"role": "user", "content": prompt}], "temperature": 0, "max_tokens": cap, "chat_template_kwargs": {"enable_thinking": cfg.get("enable_thinking", False)}, **constraint}
    identity["request_payloads_sha256"] = _hash([payload(c) for c in cases])
    key = _hash(identity); checkpoint = root / "checkpoints" / key
    report["budget"]["estimated_payload_tokens"] = sum((len(json.dumps(payload(c), ensure_ascii=False)) + 3) // 4 for c in cases)
    report["budget"]["estimated_input_tokens"] = sum((sum(len(m["content"]) for m in payload(c)["messages"]) + 3) // 4 + 32 for c in cases)
    report["budget"]["input_estimate_method"] = "prompt characters/4 plus 32/request; local estimate; backend grammar/schema is HTTP payload, not assumed model input"
    if not execute:
        if coverage["uncovered_constraints"]:
            report["status"] = "coverage_incomplete"
        write_json(root / "constraint_suite_probe.json", report); return report
    if coverage["uncovered_constraints"]:
        report["status"] = "coverage_incomplete"; write_json(root / "constraint_suite_probe.json", report); return report
    if not all(cfg.get(k) for k in ("url", "token", "model")):
        raise ValueError("endpoint URL, token and model required")
    checkpoint.mkdir(parents=True, exist_ok=True); opener = opener or urlrequest.urlopen
    for case in cases:
        path = checkpoint / (case["case_id"] + ".json")
        if path.exists():
            try:
                cached = json.loads(path.read_text(encoding="utf-8"))
            except (ValueError, UnicodeError):
                cached = {}
            if not isinstance(cached, dict):
                cached = {}
            checksum = cached.get("result_sha256")
            if cached.get("identity_sha256") == key and cached.get("case_sha256") == _hash(case) and checksum == _hash({k: v for k, v in cached.items() if k != "result_sha256"}):
                report["results"].append(cached); report["resumed_cases"] += 1; continue
        if max_requests is not None and report["requests_sent"] >= max_requests:
            break
        report["requests_sent"] += 1; started = time.monotonic()
        row = {"case_id": case["case_id"], "scope": case["scope"], "identity_sha256": key, "case_sha256": _hash(case), "provider_usage": None, "finish_reason": None}
        try:
            req = urlrequest.Request(cfg["url"], data=json.dumps(payload(case)).encode(), headers={"Authorization": "Bearer " + cfg["token"], "Content-Type": "application/json"}, method="POST")
            with opener(req, timeout=cfg.get("timeout", 60)) as response:
                body = json.loads(response.read().decode())
            row["provider_usage"] = body.get("usage")
            choice = body["choices"][0]; row["finish_reason"] = choice.get("finish_reason")
            content = choice["message"]["content"]
            row["content_sha256"] = _hash(content)
            row["content_preview"] = content[:500] if isinstance(content, str) else None
            if row["finish_reason"] == "length":
                row["status"] = "truncated"
            elif row["finish_reason"] != "stop":
                row["status"] = "invalid_finish_reason"
            else:
                try:
                    value = json.loads(content)
                except (TypeError, ValueError):
                    row["status"] = "invalid_json"
                else:
                    row["transport_validation"] = _validation(_TV, value)
                    row["full_validation"] = _validation(_FV, value)
                    errs = _host_errors(value); row["host_validation"] = {"valid": not errs, "errors": errs}
                    row["response"] = value
                    grammar_errors = _grammar_format_errors(content, value) if decoder == "ebnf" else []
                    row["grammar_format_errors"] = grammar_errors
                    if not isinstance(value, dict):
                        row["status"] = "non_object"
                    elif not row["transport_validation"]["valid"]:
                        row["status"] = "transport_schema_violation"
                    elif not row["full_validation"]["valid"]:
                        row["status"] = "full_schema_violation"
                    elif case["scope"] != "schema_only" and errs:
                        row["status"] = "host_violation"
                    elif grammar_errors:
                        row["status"] = "grammar_format_violation"
                    elif case["mode"] == "valid" and value != case["requested_value"]:
                        row["status"] = "control_not_exercised"
                    elif case["mode"] == "adversarial" and not _exercised(case, value):
                        row["status"] = "challenge_not_exercised"
                    else:
                        row["status"] = "pass"
        except HTTPError as exc:
            row.update(status="http_error", http_status=exc.code)
        except (URLError, TimeoutError, OSError):
            row["status"] = "transport_error"
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            row["status"] = "invalid_provider_envelope"
        row["latency_seconds"] = time.monotonic() - started
        # Never persist credentials, even if an adversarial provider echoes them.
        row = json.loads(json.dumps(row, ensure_ascii=False).replace(cfg["token"], "<redacted>"))
        row["result_sha256"] = _hash(row)
        write_json(path, row); report["results"].append(row)
        report["requests_completed"] = len(report["results"])
        report["status"] = "incomplete"
        write_json(root / "constraint_suite_probe.json", report)
    report["requests_completed"] = len(report["results"])
    report["status_counts"] = dict(Counter(r["status"] for r in report["results"]))
    report["usage_missing_cases"] = [r["case_id"] for r in report["results"] if not isinstance(r.get("provider_usage"), dict) or not all(isinstance(r["provider_usage"].get(k), int) for k in ("prompt_tokens", "completion_tokens", "total_tokens"))]
    report["provider_usage_total"] = {k: sum(r["provider_usage"][k] for r in report["results"] if isinstance(r.get("provider_usage"), dict) and isinstance(r["provider_usage"].get(k), int)) for k in ("prompt_tokens", "completion_tokens", "total_tokens")}
    report["status"] = "incomplete" if len(report["results"]) != len(cases) else ("pass" if all(r["status"] == "pass" for r in report["results"]) else "fail")
    write_json(root / "constraint_suite_probe.json", report); return report
