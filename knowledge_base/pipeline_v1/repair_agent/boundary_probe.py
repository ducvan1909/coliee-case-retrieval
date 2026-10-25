"""FORMAL-only restrictions; production runtime must not import this module.

Length probes narrow a copied schema, never substitute a whole-string const.
Unicode probes reuse Compiler.emit/repeat with a restricted scalar alphabet.
"""
from __future__ import annotations

import copy
import json

from .grammar import Compiler, literal
from .selection import selection_schema
from .wire import force_branches

UNICODE_MARKER = "FORMAL probe Unicode scalar alphabet"
UNICODE_SCALARS = ("é", "😀")


def boundary_case(fixture):
    cid = fixture["case_id"]
    return "_length_" in cid or cid in {"reason_unicode_120", "reason_unicode_121"}


def unicode_boundary(fixture):
    return fixture["case_id"] in {"reason_unicode_120", "reason_unicode_121"}


class BoundaryCompiler(Compiler):
    """Change only the target scalar domain; share production length emission."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.unicode_target = False
        self.rules["probe-unicode-char"] = " | ".join([
            json.dumps("é", ensure_ascii=False), json.dumps("😀", ensure_ascii=False),
            literal("\\u00") + ' [eE] "9"',
            literal("\\u") + ' [dD] "83" [dD] ' + literal("\\u") + ' [dD] [eE] "00"',
        ])

    def emit(self, node):
        previous = self.unicode_target
        self.unicode_target = (node.get("type") == "string" and
                               node.get("description") == UNICODE_MARKER)
        try:
            return super().emit(node)
        finally:
            self.unicode_target = previous

    def repeat(self, item, lo, hi):
        if self.unicode_target and item == "json-char":
            item = "probe-unicode-char"
        return super().repeat(item, lo, hi)

    def branches(self, node):
        branches = super().branches(node)
        # Production's kind=other branch reinstates minLength=1. Retain an
        # exact probe minimum on that copied label without changing Compiler.
        label = node.get("properties", {}).get("other_kind", {})
        if label.get("minLength") == label.get("maxLength") and "minLength" in label:
            # Otherwise the non-other/null branch can evade the target entirely.
            branches = [b for b in branches if b["properties"].get("kind", {}).get("const") == "other"]
            for branch in branches:
                branch["properties"]["other_kind"].update(
                    minLength=label["minLength"], maxLength=label["maxLength"])
        return branches


def _target_nodes(node, path, *, effective=False):
    """Follow the fixture's output path through schema alternatives only."""
    if not path:
        return [node]
    if effective and "allOf" in node:
        return [target for variant in Compiler().branches(node)
                for target in _target_nodes(variant, path, effective=True)]
    if "oneOf" in node or "anyOf" in node:
        return [target for variant in node.get("oneOf", node.get("anyOf", []))
                for target in _target_nodes(variant, path, effective=effective)]
    key, *rest = path
    if isinstance(key, int):
        return _target_nodes(node["items"], rest, effective=effective) if "items" in node else []
    child = node.get("properties", {}).get(key)
    return _target_nodes(child, rest, effective=effective) if child is not None else []


def probe_decoding(fixture, *, forced_verdict=None, forced_action=None):
    """Return EBNF plus auditable production/probe boundary limits."""
    task = fixture["task"]
    schema = copy.deepcopy(selection_schema(task, fixture["arm"], fixture["turn"], ["a"]))
    force_branches(schema, forced_verdict=forced_verdict, forced_action=forced_action)
    details = None
    if boundary_case(fixture):
        targets = _target_nodes(schema, fixture["target_path"])
        effective_targets = [n for n in _target_nodes(schema, fixture["target_path"], effective=True)
                             if "maxLength" in n and "const" not in n]
        if not targets or not effective_targets or any("minLength" not in n for n in effective_targets):
            raise ValueError("missing_probe_boundary_target")
        limits = [{"minLength": n["minLength"], "maxLength": n["maxLength"]} for n in effective_targets]
        if any(limit != limits[0] for limit in limits):
            raise ValueError("ambiguous_probe_boundary_limits")
        value = fixture["output"]
        for key in fixture["target_path"]:
            value = value[key]
        length = len(value)
        valid = fixture["expected_valid"]
        details = dict(production_limits=limits[0], requested_decoded_length=length,
                       probe_restriction=None, observed_decoded_length=None,
                       observed_unicode_condition=None,
                       evidence_kind="boundary_exercising_via_test_narrowing" if valid
                       else "original_limits_invalid_challenge",
                       original_max_enforcement="unverified")
        if valid:
            if not limits[0]["minLength"] <= length <= limits[0]["maxLength"]:
                raise ValueError("probe_boundary_outside_production_limits")
            details["probe_restriction"] = dict(minLength=length, maxLength=length,
                unicode_scalars=list(UNICODE_SCALARS) if unicode_boundary(fixture) else None,
                required_kind="other" if fixture["target_path"][-1] == "other_kind" else None)
            for target in targets:
                if "const" in target or "enum" in target:
                    raise ValueError("probe_boundary_must_use_length_compiler")
                target.update(minLength=length, maxLength=length)
                if unicode_boundary(fixture):
                    target["description"] = UNICODE_MARKER
    cls = BoundaryCompiler if details and fixture["expected_valid"] else Compiler
    compiler = cls(allow_duplicate=len(task["original_proposals"]) > 1)
    return {"ebnf": compiler.compile(schema)}, details


def boundary_matches(value, fixture):
    expected = fixture["output"]
    for key in fixture["target_path"]:
        expected = expected[key]
    return (isinstance(value, str) and len(value) == len(expected) and
            (not unicode_boundary(fixture) or all(c in UNICODE_SCALARS for c in value)))


def observe_boundary(output, fixture, details):
    if details is None:
        return
    try:
        value = output
        for key in fixture["target_path"]:
            value = value[key]
    except (KeyError, IndexError, TypeError):
        return
    if isinstance(value, str):
        details["observed_decoded_length"] = len(value)
        if unicode_boundary(fixture):
            details["observed_unicode_condition"] = bool(value) and all(c in UNICODE_SCALARS for c in value)
