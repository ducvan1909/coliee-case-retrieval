"""Frozen source-bound repair inputs. No model calls and no gold/KOS ingestion."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator

from ..au_candidate_store.core import _catalog, _exact_span, _hash, build_store
from ..au_candidate_store.reviews import _quote, run_sha256
from ..au_compact.manifest import _binding_path
from ..au_only.atom_binding import resolve
from ..source_contract import open_source

CONTRACTS = Path(__file__).resolve().parents[1] / "contracts"
MODEL = "Qwen/Qwen3.5-9B"
POLICY = {"input_tokens": 6000, "output_tokens": 1200, "total_tokens": 20000,
          "source_model_attempts": 8, "concurrency": 1, "tool_calls": 8,
          "model_turns": 2, "expansions": 1, "expansion_chars": 1200}


def safe_error(exc):
    code = str(exc)
    return {"type": type(exc).__name__, "code": code if isinstance(exc, ValueError) and
            re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,95}", code) else type(exc).__name__}


def guard_output(output_root, source_store, atom_root):
    destination = Path(output_root).resolve()
    for protected in (source_store, atom_root):
        if protected and destination.is_relative_to(Path(protected).resolve()):
            raise ValueError("output_root_overlaps_source")


def load(path):
    def strict(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=strict)


def validate(name, value):
    version = "v2" if name == "revision" and value.get("schema_version") == "repair-revision-v2" else "v1"
    schema = load(CONTRACTS / ("repair_" + name + "." + version + ".json"))
    Draft202012Validator(schema).validate(value)
    return value


def atomic(path, value, *, immutable=False):
    path = Path(path)
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    if immutable and path.exists():
        if path.read_text(encoding="utf-8") != encoded:
            raise ValueError("immutable_artifact_conflict")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(encoded, encoding="utf-8")
    temporary.replace(path)


def file_ref(path):
    return {"path": str(Path(path).resolve()), "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest()}


def _review_check(run, review, run_digest, source_store, atom_root):
    validate_review = Draft202012Validator(load(CONTRACTS / "au_candidate_review.v1.json"))
    validate_review.validate(review)
    rows = {}
    for row in run["request_ledger"]:
        rid = row["request"]["request_id"]
        if rid in rows:
            raise ValueError("ambiguous_request_binding")
        rows[rid] = row
    for entry in review["reviews"]:
        if entry["run_sha256"] != run_digest or entry["request_id"] not in rows:
            raise ValueError("stale_review_binding")
        row = rows[entry["request_id"]]
        proposal = row.get("compact_response")
        if entry["review_type"] == "au":
            index = entry["au_index"]
            if not 0 <= index < len(proposal.get("aus", [])):
                raise ValueError("review_proposal_not_found")
            proposal = proposal["aus"][index]
        if _hash(proposal) != entry["proposal_sha256"]:
            raise ValueError("stale_review_proposal")
        atoms, invalid, targets = _catalog(row["request"], source_store, atom_root)
        if invalid:
            raise ValueError("invalid_review_catalog")
        selected = atoms if entry["review_type"] != "au" else {
            aid: atoms[aid] for aid in proposal["evidence_ref_ids"] if aid in atoms}
        primary = entry.get("primary_proposition")
        if primary:
            _quote(primary, selected, targets, primary=True)
        for witness in entry.get("witnesses", []):
            _quote(witness, atoms, targets, primary=True)
        for witnesses in entry.get("field_witnesses", {}).values():
            for witness in witnesses:
                _quote(witness, selected, targets)
        for witness in entry.get("material_conditions", {}).get("witnesses", []):
            _quote(witness, selected, targets)


def _expansion_catalog(request, source_store, atom_root, initial):
    """Adjacent complete atoms only, within 1200 chars of the initial view."""
    source = open_source(source_store, request["case_id"], request["source_hash"])
    atom_map = resolve(_binding_path(request["atom_binding"], atom_root))
    lo = min(a["start_char"] for a in initial.values())
    hi = max(a["end_char"] for a in initial.values())
    catalog = []
    for atom in atom_map["atoms"]:
        if atom["atom_id"] in initial:
            continue
        if atom.get("case_id") != request["case_id"] or atom.get("source_hash") != request["source_hash"]:
            raise ValueError("expansion_identity_mismatch")
        span = _exact_span(atom["span"], source, request["case_id"], request["source_hash"])
        if "quote" in atom and atom["quote"] != span["quote"]:
            raise ValueError("expansion_quote_mismatch")
        direction = "before" if span["end_char"] <= lo else "after" if span["start_char"] >= hi else None
        if direction and span["start_char"] >= lo - POLICY["expansion_chars"] and span["end_char"] <= hi + POLICY["expansion_chars"]:
            catalog.append({**span, "atom_id": atom["atom_id"], "direction": direction})
    if len({a["atom_id"] for a in catalog}) != len(catalog):
        raise ValueError("duplicate_expansion_atom")
    return sorted(catalog, key=lambda a: (a["start_char"], a["atom_id"]))


def build_tasks(run, review, source_store, atom_root, output_root=None):
    """Build one task per target, retaining exact proposals and arm aliases.

    Semantic triggers come only from bound agent review. Technical invalidity
    remains host-owned; controls are reviewed targets without a semantic fail.
    """
    if output_root is not None:
        guard_output(output_root, source_store, atom_root)
    report, sidecar = load(run), load(review)
    _review_check(report, sidecar, run_sha256(run), source_store, atom_root)
    store = build_store(run, source_store, atom_root, reviews=review)
    groups = {}
    for row in report["request_ledger"]:
        request = row["request"]
        if len(request.get("expected_target_ids", [])) != 1:
            raise ValueError("one_target_required")
        key = (request["case_id"], request["source_hash"], request["expected_target_ids"][0])
        groups.setdefault(key, []).append(row)
    tasks = []
    for (case_id, source_hash, target_id), rows in sorted(groups.items()):
        rows.sort(key=lambda r: (r["request"].get("arm") != "P2a", r["request"]["request_id"]))
        row = rows[0]
        request = copy.deepcopy(row["request"])
        atoms, invalid, targets = _catalog(request, source_store, atom_root)
        if invalid or not atoms:
            raise ValueError("task_catalog_invalid")
        for other in rows:
            _, _, other_targets = _catalog(other["request"], source_store, atom_root)
            if targets != other_targets:
                raise ValueError("group_target_bounds_disagree")
        rids = {r["request"]["request_id"] for r in rows}
        oracle = [copy.deepcopy(e) for e in sidecar["reviews"] if e["request_id"] in rids]
        semantic_errors = [e for e in oracle if "fail" in e.get("checks", {}).values()]
        originals = {}
        for other in rows:
            for index, proposal in enumerate((other.get("compact_response") or {}).get("aus", [])):
                digest = _hash(proposal)
                item = originals.setdefault(digest, {"proposal_id": "proposal-" + digest,
                    "proposal_sha256": digest, "proposal": copy.deepcopy(proposal), "aliases": []})
                item["aliases"].append({"request_id": other["request"]["request_id"],
                    "arm": other["request"].get("arm", "unknown"), "au_index": index})
        technical = [copy.deepcopy(l) for l in store["target_ledger"] if l.get("request_id") in rids and l.get("errors")]
        technical += [copy.deepcopy(c) for c in store["candidates"] if c["provenance"]["request_id"] in rids and c["structural_status"] != "valid"]
        task = {"artifact_type": "RepairTask", "schema_version": "repair-task-v1",
            "task_id": "task-" + _hash([case_id, source_hash, target_id]),
            "case_id": case_id, "source_hash": source_hash, "target_id": target_id,
            "raw_targets": targets, "request": request,
            "original_proposals": list(originals.values()),
            "original_responses": [r.get("compact_response") for r in rows],
            "supplied_atom_catalog": list(atoms.values()),
            "expansion_atom_catalog": _expansion_catalog(request, source_store, atom_root, atoms),
            "review_oracle": oracle, "error_origin": "agent_review",
            "technical_errors_origin": "host", "technical_errors": technical,
            "selection": "repair" if semantic_errors else "correct_control" if oracle else "unreviewed_control",
            "semantic_errors": semantic_errors, "obligations": [],
            "model": MODEL, "policy": POLICY, "semantic_gold": False}
        # Do not invent missing-context ground truth from a qualification fail.
        for item in task["original_proposals"]:
            for need in item["proposal"].get("needs_context", []):
                oid = "obligation-" + _hash([task["task_id"], item["proposal_id"], need])
                task["obligations"].append({"obligation_id": oid, "task_id": task["task_id"],
                    "target_id": target_id, "obligation_type": need, "requested_direction_or_ref": "unknown",
                    "reason": "Original model requested context", "producer": "source_model",
                    "run_id": run_sha256(run), "status": "pending", "searched_spans": [],
                    "stop_reason": None, "review_confirmation": None})
        validate("task", task)
        tasks.append(task)
    manifest = {"artifact_type": "RepairManifest", "schema_version": "repair-manifest-v1",
        "inputs": {"run": file_ref(run), "review": file_ref(review)},
        "source_store": str(Path(source_store).resolve()), "atom_root": str(Path(atom_root).resolve()),
        "source_workload": load(Path(source_store) / "source_store_manifest.json").get("cases", []),
        "task_case_ids": sorted({t["case_id"] for t in tasks}), "task_count": len(tasks),
        "task_workload": "v6 output subset; not full KOS-5", "model": MODEL,
        "reviewer": sidecar["reviewer"], "policy": POLICY, "tasks": tasks,
        "semantic_gold": False, "semantic_metrics": None}
    manifest["manifest_sha256"] = _hash(manifest)
    if output_root:
        atomic(Path(output_root) / "manifest.json", manifest, immutable=True)
    return manifest


def verify_manifest(manifest, source_store=None, atom_root=None):
    frozen = copy.deepcopy(manifest)
    digest = frozen.pop("manifest_sha256")
    if _hash(frozen) != digest or manifest["policy"] != POLICY or manifest["model"] != MODEL:
        raise ValueError("manifest_fingerprint_mismatch")
    for ref in manifest["inputs"].values():
        if file_ref(ref["path"]) != ref:
            raise ValueError("manifest_input_changed")
    source_store = source_store or manifest["source_store"]
    atom_root = atom_root or manifest["atom_root"]
    rebuilt = build_tasks(manifest["inputs"]["run"]["path"], manifest["inputs"]["review"]["path"], source_store, atom_root)
    if rebuilt["tasks"] != manifest["tasks"] or rebuilt["source_workload"] != manifest["source_workload"]:
        raise ValueError("manifest_source_or_task_changed")
    return True
