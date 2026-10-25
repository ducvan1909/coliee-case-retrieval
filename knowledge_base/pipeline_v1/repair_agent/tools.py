"""Five local tools: fixed source scope, exact witnesses, pending revisions."""
from __future__ import annotations

import copy

from jsonschema import Draft202012Validator

from ..au_candidate_store.core import _hash
from ..au_candidate_store.reviews import _quote
from .core import CONTRACTS, POLICY, atomic, load, validate


def model_task(task):
    """Never leak control verdicts, gold, or unread expansion text."""
    errors = {}
    for entry in task["semantic_errors"]:
        checks = sorted(k for k, v in entry.get("checks", {}).items() if v == "fail")
        key = (entry["proposal_sha256"], tuple(checks))
        errors.setdefault(key, {"reason": entry["reason"][:200],
            "proposal_id": "proposal-" + entry["proposal_sha256"],
            "hypothesized_checks": checks})
    return {k: copy.deepcopy(task[k]) for k in (
        "task_id", "case_id", "source_hash", "target_id", "raw_targets",
        "original_proposals", "supplied_atom_catalog")} | {
        "obligations": [{k: copy.deepcopy(o[k]) for k in ("obligation_id", "obligation_type", "requested_direction_or_ref", "reason") if k in o} for o in task["obligations"]],
        "prior_reported_errors": [dict(e, status="unverified_hypothesis") for e in errors.values()],
        "error_origin": task["error_origin"]}


class RepairSession:
    def __init__(self, task, arm, checkpoint=None, state=None, *, legacy_offline=False):
        validate("task", task)
        if arm not in {"R0", "R1", "R2"}:
            raise ValueError("invalid_arm")
        self.task = copy.deepcopy(task)
        self.arm = arm
        self.legacy_offline = legacy_offline
        self.checkpoint = checkpoint
        self.state = copy.deepcopy(state) if state else {
            "read_atom_ids": [a["atom_id"] for a in task["supplied_atom_catalog"]],
            "expanded_atom_ids": [], "expansion_count": 0, "tool_count": 0,
            "events": [], "revision": None, "obligations": copy.deepcopy(task["obligations"])}
        self.catalog = {a["atom_id"]: a for a in task["supplied_atom_catalog"] + task["expansion_atom_catalog"]}
        if len(self.catalog) != len(task["supplied_atom_catalog"]) + len(task["expansion_atom_catalog"]):
            raise ValueError("duplicate_catalog_id")

    def save(self):
        if self.checkpoint:
            atomic(self.checkpoint, self.state)

    def _witness(self, witness, primary=False):
        atoms = {aid: self.catalog[aid] for aid in self.state["read_atom_ids"]}
        return _quote(witness, atoms, self.task["raw_targets"], primary=primary)

    def _submit(self, args, *, commit=True):
        if args["task_id"] != self.task["task_id"]:
            raise ValueError("foreign_task")
        original = {p["proposal_id"]: p for p in self.task["original_proposals"]}
        ids = [d["proposal_id"] for d in args["decisions"]]
        if len(ids) != len(set(ids)) or set(ids) != set(original):
            raise ValueError("one_decision_per_original_required")
        verified = []
        for decision in args["decisions"]:
            action = decision["action"]
            if action != "replace" and decision["replacements"]:
                raise ValueError("unexpected_replacements")
            proposed = decision["replacements"]
            if action == "keep":
                if not decision["primary_proposition"]:
                    raise ValueError("keep_primary_required")
                proposed = [{"au": original[decision["proposal_id"]]["proposal"],
                             "primary_proposition": decision["primary_proposition"]}]
            for replacement in proposed:
                au = replacement["au"]
                # Compact field constraints are checked even for keep.
                au_schema = load(CONTRACTS / "compact_au_model_output.v1.json")["$defs"]["au"]
                Draft202012Validator(au_schema).validate(au)
                if not set(au["evidence_ref_ids"]) <= set(self.state["read_atom_ids"]):
                    raise ValueError("evidence_id_not_read")
                primary = replacement["primary_proposition"]
                if primary["atom_id"] not in au["evidence_ref_ids"]:
                    raise ValueError("primary_not_selected_evidence")
                owner = self._witness(primary, primary=True)
                evidence = [copy.deepcopy(self.catalog[aid]) for aid in au["evidence_ref_ids"]]
                verified.append({"original_proposal_id": decision["proposal_id"],
                    "au": copy.deepcopy(au), "primary_proposition": owner,
                    "evidence_spans": evidence, "semantic_status": "semantic_review_pending",
                    "accepted_semantic": False, "entailment_validated": False})
        revision = copy.deepcopy(args) | {"semantic_status": "semantic_review_pending",
            "original_proposals": copy.deepcopy(self.task["original_proposals"]),
            "verified_replacements": verified, "read_atom_ids": list(self.state["read_atom_ids"])}
        validate("revision", revision)
        if commit:
            self.state["revision"] = revision
        return copy.deepcopy(revision)

    def _submit_assessments(self, args):
        from .wire import normalize
        envelope = {"tool_calls": [{"name": "submit_revision", "arguments": args}]}
        normalized = normalize(envelope, self.task, self.arm, 1, self.state["read_atom_ids"])["tool_calls"][0]["arguments"]
        assessments = normalized["decisions"]
        decisions, verified, preservation = [], [], []
        for assessment in assessments:
            d = {"proposal_id": assessment["proposal_id"], "reason": assessment["reason"],
                 "replacements": [], "primary_proposition": None}
            verdict = assessment["verdict"]
            witnesses = []
            if verdict == "supported":
                d.update(action="keep", primary_proposition=assessment["primary_proposition"])
                witnesses = [self._witness(assessment["primary_proposition"], primary=True)]
            elif verdict == "uncertain":
                d["action"] = "unresolved"
                preservation.append({"proposal_id": d["proposal_id"], "decision": "preserve_baseline",
                    "reason": d["reason"], "needed_context": assessment.get("needed_context", []),
                    "accepted_semantic": False})
            else:
                witnesses = [self._witness(w) for w in assessment["witnesses"]]
                d.update(assessment["correction"])
            decisions.append(d)
            verified.append({"proposal_id": d["proposal_id"], "verdict": verdict,
                "evidence_spans": witnesses, "accepted_semantic": False,
                "entailment_validated": False, "defect_semantics_validated": False})
        # Reuse full AU/source/ownership validation; publication remains pending.
        revision = self._submit({"task_id": normalized["task_id"], "decisions": decisions}, commit=False)
        revision.update(schema_version="repair-revision-v2", assessments=copy.deepcopy(assessments),
                        verified_assessments=verified, preservation_decisions=preservation)
        validate("revision", revision)
        self.state["revision"] = revision
        return copy.deepcopy(revision)

    def call_tool(self, name, arguments):
        """Errors are local return values; failed calls also consume tool quota."""
        event = {"name": name, "arguments": copy.deepcopy(arguments), "sequence": self.state["tool_count"] + 1}
        try:
            if self.arm == "R0" or self.state["revision"] is not None:
                raise ValueError("task_closed")
            if self.state["tool_count"] >= POLICY["tool_calls"]:
                raise ValueError("tool_budget_exhausted")
            self.state["tool_count"] += 1
            definitions = load(CONTRACTS / ("repair_tools.v1.json" if self.legacy_offline else "repair_tools.v2.json"))["$defs"]["arguments"]
            if name not in definitions:
                raise ValueError("unknown_tool")
            Draft202012Validator(definitions[name]).validate(arguments)
            if self.arm == "R1" and name != "submit_revision":
                raise ValueError("R1_submit_only")
            if name == "get_repair_task":
                result = {"task_id": self.task["task_id"], "status": "open", "tool_calls_remaining": POLICY["tool_calls"] - self.state["tool_count"], "expansions_remaining": POLICY["expansions"] - self.state["expansion_count"]}
            elif name == "get_related_aus":
                result = {"case_id": self.task["case_id"], "source_hash": self.task["source_hash"],
                    "target_id": self.task["target_id"], "collection": copy.deepcopy(self.task["original_proposals"]),
                    "semantic_status": "baseline_proposals_not_support_edges"}
            elif name == "open_span":
                aid = arguments["atom_id"]
                if aid not in self.state["read_atom_ids"]:
                    raise ValueError("atom_not_in_read_catalog_use_expansion")
                atom = self.catalog[aid]
                start = arguments.get("start_char", atom["start_char"])
                end = arguments.get("end_char", atom["end_char"])
                if not atom["start_char"] <= start < end <= atom["end_char"]:
                    raise ValueError("span_outside_allowed_atom")
                quote = atom["quote"][start - atom["start_char"]:end - atom["start_char"]]
                if "quote" in arguments and quote != arguments["quote"]:
                    raise ValueError("span_quote_mismatch")
                result = {k: atom[k] for k in ("case_id", "source_hash", "atom_id")} | {
                    "start_char": start, "end_char": end, "quote": quote}
                for obligation in self.state["obligations"]:
                    obligation["searched_spans"].append(copy.deepcopy(result))
            elif name == "expand_context":
                if self.state["expansion_count"] >= POLICY["expansions"]:
                    raise ValueError("expansion_budget_exhausted")
                self.state["expansion_count"] += 1
                direction = arguments["direction"]
                options = [a for a in self.task["expansion_atom_catalog"] if a["direction"] == direction]
                options.sort(key=lambda a: a["start_char"], reverse=direction == "before")
                selected, chars = [], 0
                input_limited = False
                for atom in options:
                    if chars + len(atom["quote"]) > POLICY["expansion_chars"]:
                        break
                    if hasattr(self, "context_admitter") and not self.context_admitter(selected + [atom]):
                        input_limited = True
                        break
                    chars += len(atom["quote"])
                    selected.append(copy.deepcopy(atom))
                for atom in selected:
                    self.state["read_atom_ids"].append(atom["atom_id"])
                    self.state["expanded_atom_ids"].append(atom["atom_id"])
                    for obligation in self.state["obligations"]:
                        obligation["searched_spans"].append(copy.deepcopy(atom))
                result = {"atoms": selected, "rendered_chars": chars, "stop_reason": "context_input_cap" if input_limited else "bounded_expansion" if selected else "no_allowed_context"}
            else:
                result = self._submit(arguments) if self.legacy_offline else self._submit_assessments(arguments)
            event.update(ok=True, result=result)
        except Exception as exc:
            # Never render exception bodies which can contain provider credentials.
            message = str(exc) if isinstance(exc, ValueError) and not hasattr(exc, "schema") else type(exc).__name__
            event.update(ok=False, error={"origin": "host_validator", "code": message})
        self.state["events"].append(event)
        self.save()
        return copy.deepcopy(event)

    def confirm_obligation(self, confirmation):
        """Trusted external review only; NOT a model tool or automatic transition."""
        required = {"obligation_id", "revision_sha256", "reviewer_id", "reviewed", "witnesses", "reason"}
        if set(confirmation) != required or confirmation["reviewed"] is not True or not confirmation["reviewer_id"] or not confirmation["reason"]:
            raise ValueError("explicit_review_confirmation_required")
        revision = self.state["revision"]
        if revision is None or confirmation["revision_sha256"] != _hash(revision):
            raise ValueError("stale_obligation_review")
        if not confirmation["witnesses"]:
            raise ValueError("obligation_review_witness_required")
        for witness in confirmation["witnesses"]:
            self._witness(witness)
        matches = [o for o in self.state["obligations"] if o["obligation_id"] == confirmation["obligation_id"]]
        if len(matches) != 1:
            raise ValueError("unknown_obligation")
        matches[0].update(status="satisfied", review_confirmation=copy.deepcopy(confirmation), stop_reason="explicit_review_confirmation")
        validate("obligation", matches[0])
        self.save()
