"""Source-free FORMAL checks. Host validity is not grammar or semantic proof."""
from __future__ import annotations

import copy
import json
import time
import uuid
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

from .core import MODEL, POLICY, atomic, safe_error
from .wire import decoding, normalize, payload, wire_schema
from .selection import (VERSION as WIRE_VERSION, evidence_catalog, model_catalog,
                        selection_schema, normalize_selection)
from .runtime import estimate_input
from .boundary_probe import (boundary_case, boundary_matches, probe_decoding,
                             observe_boundary)
from .tools import RepairSession
from .grammar import DECISION_RELATION_LIMIT
from ..au_candidate_store.core import _hash

VERSION = "repair-formal-suite-selection-relations-v3"
KNOWN_GAPS = ["primary membership in AU evidence (host relationship check)"]


def synthetic_task(count=1):
    digest = _hash("formal synthetic source")
    atom = dict(case_id="011904", source_hash=digest, atom_id="a",
                start_char=0, end_char=7, quote="Rule X.")
    au = dict(kind="holding", other_kind=None, claim="Rule X.", evidence_ref_ids=["a"],
              speaker="current_court", attribution_role="proposition", needs_context=[])
    proposals = []
    for i in range(count):
        candidate = dict(au, claim="Rule X. " + str(i))
        sha = _hash(candidate)
        proposals.append(dict(proposal_id="proposal-" + sha, proposal_sha256=sha,
                              proposal=candidate, aliases=[]))
    return dict(artifact_type="RepairTask", schema_version="repair-task-v1", task_id="formal-task",
                case_id="011904", source_hash=digest, target_id="formal-target",
                raw_targets=[{k: v for k, v in atom.items() if k != "atom_id"}], request={},
                original_proposals=proposals, original_responses=[], supplied_atom_catalog=[atom],
                expansion_atom_catalog=[dict(atom, atom_id="b", start_char=8, end_char=17,
                                             quote="Unless Y.", direction="after")],
                review_oracle=[], error_origin="agent_review", technical_errors_origin="host",
                technical_errors=[], selection="repair", semantic_errors=[], obligations=[],
                model=MODEL, policy=POLICY, semantic_gold=False)


def envelope(task, verdict="uncertain", action="reject"):
    decisions = []
    for p in task["original_proposals"]:
        d = dict(proposal_id=p["proposal_id"], verdict=verdict, reason="Synthetic formal check")
        witness = dict(atom_id="a", quote="Rule X.")
        if verdict == "supported":
            d["primary_proposition"] = witness
        if verdict == "defect_found":
            d.update(defect_type="qualification", witnesses=[witness], correction=dict(action=action))
            if action == "replace":
                d["correction"]["replacements"] = [dict(au=copy.deepcopy(p["proposal"]), primary_proposition=witness)]
        decisions.append(d)
    return dict(tool_calls=[dict(name="submit_revision", arguments=dict(task_id=task["task_id"], decisions=decisions))])


def _at(value, path):
    for key in path:
        value = value[key]
    return value


def fixtures():
    """Independent expected-valid/invalid outputs, never remote expected answers."""
    rows = []
    t = synthetic_task()
    dpath = ["tool_calls", 0, "arguments", "decisions", 0]
    apath = dpath + ["correction", "replacements", 0, "au"]

    def add(cid, out, valid, *, task=t, arm="R1", turn=1, path=dpath, branch=None):
        rows.append(dict(case_id=cid, output=out, expected_valid=valid, task=copy.deepcopy(task),
                         arm=arm, turn=turn, target_path=path, branch=branch))

    def change(cid, path, value, valid=False, verdict="uncertain", action="reject"):
        out = envelope(t, verdict, action)
        _at(out, path[:-1])[path[-1]] = value
        add(cid, out, valid, path=path, branch=verdict)

    for verdict, action in [("uncertain", "reject"), ("supported", "reject"),
                            ("defect_found", "reject"), ("defect_found", "replace")]:
        add(verdict + "_" + action, envelope(t, verdict, action), True, branch=verdict)
    for length in (0, 1, 120, 121):
        change("reason_length_" + str(length), dpath + ["reason"], "x" * length, 1 <= length <= 120)
    change("reason_unicode_escape", dpath + ["reason"], 'Luật 😀 \\ "\n\t', True)
    change("reason_unicode_120", dpath + ["reason"], "😀" * 120, True)
    change("reason_unicode_121", dpath + ["reason"], "😀" * 121)
    for length in (0, 1, 300, 301):
        change("claim_length_" + str(length), apath + ["claim"], "x" * length,
               1 <= length <= 300, "defect_found", "replace")
    change("claim_unicode_escape", apath + ["claim"], 'Điều 😀 \\ "\n', True, "defect_found", "replace")
    for field, value in [("claim", []), ("speaker", 7), ("kind", "foreign"),
                         ("attribution_role", "foreign"), ("evidence_ref_ids", ["foreign"])]:
        change("invalid_au_" + field, apath + [field], value, False, "defect_found", "replace")
    for field in ("claim", "speaker", "evidence_ref_ids"):
        out = envelope(t, "defect_found", "replace"); del _at(out, apath)[field]
        add("missing_au_" + field, out, False, path=apath, branch="defect_found")
    change("extra_au_field", apath + ["extra"], True, False, "defect_found", "replace")
    for length in (0, 1, 160, 161):
        out = envelope(t, "defect_found", "replace")
        _at(out, apath).update(kind="other", other_kind="x" * length)
        add("other_kind_length_" + str(length), out, 1 <= length <= 160, path=apath + ["other_kind"], branch="other")
    for name, value in [("null", None), ("missing", None)]:
        out = envelope(t, "defect_found", "replace")
        au = _at(out, apath); au["kind"] = "other"
        if name == "missing": del au["other_kind"]
        else: au["other_kind"] = value
        add("other_kind_" + name, out, False, path=apath + ["other_kind"], branch="other")
    change("nonother_forbids_label", apath + ["other_kind"], "label", False, "defect_found", "replace")
    for field in ("evidence_ref_ids", "needs_context"):
        value = ["a", "a"] if field == "evidence_ref_ids" else ["condition", "condition"]
        change("unique_" + field, apath + [field], value, False, "defect_found", "replace")
    change("unique_needed_context", dpath + ["needed_context"], ["condition", "condition"])
    change("unique_witnesses", dpath + ["witnesses"], [dict(atom_id="a", quote="Rule X.")] * 2,
           False, "defect_found")
    for field, value in [("reason", None), ("reason", 7), ("verdict", "accept"), ("needed_context", ["foreign"]),
                         ("proposal_id", "foreign")]:
        change("invalid_" + field + "_" + type(value).__name__, dpath + [field], value)
    for field in ("reason", "proposal_id", "verdict"):
        out = envelope(t); del _at(out, dpath)[field]
        add("missing_" + field, out, False)
    change("extra_decision_field", dpath + ["extra"], True)
    change("foreign_task", ["tool_calls", 0, "arguments", "task_id"], "foreign")
    for count in (0, 2):
        out = envelope(t); out["tool_calls"] *= count
        add("call_count_" + str(count), out, False, path=["tool_calls"])
    for count in (0, 2):
        out = envelope(t); out["tool_calls"][0]["arguments"]["decisions"] *= count
        add("decision_count_" + str(count), out, False)
    two = synthetic_task(2)
    out = envelope(two); out["tool_calls"][0]["arguments"]["decisions"][1] = copy.deepcopy(_at(out, dpath))
    add("proposal_exact_once", out, False, task=two)
    for count in (1, 2):
        task = synthetic_task(count); out = envelope(task, "supported")
        d = _at(out, dpath)
        d.update(verdict="defect_found", defect_type="duplicate", witnesses=[d.pop("primary_proposition")],
                 retained_proposal_id=task["original_proposals"][-1]["proposal_id"], correction=dict(action="reject"))
        add("duplicate_" + str(count) + "_anchor", out, count == 2, task=task, branch="duplicate")
        if count == 2:
            for name in ("missing_retained", "replace", "uncertain_anchor", "cycle"):
                bad = copy.deepcopy(out); dup = _at(bad, dpath)
                if name == "missing_retained": del dup["retained_proposal_id"]
                if name == "replace": dup["correction"] = _at(envelope(t, "defect_found", "replace"), dpath)["correction"]
                if name == "uncertain_anchor": bad["tool_calls"][0]["arguments"]["decisions"][1] = envelope(task)["tool_calls"][0]["arguments"]["decisions"][1]
                if name == "cycle":
                    anchor = copy.deepcopy(dup); anchor.update(proposal_id=dup["retained_proposal_id"], retained_proposal_id=dup["proposal_id"])
                    bad["tool_calls"][0]["arguments"]["decisions"][1] = anchor
                add("duplicate_" + name, bad, False, task=task, branch="duplicate")
    change("nonduplicate_retained", dpath + ["retained_proposal_id"], t["original_proposals"][0]["proposal_id"], False, "defect_found")
    for arm, turn in [("R1", 1), ("R2", 1), ("R2", 2)]:
        for tool, args in [("get_repair_task", {}), ("get_related_aus", {}),
                           ("expand_context", dict(direction="after", reason="Read")),
                           ("open_span", dict(atom_id="a", start_char=0, end_char=7, quote="Rule X."))]:
            out = dict(tool_calls=[dict(name=tool, arguments=args)])
            add(f"{arm}_turn{turn}_{tool}", out, arm == "R2" and turn == 1, arm=arm, turn=turn, path=["tool_calls", 0, "name"], branch=tool)
    for name, args, valid in [("negative_start", dict(start_char=-1), False), ("zero_end", dict(end_char=0), False),
                              ("bool_start", dict(start_char=True), False), ("outside_end", dict(end_char=8), False),
                              ("reversed", dict(start_char=6, end_char=1), False), ("wrong_quote", dict(quote="Wrong"), False),
                              ("unread_atom", dict(atom_id="b"), False)]:
        out = dict(tool_calls=[dict(name="open_span", arguments=dict(atom_id="a", **{k:v for k,v in args.items() if k != "atom_id"}))])
        out["tool_calls"][0]["arguments"].update(args)
        add("offset_" + name, out, valid, arm="R2", path=["tool_calls", 0, "arguments"], branch="open_span")
    change("supported_wrong_quote", dpath + ["primary_proposition", "quote"], "Wrong", False, "supported")
    change("supported_unread_atom", dpath + ["primary_proposition", "atom_id"], "b", False, "supported")
    return rows


def validate_output(output, task, arm, turn, *, contract="full_v2"):
    """Detailed schema diagnostics only for synthetic model outputs; no config errors."""
    errors = []
    def collect(error):
        errors.append(dict(path=list(error.absolute_path), schema_path=list(error.absolute_schema_path),
                           validator=error.validator, message=error.message))
        for child in error.context: collect(child)
    if contract not in {"full_v2", "selection_v1"}: raise ValueError("unknown_formal_contract")
    schema = wire_schema(task, arm, turn, ["a"]) if contract == "full_v2" else selection_schema(task, arm, turn, ["a"])
    for error in Draft202012Validator(schema).iter_errors(output): collect(error)
    if errors: return dict(valid=False, schema_errors=errors, host_error=None)
    try:
        normalizer = normalize if contract == "full_v2" else normalize_selection
        full = normalizer(output, task, arm, turn, ["a"])
        call = full["tool_calls"][0]
        result = RepairSession(task, arm).call_tool(call["name"], call["arguments"])
        return dict(valid=result["ok"], schema_errors=[], host_error=result.get("error"),
                    contract=contract, full_contract_valid=result["ok"])
    except ValidationError as exc:
        collect(exc)
        return dict(valid=False, schema_errors=errors, host_error=None)
    except Exception as exc:
        return dict(valid=False, schema_errors=[], host_error=safe_error(exc))


def selection_fixture(fixture):
    """Map every legacy challenge explicitly, preserving invalid/duplicate cases.

    Invalid offset/quote challenges become unavailable selection IDs on transport;
    their original full-v2 host checks still execute unchanged.
    """
    f = copy.deepcopy(fixture)
    entries = evidence_catalog(f["task"], ["a"])["entries"]
    def select(w):
        return next((e["evidence_id"] for e in entries
                     if e["atom_id"] == w.get("atom_id") and e["quote"] == w.get("quote")),
                    "unavailable-" + _hash(w)[:20])
    out = f["output"]
    out["schema_version"] = WIRE_VERSION
    for call in out["tool_calls"]:
        args = call["arguments"]
        if call["name"] == "open_span":
            atom = next((a for a in f["task"]["supplied_atom_catalog"] if a["atom_id"] == args.get("atom_id")), None)
            match = next((e for e in entries if atom and e["atom_id"] == atom["atom_id"]
                          and type(args.get("start_char", atom["start_char"])) is int
                          and type(args.get("end_char", atom["end_char"])) is int
                          and e["start_char"] == args.get("start_char", atom["start_char"])
                          and e["end_char"] == args.get("end_char", atom["end_char"])
                          and e["quote"] == args.get("quote", e["quote"])), None)
            call["arguments"] = {"span_selection_id": match["evidence_id"] if match else "unavailable-" + _hash(args)[:20]}
        for d in args.get("decisions", []):
            if "primary_proposition" in d: d["primary_proposition"] = select(d["primary_proposition"])
            if "witnesses" in d: d["witnesses"] = [select(w) for w in d["witnesses"]]
            for r in d.get("correction", {}).get("replacements", []):
                r["primary_proposition"] = select(r["primary_proposition"])
    if f["target_path"][-1] in {"quote", "atom_id"}:
        f["target_path"] = f["target_path"][:-1]
    f["contract"] = "selection_v1"
    f["legacy_case_id"] = fixture["case_id"]
    return f


def selection_fixtures():
    return [selection_fixture(f) for f in fixtures()]


def remote_cases():
    # One challenge per fixture keeps identity stable and exposes all local targets.
    return [dict(case_id=f["case_id"], arm=f["arm"], turn=f["turn"], branch=f["branch"],
                 contract="selection_v1", expected_fixture_valid=f["expected_valid"], target_path=f["target_path"]) for f in selection_fixtures()]


def _coverage(output, fixture):
    # This helper observes valid-fixture targets only. It cannot establish
    # enforcement of an invalid value from a model choosing another value.
    if not fixture["expected_valid"]:
        return False
    try:
        value = _at(output, fixture["target_path"])
        branch = fixture["branch"]
        decisions = output["tool_calls"][0]["arguments"].get("decisions", [])
        target_decision = decisions[fixture["target_path"][4]] if len(fixture["target_path"]) > 4 and fixture["target_path"][3] == "decisions" else None
        if branch == "duplicate": return bool(target_decision and target_decision.get("verdict") == "defect_found" and target_decision.get("defect_type") == "duplicate")
        if branch == "other":
            if not target_decision or target_decision.get("verdict") != "defect_found": return False
            au = _at(output, fixture["target_path"][:-1])
            if au.get("kind") != "other": return False
        if branch in {"supported", "uncertain", "defect_found"}:
            if not target_decision or target_decision.get("verdict") != branch: return False
        if branch in {"open_span", "get_repair_task", "get_related_aus", "expand_context"}:
            return output["tool_calls"][0]["name"] == branch
        # Boundary fixtures require observing the valid boundary value; invalid
        # requests prove only valid host output under challenge, never enforcement.
        expected = _at(fixture["output"], fixture["target_path"])
        if boundary_case(fixture): return boundary_matches(value, fixture)
        return value == expected if fixture["expected_valid"] else True
    except (KeyError, IndexError, TypeError): return False


def _branch_exercised(output, fixture):
    """Separate observation from successful invalid-request challenge coverage."""
    try:
        if boundary_case(fixture):
            return _coverage(output, fixture) if fixture["expected_valid"] else False
        branch = fixture["branch"]
        call = output["tool_calls"][0]
        decisions = call["arguments"].get("decisions", [])
        target_decision = decisions[fixture["target_path"][4]] if len(fixture["target_path"]) > 4 and fixture["target_path"][3] == "decisions" else None
        if branch == "duplicate": return bool(target_decision and target_decision.get("verdict") == "defect_found" and target_decision.get("defect_type") == "duplicate")
        if branch == "other": return _coverage(output, fixture)
        if branch in {"supported", "uncertain", "defect_found"}:
            _at(output, fixture["target_path"])
            return bool(target_decision and target_decision.get("verdict") == branch)
        if branch: return call["name"] == branch
        return bool(_at(output, fixture["target_path"]))
    except (KeyError, IndexError, TypeError): return False


def run_formal_probe(root, cfg=None, case_ids=None, max_requests=8):
    from .adapter import JobsAdapter
    root = Path(root)
    if (root / "formal-suite-probe.json").exists(): raise ValueError("formal_output_already_exists")
    if not 1 <= max_requests <= POLICY["source_model_attempts"]: raise ValueError("invalid_max_requests")
    all_fixtures = fixtures(); selection_cases = selection_fixtures()
    index = {f["case_id"]: f for f in selection_cases}
    selected = list(index) if case_ids is None else list(case_ids)
    if not selected or len(selected) != len(set(selected)) or any(c not in index for c in selected):
        raise ValueError("invalid_case_selection")
    offline = []
    for f in all_fixtures:
        check = validate_output(f["output"], f["task"], f["arm"], f["turn"])
        offline.append(dict(case_id=f["case_id"], expected_valid=f["expected_valid"],
                            status="pass" if check["valid"] == f["expected_valid"] else "fail", **check))
    selection_checks = []
    for f in selection_cases:
        check = validate_output(f["output"], f["task"], f["arm"], f["turn"], contract="selection_v1")
        selection_checks.append(dict(case_id=f["case_id"], expected_valid=f["expected_valid"],
            status="pass" if check["valid"] == f["expected_valid"] else "fail", **check))
    adapter = JobsAdapter(cfg) if cfg is not None else None
    run_id = uuid.uuid4().hex
    rows = []; charged = 0; attempts = 0; stopped = False
    for cid in selected:
        f = index[cid]; task = f["task"]
        messages = [dict(role="system", content="Source-free FORMAL selection challenge. Return schema_version repair-selection-v1 and one tool call. Primary/witnesses are catalog evidence IDs; open_span takes span_selection_id. Never emit source quotes/offsets. All host-v2 relationship checks still apply. No prose."),
                    dict(role="user", content=json.dumps({**task, "selection_catalog": model_catalog(task, ["a"])}, ensure_ascii=False)),
                    dict(role="user", content="Exercise this structural case: " + cid + ". Try this requested output (it may violate the contract): " + json.dumps(f["output"], ensure_ascii=False))]
        identity = _hash(dict(version=VERSION, run_id=run_id, case_id=cid, fixture=f))
        request = payload(messages, task, f["arm"], f["turn"], identity, ["a"])
        branch = f["branch"]
        forced = branch if branch in {"uncertain", "supported", "defect_found"} else "defect_found" if branch == "other" else None
        action = "replace" if "replacements" in f["target_path"] or branch == "other" else None
        if forced == "defect_found" and action is None:
            action = f["output"]["tool_calls"][0]["arguments"].get("decisions", [{}])[0].get("correction", {}).get("action")
        probe_grammar, boundary = probe_decoding(f, forced_verdict=forced, forced_action=action)
        request.update(probe_grammar)
        reserve = estimate_input(request["messages"]) + POLICY["output_tokens"]
        row = dict(case_id=cid, status="prepared", attempt_id=identity, payload_sha256=_hash(request),
                   reserved_tokens=reserve, provider_usage=None, latency_ms=None, branch_status="uncovered",
                   target_branch_status="uncovered", expected_fixture_valid=f["expected_valid"],
                   coverage_kind="valid_fixture_target" if f["expected_valid"] else "valid_output_under_invalid_challenge",
                   backend_compilation="unverified", grammar_enforcement="unverified",
                   boundary_probe=boundary)
        atomic(root / (cid + ".payload.json"), request, immutable=True)
        if adapter:
            if stopped or attempts >= max_requests or charged + reserve > POLICY["total_tokens"] or reserve - POLICY["output_tokens"] > POLICY["input_tokens"]:
                row["status"] = "unrun_budget_or_prior_failure"
            else:
                attempts += 1; charged += reserve
                row["charged_or_reserved_tokens"] = reserve
                started = time.monotonic()
                adapter.prepare_payload = lambda *a, **k: request
                try:
                    response = adapter(messages, task=task, turn=f["turn"], arm=f["arm"], attempt_id=identity)
                    row["receipt"] = response; usage = response.get("provider_usage"); row["provider_usage"] = usage
                    if isinstance(usage, dict) and type(usage.get("total_tokens")) is int and usage["total_tokens"] >= 0:
                        charged += usage["total_tokens"] - reserve; row["charged_or_reserved_tokens"] = usage["total_tokens"]
                    cap = isinstance(usage, dict) and (charged > POLICY["total_tokens"] or usage.get("prompt_tokens", usage.get("input_tokens", 0)) > POLICY["input_tokens"] or usage.get("completion_tokens", usage.get("output_tokens", 0)) > POLICY["output_tokens"])
                    row["actual_usage_cap_violation"] = bool(cap)
                    check = validate_output(response.get("output"), task, f["arm"], f["turn"], contract="selection_v1")
                    row["validation"] = check
                    output = response.get("output")
                    observe_boundary(output, f, boundary)
                    covered = check["valid"] and (not f["expected_valid"] or _coverage(output, f))
                    if forced and check["valid"]:
                        ds = output["tool_calls"][0]["arguments"].get("decisions", [])
                        if any(d["verdict"] != forced for d in ds) or (action and any(d.get("correction", {}).get("action") != action for d in ds)):
                            check.update(valid=False, forced_branch_error="probe_branch_mismatch"); covered = False
                    row["branch_status"] = "covered" if covered else "uncovered"
                    row["target_branch_status"] = "exercised" if check["valid"] and _branch_exercised(output, f) else "uncovered"
                    row["status"] = "protocol_valid" if check["valid"] and not cap else "failed"
                    if cap or response.get("output") is None: stopped = True
                except Exception as exc:
                    row.update(status="failed", error=safe_error(exc))
                    if hasattr(exc, "safe_trace"): row["transport_trace"] = exc.safe_trace
                    stopped = True
                row["latency_ms"] = round((time.monotonic() - started) * 1000, 3)
        rows.append(row)
        atomic(root / (cid + ".result.json"), row, immutable=True)
    executed = [r["case_id"] for r in rows if "charged_or_reserved_tokens" in r]
    uncovered = [cid for cid in index if not any(r["case_id"] == cid and r["branch_status"] == "covered" for r in rows)]
    selected_complete = (not any(cid in uncovered for cid in selected) and all(r["status"] == "protocol_valid" for r in rows)
                        and all(r["status"] == "pass" for r in offline + selection_checks))
    report = dict(version=VERSION, suite_sha256=_hash(all_fixtures), selection_suite_sha256=_hash(selection_cases), run_id=run_id,
                  status="prepared" if adapter is None else "complete" if selected_complete else "incomplete",
                  selected_batch_status="prepared" if adapter is None else "complete" if selected_complete else "incomplete",
                  global_suite_status="complete" if adapter and not uncovered else "incomplete",
                  remote_execution_status="not_executed" if not adapter else "complete" if len(executed) == len(index) else "incomplete",
                  selected_execution_status="not_executed" if not adapter else "complete" if len(executed) == len(selected) else "incomplete",
                  remote_validation_status="not_executed" if not adapter else "pass" if executed and all(r["status"] == "protocol_valid" for r in rows if r["case_id"] in executed) else "fail",
                  remote_cases=remote_cases(), selected_case_ids=selected, executed_case_ids=executed,
                  unrun_case_ids=[cid for cid in index if cid not in executed], uncovered_case_ids=uncovered,
                  uncovered_selected_case_ids=[cid for cid in selected if cid in uncovered],
                  unexercised_target_branch_ids=[cid for cid in index if not any(r["case_id"] == cid and r["target_branch_status"] == "exercised" for r in rows)],
                  host_checks=offline, host_check_status="pass" if all(r["status"] == "pass" for r in offline) else "fail",
                  host_contract="full_v2", wire_contract=WIRE_VERSION, selection_checks=selection_checks,
                  selection_check_status="pass" if all(r["status"] == "pass" for r in selection_checks) else "fail",
                  cases=rows, known_grammar_gaps=KNOWN_GAPS, backend_compilation="unverified",
                  decision_relation_decoding=dict(max_proposals=DECISION_RELATION_LIMIT,
                      ordering="original_proposals", anchors="distinct_supported_in_same_response",
                      overflow="reject_before_dispatch", semantic_quality="not_evaluated"),
                  coverage="bounded representative formal cases; not exhaustive grammar verification",
                  semantic_quality="not_evaluated", source_quote_scope="synthetic exact-read checks only",
                  cost_summary=dict(attempts=attempts, charged_or_reserved_tokens=charged,
                                    provider_usage_unknown_attempts=sum("charged_or_reserved_tokens" in r and r["provider_usage"] is None for r in rows),
                                    latency_ms=sum(r["latency_ms"] or 0 for r in rows)))
    atomic(root / "formal-suite-probe.json", report, immutable=True)
    return report


def aggregate_reports(reports):
    """Aggregate disjoint/chunk attempts; callers keep warmup outside reports."""
    expected = {c["case_id"] for c in remote_cases()}
    rows = [r for report in reports for r in report["cases"] if "charged_or_reserved_tokens" in r]
    for report in reports:
        if report["version"] != VERSION or report.get("suite_sha256") != _hash(fixtures()) or report.get("selection_suite_sha256") != _hash(selection_fixtures()) or {c["case_id"] for c in report["remote_cases"]} != expected:
            raise ValueError("incompatible_formal_report")
    executed = {r["case_id"] for r in rows}
    covered = {r["case_id"] for r in rows if r["branch_status"] == "covered" and r["status"] == "protocol_valid"}
    host_pass = bool(reports) and all(r["host_check_status"] == "pass" and
                                    {c["case_id"] for c in r["host_checks"]} == expected and
                                    all(c["status"] == "pass" for c in r["host_checks"]) for r in reports)
    selection_pass = bool(reports) and all(r.get("selection_check_status") == "pass" and
        {c["case_id"] for c in r.get("selection_checks", [])} == expected and
        all(c["status"] == "pass" for c in r["selection_checks"]) for r in reports)
    return dict(status="complete" if covered == expected and host_pass and selection_pass and all(r["status"] == "protocol_valid" for r in rows) else "incomplete",
                selection_check_status="pass" if selection_pass else "fail",
                remote_execution_status="complete" if executed == expected else "incomplete",
                remote_validation_status="pass" if rows and all(r["status"] == "protocol_valid" for r in rows) else "fail",
                host_check_status="pass" if host_pass else "fail",
                host_check_count=len({c["case_id"] for r in reports for c in r["host_checks"]}),
                host_check_executions=sum(len(r["host_checks"]) for r in reports),
                remote_attempts=len(rows), unrun_case_ids=sorted(expected - executed), uncovered_case_ids=sorted(expected - covered),
                unexercised_target_branch_ids=sorted(expected - {r["case_id"] for r in rows if r.get("target_branch_status") == "exercised"}),
                charged_or_reserved_tokens=sum(r["charged_or_reserved_tokens"] for r in rows),
                provider_usage_unknown_attempts=sum(r["provider_usage"] is None for r in rows),
                latency_ms=sum(r["latency_ms"] or 0 for r in rows),
                semantic_quality="not_evaluated", backend_compilation="unverified", warmup_included=False)
