"""Compare source-grounded AU candidates with a hash-locked KOS reference."""
from __future__ import annotations

import ast
from collections import Counter
import hashlib
import html
import json
from pathlib import Path
import re

from jsonschema import Draft202012Validator

from ..au_compact.core import FULL_SCHEMA, build_evidence_catalog
from ..au_compact.manifest import _binding_path
from ..source_contract.store import open_source

DEFAULT_ATOM_ROOT = Path(__file__).resolve().parents[1] / "outputs/plan04_sentence_atoms_v1"


class ComparisonError(ValueError):
    """An input cannot be safely interpreted as the comparison contract."""


def _json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _inside(path, root):
    return path == root or root in path.parents


def _occurrences(text, source):
    spans, offset = [], 0
    while text:
        start = source.find(text, offset)
        if start < 0:
            break
        spans.append({"start_char": start, "end_char": start + len(text), "quote": text})
        offset = start + 1
    return spans


def _whitespace_map(text):
    chunks = list(re.finditer(r"\S+|\s+", text))
    normalized, starts, ends = [], [], []
    for chunk in chunks:
        value = chunk.group()
        if value.isspace():
            normalized.append(" "); starts.append(chunk.start()); ends.append(chunk.end())
        else:
            normalized.extend(value)
            starts.extend(range(chunk.start(), chunk.end()))
            ends.extend(range(chunk.start() + 1, chunk.end() + 1))
    return "".join(normalized), starts, ends


def align_evidence(text, source):
    """Return all exact or whitespace-only matches, never a guessed offset.

    ``status`` is exact, whitespace_normalized, ambiguous, no_match, or
    empty_evidence. Ambiguous matches retain every candidate source span.
    """
    if not isinstance(text, str) or not isinstance(source, str):
        raise ComparisonError("evidence and source must be strings")
    text = text.strip()
    if not text:
        return {"status": "empty_evidence", "method": None, "spans": []}
    exact = _occurrences(text, source)
    normalized, starts, ends = _whitespace_map(source)
    needle = re.sub(r"\s+", " ", text)
    spans = []
    for match in _occurrences(needle, normalized):
        start, end = starts[match["start_char"]], ends[match["end_char"] - 1]
        spans.append({"start_char": start, "end_char": end, "quote": source[start:end]})
    method = "exact" if len(exact) == len(spans) and exact else "whitespace_normalized"
    return {"status": "ambiguous" if len(spans) > 1 else method if spans else "no_match",
            "method": method if spans else None, "spans": spans}


def _scalar(value):
    value = value.strip()
    if value.startswith(("&", "*", "!", "|", ">", "{")):
        raise ComparisonError("unsupported YAML scalar syntax")
    if value.startswith("["):
        if not value.endswith("]"):
            raise ComparisonError("unclosed YAML list")
        return [_scalar(x) for x in value[1:-1].split(",")] if value[1:-1].strip() else []
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    if value.startswith('"'):
        try:
            return ast.literal_eval(value)
        except (ValueError, SyntaxError) as exc:
            raise ComparisonError("invalid quoted YAML scalar") from exc
    if value in ("null", "~"):
        return None
    if value in ("true", "false"):
        return value == "true"
    # Preserve leading zero case IDs and dates; no implicit YAML coercion.
    return value


def _frontmatter(text):
    match = re.match(r"\A---\s*\n(.*?)\n---\s*(?:\n|$)", text, re.S)
    if not match:
        raise ComparisonError("missing YAML front matter")
    values, list_key = {}, None
    for line in match[1].splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if re.match(r"^\s*-\s+", line):
            if list_key is None:
                raise ComparisonError("YAML list without field")
            values[list_key].append(_scalar(re.sub(r"^\s*-\s+", "", line)))
            continue
        field = re.fullmatch(r"([\w-]+):\s*(.*)", line)
        if not field:
            raise ComparisonError("unsupported nested YAML; requires explicit parser support")
        key, value = field.groups()
        if key in values:
            raise ComparisonError("duplicate YAML field: " + key)
        values[key] = _scalar(value) if value else []
        list_key = key if not value else None
    return values, text[match.end():]


def _sections(body):
    headers = list(re.finditer(r"^##\s+(.+?)\s*$", body, re.M))
    sections = {}
    for i, header in enumerate(headers):
        key = header[1].strip().lower()
        if key in sections:
            raise ComparisonError("duplicate Markdown section: " + key)
        sections[key] = body[header.end():headers[i + 1].start() if i + 1 < len(headers) else len(body)].strip()
    return sections


def _load_kos(root, manifest):
    root = Path(root).resolve()
    inventory, units, errors = [], [], []
    cases = manifest.get("cases", [])
    ids = [case.get("case_id") for case in cases]
    if not cases or len(ids) != len(set(ids)):
        raise ComparisonError("empty or duplicate KOS case selection")
    for case in cases:
        case_id = case["case_id"]
        if not isinstance(case_id, str) or not re.fullmatch(r"\d{6}", case_id):
            raise ComparisonError("invalid KOS case ID")
        directory = (root / case["case_path"]).resolve()
        if not _inside(directory, root) or directory == root or not directory.is_dir():
            raise ComparisonError("missing or unsafe KOS case directory")
        files, raws = [], {}
        for path in sorted(directory.rglob("*"), key=lambda p: p.relative_to(directory).as_posix()):
            if not _inside(path.resolve(), directory) or path.is_symlink():
                raise ComparisonError("KOS file escapes selected case")
            if not path.is_file():
                continue
            raw = path.read_bytes(); relative = path.relative_to(directory).as_posix()
            files.append({"path": relative, "sha256": _sha(raw), "byte_length": len(raw)})
            raws[relative] = raw
        digest = _sha(json.dumps(files, sort_keys=True, separators=(",", ":")).encode())
        actual = {"file_count": len(files), "total_bytes": sum(f["byte_length"] for f in files), "tree_sha256": digest}
        for key, value in actual.items():
            if case.get(key) != value:
                raise ComparisonError(f"KOS {case_id} {key} mismatch")
        inventory.append({**case, **actual, "status": "hash_verified", "files": files})
        for file in files:
            if Path(file["path"]).suffix.lower() != ".md":
                raise ComparisonError("selected KOS tree contains non-Markdown file")
            text = raws[file["path"]].decode("utf-8-sig")
            is_au = bool(re.search(r"^type:\s*['\"]?authority_unit['\"]?\s*$", text, re.M))
            if not is_au and "authority_units" not in Path(file["path"]).parts:
                continue
            try:
                metadata, body = _frontmatter(text)
                if metadata.get("type") != "authority_unit":
                    raise ComparisonError("AU file type mismatch")
                if str(metadata.get("case_id", "")).removesuffix(".txt") != case_id:
                    raise ComparisonError("AU case identity mismatch")
                if not isinstance(metadata.get("id"), str) or not metadata["id"]:
                    raise ComparisonError("missing AU ID")
                sections = _sections(body)
                evidence = sections.get("evidence span", "")
                evidence = "\n".join(re.sub(r"^\s*> ?", "", line) for line in evidence.splitlines()).strip()
                units.append({"kos_id": metadata["id"], "case_id": case_id,
                              "kos_role": case.get("kos_role"), "file": case["case_path"] + "/" + file["path"],
                              "file_sha256": file["sha256"], "metadata": metadata,
                              "claim_text": sections.get("claim", ""), "kind": metadata.get("kind"),
                              "attribution": metadata.get("attribution", sections.get("attribution")),
                              "speaker": metadata.get("speaker"), "evidence_text": evidence,
                              "limits_text": sections.get("limits", "")})
            except ComparisonError as exc:
                errors.append({"case_id": case_id, "file": file["path"], "file_sha256": file["sha256"], "error": str(exc)})
    keys = [(unit["case_id"], unit["kos_id"]) for unit in units]
    if len(keys) != len(set(keys)):
        raise ComparisonError("duplicate KOS AU identity")
    return inventory, units, errors


def _union(spans):
    result = []
    for span in sorted(spans, key=lambda x: (x["start_char"], x["end_char"])):
        start, end = span["start_char"], span["end_char"]
        if result and start <= result[-1][1]:
            result[-1][1] = max(end, result[-1][1])
        else:
            result.append([start, end])
    return result


def _overlap(a, b):
    return sum(max(0, min(x[1], y[1]) - max(x[0], y[0])) for x in _union(a) for y in _union(b))


def _length(spans):
    return sum(end - start for start, end in _union(spans))


def _valid_span(span, source, quote=False):
    start, end = span.get("start_char"), span.get("end_char")
    return (type(start) is int and type(end) is int and 0 <= start < end <= len(source)
            and (not quote or span.get("quote") == source[start:end]))


def _supplied_evidence(request, source, atom_root):
    if "atom_binding" not in request:
        return request["source_refs"], {"status": "legacy_raw_refs_fallback", "expansion_verified": False,
                                         "note": "No atom binding supplied; only raw refs are proven readable. No inferred expansion."}
    binding = request["atom_binding"]
    if not isinstance(binding, dict):
        raise ComparisonError("invalid request atom binding")
    for field in ("case_id", "source_hash"):
        if field in binding and binding[field] != request[field]:
            raise ComparisonError("atom binding case/hash identity mismatch")
    for field in ("atom_map_sha256", "policy_sha256", "source_hash"):
        if field in binding and (not isinstance(binding[field], str) or not re.fullmatch(r"[a-f0-9]{64}", binding[field])):
            raise ComparisonError("invalid atom binding hash format")
    catalog = build_evidence_catalog(request, _binding_path(binding, atom_root), source)
    if "atom_map_cache_key" in binding and catalog["atom_map"].get("cache_key") != binding["atom_map_cache_key"]:
        raise ComparisonError("atom map cache key mismatch")
    spans = list(catalog["atoms"].values())
    if not spans or any(not _valid_span(s, source, True) for s in spans):
        raise ComparisonError("invalid supplied atom catalog")
    return spans, {"status": "bound_atom_catalog_verified", "expansion_verified": True,
                   "atom_map_sha256": binding["atom_map_sha256"], "atom_spans": spans,
                   "metrics": catalog["metrics"]}


def _validate_response(row, source, validator, readable):
    request, response = row["request"], row.get("response")
    if row.get("status") != "protocol_verified":
        return ["row_not_protocol_verified"]
    errors = [error.message for error in validator.iter_errors(response)]
    if errors:
        return errors
    expected = request["expected_target_ids"]
    if (response["request_id"] != request["request_id"] or set(response["processed_target_ids"]) != set(expected)
            or sorted(t["target_id"] for t in response["target_results"]) != sorted(expected)):
        errors.append("response_request_target_ownership_mismatch")
    au_ids = []
    for target in response["target_results"]:
        for au in target["authority_units"]:
            au_ids.append(au["local_au_id"])
            spans = list(au["evidence_spans"])
            for key in ("condition_spans", "exception_spans", "limit_spans"):
                spans.extend(au[key])
            spans.extend(a["evidence_span"] for a in au["attributions"])
            if any(not _valid_span(span, source, True) for span in spans):
                errors.append("invalid_normalized_source_quote_or_offset")
            if any(_overlap([span], readable) != _length([span]) for span in spans if _valid_span(span, source, True)):
                errors.append("normalized_evidence_outside_supplied_catalog")
            primary = [s for s in request["source_refs"] if s.get("role") == "target" and target["target_id"] in s.get("target_ids", [])]
            if not _overlap(au["evidence_spans"], primary):
                errors.append("normalized_au_evidence_is_context_only_or_wrong_target")
    if len(au_ids) != len(set(au_ids)):
        errors.append("duplicate_normalized_au_id")
    for context in response["context_requests"]:
        if context["target_id"] not in expected or (context["anchor_span"] and not _valid_span(context["anchor_span"], source, True)):
            errors.append("invalid_context_request")
        elif context["anchor_span"] and _overlap([context["anchor_span"]], readable) != _length([context["anchor_span"]]):
            errors.append("context_anchor_outside_supplied_catalog")
    return errors


def _cost(run, run_path):
    """Ledger totals are authoritative; receipts/history remain separate to avoid double count."""
    receipts = []
    for row in run["request_ledger"]:
        receipts.append({"request_id": row["request"]["request_id"], "status": row.get("status"),
                         "receipt": row.get("receipt", {})})
    histories = []
    cache_root = Path(run_path).parent / "cache"
    for path in sorted(cache_root.glob("**/attempt_history/*.json")):
        if path.is_symlink() or not _inside(path.resolve(), cache_root.resolve()):
            raise ComparisonError("attempt history escapes run cache")
        data = _json(path)
        prior = data.get("prior", {})
        histories.append({"path": str(path), "sha256": _sha(path.read_bytes()),
                          "request_id": prior.get("request", {}).get("request_id"),
                          "status": prior.get("status"), "receipt": prior.get("receipt", {})})
    all_receipts = [r["receipt"] for r in receipts + histories]
    return {"runtime_ledger": run.get("runtime_ledger", {}), "current_receipts": receipts,
            "superseded_attempts": histories, "warmup": run.get("warmup"),
            "compact_schema_probe": run.get("compact_schema_probe"),
            "observed_receipt_latency_ms": sum(r.get("latency_ms", 0) or 0 for r in all_receipts),
            "latency_unavailable_count": sum(r.get("latency_ms") is None for r in all_receipts),
            "accounting_note": "Runtime ledger is preserved as reported, not certified exhaustive cost. Receipts/history may be missing; failures can have unknown usage. Do not add receipt tokens again to ledger totals. Archived attempts are separately observable, not guaranteed exhaustive.",
            "currency_cost": None, "currency_cost_status": "pricing_not_supplied"}


def compare(run_path, *, source_store, kos_root, kos_manifest, output_root=None, workload_manifest=None, atom_root=DEFAULT_ATOM_ROOT):
    """Read AUCompactRun and produce reference-only comparison JSON/escaped HTML.

    Full expected coverage is only assessed against supplied workload requests;
    no full-workload readiness or semantic quality is inferred from smoke runs.
    Output uses a NEW directory and refuses to overwrite prior artifacts.
    """
    run_path = Path(run_path).resolve()
    run = _json(run_path)
    if run.get("artifact_type") != "AUCompactRun" or not isinstance(run.get("request_ledger"), list):
        raise ComparisonError("expected AUCompactRun with normalized request_ledger")
    kos_manifest = Path(kos_manifest).resolve()
    inventory, kos_units, parse_errors = _load_kos(kos_root, _json(kos_manifest))
    rows = run["request_ledger"]
    requests = [r["request"] for r in rows]
    ids = [r["request_id"] for r in requests]
    if len(ids) != len(set(ids)):
        raise ComparisonError("duplicate run request ID; use final resumed run snapshot")
    workload = _json(workload_manifest) if workload_manifest else None
    expected_requests = workload.get("requests", []) if workload else requests
    expected_ids = [r["request_id"] for r in expected_requests]
    if len(expected_ids) != len(set(expected_ids)) or (workload is not None and not expected_requests):
        raise ComparisonError("empty or duplicate workload requests")
    sources, source_details = {}, []
    for case in inventory:
        case_id = case["case_id"]
        hashes = {r["source_hash"] for r in requests + expected_requests if r["case_id"] == case_id}
        if len(hashes) > 1:
            raise ComparisonError("multiple source versions for case " + case_id)
        if not hashes:
            index = _json(Path(source_store) / "cases" / case_id / "index.json")
            hashes = {index["current_source_hash"]}
            origin = "source_store_current_for_unrun_case"
        else:
            origin = "request_locked"
        source_hash = next(iter(hashes))
        source = open_source(source_store, case_id, source_hash)
        sources[case_id] = (source_hash, source)
        source_details.append({"case_id": case_id, "source_hash": source_hash, "char_length": len(source), "status": "hash_verified", "version_selection": origin,
                               "source_ref": str((Path(source_store) / "cases" / case_id / "versions" / source_hash / "source.txt").resolve())})
    for request in requests + expected_requests:
        if request["case_id"] not in sources or request["source_hash"] != sources[request["case_id"]][0]:
            raise ComparisonError("request outside selected KOS/source identity")
        source = sources[request["case_id"]][1]
        if (not request.get("expected_target_ids") or len(request["expected_target_ids"]) != len(set(request["expected_target_ids"]))
                or any(not _valid_span(s, source) for s in request.get("source_refs", []))):
            raise ComparisonError("invalid request target/source spans")
        for ref in request.get("source_refs", []):
            if ref.get("role") not in {"target", "context"} or not isinstance(ref.get("target_ids"), list):
                raise ComparisonError("invalid source ref role/ownership")
            if ref["role"] == "target" and (not ref["target_ids"] or not set(ref["target_ids"]) <= set(request["expected_target_ids"])):
                raise ComparisonError("source ref targets not owned by request")
            for field in ("case_id", "source_hash"):
                if field in ref and ref[field] != request[field]:
                    raise ComparisonError("source ref case/hash identity mismatch")
        for tid in request["expected_target_ids"]:
            if not any(s.get("role") == "target" and tid in s.get("target_ids", []) for s in request.get("source_refs", [])):
                raise ComparisonError("target has no primary source span")
    expected_by_id = {r["request_id"]: r for r in expected_requests}
    unexpected_ids = set(ids) - set(expected_ids) if workload else set()
    if workload:
        for request in requests:
            expected = expected_by_id.get(request["request_id"])
            # Historical pilot request namespaces can differ from M1. Keep their
            # verified candidates, but never credit them as expected requests.
            if expected is not None and any(request.get(k) != expected.get(k) for k in ("case_id", "source_hash", "expected_target_ids", "source_refs")):
                raise ComparisonError("run request does not match expected workload")
    validator = Draft202012Validator(_json(FULL_SCHEMA))
    target_rows, model_units, request_states = [], [], []
    for row in rows:
        request = row["request"]; source_hash, source = sources[request["case_id"]]
        try:
            readable, evidence_scope = _supplied_evidence(request, source, atom_root)
            errors = _validate_response(row, source, validator, readable)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors = ["atom_catalog_binding_failed: " + str(exc)]
            evidence_scope = {"status": "invalid_binding", "expansion_verified": False}
        targets = {t["target_id"]: t for t in row["response"]["target_results"]} if not errors else {}
        raw = row.get("compact_response")
        needs_split = isinstance(raw, dict) and raw.get("coverage_status") == "needs_split"
        request_states.append({"request_id": request["request_id"], "status": row.get("status"), "validation_errors": errors, "needs_split": needs_split, "evidence_scope": evidence_scope})
        for tid in request["expected_target_ids"]:
            target = targets.get(tid, {})
            state = "invalid_or_unresolved" if errors else "needs_split" if needs_split else "unresolved" if target.get("decision") == "unresolved" else "covered"
            spans = [s for s in request["source_refs"] if s.get("role") == "target" and tid in s.get("target_ids", [])]
            target_rows.append({"case_id": request["case_id"], "source_hash": source_hash, "request_id": request["request_id"], "target_id": tid, "status": state, "decision": target.get("decision"), "spans": spans,
                                "hard_negative_reason": target.get("hard_negative_reason"), "unresolved_reason": target.get("unresolved_reason"), "reason_detail": target.get("reason_detail"),
                                "expected_workload_member": request["request_id"] in expected_by_id if workload else None})
            if not errors:
                for au in target.get("authority_units", []):
                    model_units.append({**au, "model_id": request["request_id"] + "/" + au["local_au_id"],
                                        "request_id": request["request_id"], "target_id": tid,
                                        "case_id": request["case_id"], "source_hash": source_hash,
                                        "validation_status": "normalized_schema_source_verified", "evidence_scope_status": evidence_scope["status"], "coverage_status": state})
    seen_targets = [(t["case_id"], t["target_id"]) for t in target_rows]
    if len(seen_targets) != len(set(seen_targets)):
        raise ComparisonError("duplicate actual target ownership")
    for request in expected_requests:
        if request["request_id"] not in ids:
            for tid in request["expected_target_ids"]:
                target_rows.append({"case_id": request["case_id"], "source_hash": request["source_hash"], "request_id": request["request_id"], "target_id": tid, "status": "unrun", "decision": None,
                                    "spans": [s for s in request["source_refs"] if s.get("role") == "target" and tid in s.get("target_ids", [])], "expected_workload_member": True})
    expected_targets = [(r["case_id"], tid) for r in expected_requests for tid in r["expected_target_ids"]]
    if len(expected_targets) != len(set(expected_targets)):
        raise ComparisonError("duplicate expected target ownership")
    matches = []
    for unit in kos_units:
        source_hash, source = sources[unit["case_id"]]
        unit["source_hash"] = source_hash
        alignment = align_evidence(unit["evidence_text"], source); unit["alignment"] = alignment
        overlaps = []
        for model in model_units:
            if model["case_id"] != unit["case_id"]:
                continue
            for span_index, span in enumerate(alignment["spans"]):
                chars = _overlap([span], model["evidence_spans"])
                if not chars:
                    continue
                differences = {"kind": {"kos": unit["kind"], "model": model["kind"], "different": unit["kind"] != model["kind"]},
                               "claim": {"kos": unit["claim_text"], "model": model["claim_text"], "whitespace_equal": re.sub(r"\s+", " ", unit["claim_text"]).strip() == re.sub(r"\s+", " ", model["claim_text"]).strip(), "semantic_equivalence": "not_assessed"},
                               "attribution": {"kos": unit["attribution"], "kos_speaker": unit["speaker"], "kos_role": unit["metadata"].get("attribution_role"), "model": model["attributions"],
                                               "speaker_different": all(a["speaker"] != unit["speaker"] for a in model["attributions"]) if unit["speaker"] is not None else None,
                                               "role_different": all(a["role"] != unit["metadata"]["attribution_role"] for a in model["attributions"]) if unit["metadata"].get("attribution_role") is not None else None,
                                               "status": "reference_metadata_missing" if unit["attribution"] is None and unit["speaker"] is None and unit["metadata"].get("attribution_role") is None else "manual_review_required"}}
                matches.append({"kos_id": unit["kos_id"], "model_id": model["model_id"], "case_id": unit["case_id"], "source_hash": source_hash, "alignment_candidate_index": span_index,
                                "status": "heuristic_overlap_candidate", "ambiguous_alignment": alignment["status"] == "ambiguous", "overlap_chars": chars,
                                "kos_fraction": chars / _length([span]), "model_fraction": chars / _length(model["evidence_spans"]), "differences": differences})
                overlaps.append(model["model_id"])
        unit["candidate_model_ids"] = sorted(set(overlaps))
        covered = [s for t in target_rows if t["case_id"] == unit["case_id"] and t["status"] == "covered" for s in t["spans"]]
        observed = [s for t in target_rows if t["case_id"] == unit["case_id"] and t["status"] != "unrun" for s in t["spans"]]
        planned = [s for t in target_rows if t["case_id"] == unit["case_id"] and t.get("expected_workload_member") for s in t["spans"]]
        if alignment["status"] in ("empty_evidence", "no_match", "ambiguous"):
            unit["comparison_status"] = "unresolved_alignment"
        elif overlaps:
            unit["comparison_status"] = "heuristic_candidates"
        elif _overlap(alignment["spans"], covered) == _length(alignment["spans"]):
            unit["comparison_status"] = "missing_reference_in_covered_evidence"
        elif _overlap(alignment["spans"], observed):
            unit["comparison_status"] = "not_assessable_partial_or_unresolved_coverage"
        elif _overlap(alignment["spans"], planned):
            unit["comparison_status"] = "not_assessable_unrun_expected_workload"
        else:
            unit["comparison_status"] = "outside_observed_workload"
    for model in model_units:
        links = [m for m in matches if m["model_id"] == model["model_id"]]
        model["candidate_kos_ids"] = sorted({m["kos_id"] for m in links})
        case_has_reference = any(u["case_id"] == model["case_id"] for u in kos_units)
        case_has_parse_error = any(e["case_id"] == model["case_id"] for e in parse_errors)
        model["comparison_status"] = ("heuristic_candidates" if links else "unresolved_reference_parse" if case_has_parse_error
                                      else "no_reference_annotation" if not case_has_reference else "extra_model_candidate_reference_not_exhaustive")
    # Bipartite connected components expose potential split/merge rather than committing matches.
    graph = {}
    for match in matches:
        a, b = ("kos", match["case_id"], match["kos_id"]), ("model", match["case_id"], match["model_id"])
        graph.setdefault(a, set()).add(b); graph.setdefault(b, set()).add(a)
    groups, visited = [], set()
    for node in sorted(graph):
        if node in visited:
            continue
        queue, component = [node], set()
        while queue:
            current = queue.pop()
            if current in component:
                continue
            component.add(current); queue.extend(graph[current] - component)
        visited.update(component)
        ks = sorted(n[2] for n in component if n[0] == "kos"); ms = sorted(n[2] for n in component if n[0] == "model")
        relation = "one_to_one" if len(ks) == len(ms) == 1 else "possible_split" if len(ks) == 1 else "possible_merge" if len(ms) == 1 else "many_to_many"
        groups.append({"case_id": node[1], "kos_ids": ks, "model_ids": ms, "relation": relation, "status": "heuristic_manual_review_required"})
    unresolved_ids = set(run.get("pending_request_ids", [])) | (set(run.get("selection_request_ids", [])) - set(ids))
    coverage = {"expected_workload_supplied": workload is not None, "expected_request_count": len(expected_requests) if workload else None,
                "actual_request_count": len(rows), "expected_target_count": len(expected_targets) if workload else None,
                "actual_target_count": len(seen_targets), "target_status_counts": dict(Counter(t["status"] for t in target_rows)),
                "unexpected_actual_request_ids": sorted(unexpected_ids),
                "expected_target_status_counts": dict(Counter(t["status"] for t in target_rows if t.get("expected_workload_member"))),
                "pending_or_unrun_request_ids": sorted(unresolved_ids | (set(expected_ids) - set(ids))),
                "expected_workload_complete": bool(workload) and all(t["status"] == "covered" for t in target_rows if t.get("expected_workload_member")) and not unresolved_ids and not unexpected_ids,
                "run_reported_status": run.get("status"), "run_coverage_metadata": run.get("coverage"),
                "milestone1": workload.get("milestone1") if workload else None,
                "scope_note": "Expected completeness refers only to the supplied locked requests, never inferred from ten-target smoke output."}
    coverage["cases"] = []
    for case_id, (source_hash, source) in sources.items():
        actual = [t for t in target_rows if t["case_id"] == case_id and t["status"] != "unrun"]
        expected = [t for t in target_rows if t["case_id"] == case_id and t.get("expected_workload_member")]
        coverage["cases"].append({"case_id": case_id, "source_hash": source_hash,
                                  "source_chars": len(source), "actual_target_count": len(actual),
                                  "actual_target_status_counts": dict(Counter(t["status"] for t in actual)),
                                  "actual_primary_char_union": _length([s for t in actual for s in t["spans"]]),
                                  "covered_primary_char_union": _length([s for t in actual if t["status"] == "covered" for s in t["spans"]]),
                                  "expected_target_count": len(expected) if workload else None,
                                  "expected_primary_char_union": _length([s for t in expected for s in t["spans"]]) if workload else None})
    report = {"artifact_type": "KOSAUComparison", "schema_version": "kos-au-comparison-v1", "status": "materialized",
              "reference_role": "KOS_reference_only", "semantic_gold": False, "semantic_quality_claim": False, "equivalence_claim": False,
              "inputs": {"run": str(run_path), "run_sha256": _sha(run_path.read_bytes()), "kos_root": str(Path(kos_root).resolve()),
                         "kos_manifest": str(kos_manifest), "kos_manifest_sha256": _sha(kos_manifest.read_bytes()),
                         "source_store": str(Path(source_store).resolve()), "workload_manifest": str(Path(workload_manifest).resolve()) if workload_manifest else None,
                         "atom_root": str(Path(atom_root).resolve()),
                         "workload_manifest_sha256": _sha(Path(workload_manifest).read_bytes()) if workload_manifest else None},
              "kos_inventory": inventory, "sources": source_details, "coverage": coverage,
              "counts": {"kos_file_count": sum(c["file_count"] for c in inventory), "kos_au_count": len(kos_units), "validated_model_au_count": len(model_units),
                         "kos_status_counts": dict(Counter(u["comparison_status"] for u in kos_units)), "model_status_counts": dict(Counter(u["comparison_status"] for u in model_units)), "heuristic_candidate_pair_count": len({(m["case_id"], m["kos_id"], m["model_id"]) for m in matches}), "heuristic_alignment_candidate_count": len(matches), "kos_parse_error_count": len(parse_errors)},
              "kos_units": kos_units, "model_units": model_units, "heuristic_matches": matches, "split_merge_candidates": groups,
              "targets": target_rows, "request_states": request_states, "kos_parse_errors": parse_errors, "cost": _cost(run, run_path),
              "limitations": ["Overlap is a review candidate, not semantic equivalence or retrieval proof.", "KOS is neither exhaustive nor gold; missing/extra are reference differences, not precision/recall.", "Ambiguous/no-match evidence has no authoritative assigned offset.", "Only normalized schema/quote-verified output is compared; raw and failed output remains unresolved.", "Bound requests use reconstructed hash-verified supplied atom catalogs; legacy no-binding requests use raw refs only and have unproven expansion.", "YAML parser supports the selected flat front matter and scalar lists; unsupported structures are explicit parse errors."]}
    if output_root is not None:
        _write_report(report, output_root, kos_root, source_store, run_path, {case_id: text for case_id, (_, text) in sources.items()})
    return report


def _render_html(report, source_texts=None):
    def escaped(value):
        return html.escape(json.dumps(value, ensure_ascii=False, indent=2) if not isinstance(value, str) else value, quote=True)
    parts = ['<!doctype html><html lang="en"><meta charset="utf-8"><title>KOS AU reference comparison</title>',
             '<style>body{font:16px system-ui;max-width:1200px;margin:2em auto;padding:1em}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f5f5;padding:1em}article{border-top:1px solid #bbb;padding:1em 0}summary{cursor:pointer}h2{margin-top:2em}</style>',
             '<h1>KOS AU reference comparison</h1><p>KOS reference only. Heuristic overlap candidates require review. No gold, equivalence or semantic quality claim.</p>']
    for field in ("counts", "coverage", "sources", "inputs", "cost", "kos_parse_errors", "request_states", "split_merge_candidates"):
        parts.append('<h2>' + escaped(field) + '</h2><pre>' + escaped(report[field]) + '</pre>')
    models = {m["model_id"]: m for m in report["model_units"]}
    parts.append('<h2>KOS evidence and model candidates</h2>')
    for unit in report["kos_units"]:
        parts.append('<article><h3>' + escaped(unit["case_id"] + " / " + unit["kos_id"]) + '</h3><pre>' + escaped(unit) + '</pre>')
        for mid in unit["candidate_model_ids"]:
            parts.append('<details><summary>Model candidate ' + escaped(mid) + '</summary><pre>' + escaped(models[mid]) + '</pre><pre>' + escaped([m for m in report["heuristic_matches"] if m["model_id"] == mid and m["kos_id"] == unit["kos_id"]]) + '</pre></details>')
        parts.append('</article>')
    parts.append('<h2>All validated model AU candidates, including extra</h2><pre>' + escaped(report["model_units"]) + '</pre><h2>Target coverage</h2><pre>' + escaped(report["targets"]) + '</pre><h2>Limitations</h2><pre>' + escaped(report["limitations"]) + '</pre>')
    if source_texts:
        parts.append('<h2>Verified source text (Unicode codepoint offsets)</h2>')
        for source in report["sources"]:
            case_id = source["case_id"]
            parts.append('<details><summary>Case ' + escaped(case_id) + ' — SHA256 ' + escaped(source["source_hash"]) + '</summary><pre>' + escaped(source_texts[case_id]) + '</pre></details>')
    parts.append('</html>')
    return '\n'.join(parts)


def _write_report(report, output_root, kos_root, source_store, run_path, source_texts):
    root = Path(output_root).resolve()
    # Neither a source input nor a historic output directory may be overwritten.
    for protected in (Path(kos_root).resolve(), Path(source_store).resolve(), run_path.parent):
        if _inside(root, protected) or _inside(protected, root):
            raise ComparisonError("output overlaps protected input/history directory")
    if root.exists():
        raise ComparisonError("output_root must be a new directory; refusing historical overwrite")
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    page = _render_html(report, source_texts)
    root.mkdir(parents=True, exist_ok=False)
    (root / "comparison.json").write_text(payload, encoding="utf-8")
    (root / "comparison.html").write_text(page, encoding="utf-8")
