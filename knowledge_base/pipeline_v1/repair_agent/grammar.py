"""Strict compiler for the repair wire subset; canonical field/list order.

Finite enum uniqueItems (including selection witnesses) is grammar-enforced.
The legacy full-v2 compiler still leaves witness object uniqueness to host checks.
Bound decision arrays enforce exact once and distinct supported duplicate anchors.
This module proves no backend capability or AU semantics.
"""
from __future__ import annotations

import copy
import json

from jsonschema import Draft202012Validator
from ..au_compact.decoding import build_decoding

DECISION_RELATION_LIMIT = 6


def literal(value):
    return json.dumps(value, ensure_ascii=True)


def terminal(value):
    return literal(json.dumps(value, ensure_ascii=True, separators=(",", ":")))


class Compiler:
    def __init__(self, *, allow_duplicate=True):
        self.allow_duplicate = allow_duplicate
        base = build_decoding("probe", "probe", ["probe"], ["probe"],
                              string_mode="host_validated")["ebnf"]
        self.rules = {line.split(" ::= ")[0]: line.split(" ::= ")[1]
                      for line in base.splitlines()
                      if line.split(" ::= ")[0] in {"json-char", "scalar-hex", "hex"}}
        self.cache = {}
        self.repeats = {}

    def rule(self, expression):
        name = "s" + str(len(self.rules))
        self.rules[name] = expression
        return name

    def repeat(self, item, lo, hi):
        """Shared binary blocks: O(log(bound)) rules instead of bound copies."""
        key = (item, lo, hi)
        if key in self.repeats:
            return self.repeats[key]
        if hi is None:
            expression = (self.repeat(item, lo, lo) + " " if lo else "") + item + "*"
        elif lo == hi:
            if lo == 0:
                expression = '""'
            elif lo == 1:
                expression = item
            else:
                half = self.repeat(item, lo // 2, lo // 2)
                expression = half + " " + half + (" " + item if lo % 2 else "")
        elif lo:
            expression = self.repeat(item, lo, lo) + " " + self.repeat(item, 0, hi - lo)
        elif hi == 1:
            expression = item + "?"
        else:
            # 0..(p-1), or p followed by 0..(hi-p); disjoint lengths.
            p = 1 << (hi.bit_length() - 1)
            expression = (self.repeat(item, 0, p - 1) + " | " +
                          self.repeat(item, p, p) + " " + self.repeat(item, 0, hi - p))
        result = self.rule(expression)
        self.repeats[key] = result
        return result

    def check(self, node):
        allowed = {"$schema", "$id", "title", "description", "type", "const", "enum",
                   "oneOf", "anyOf", "properties", "required", "additionalProperties",
                   "items", "minItems", "maxItems", "uniqueItems", "minLength",
                   "maxLength", "minimum", "allOf"}
        unknown = set(node) - allowed
        if unknown:
            raise ValueError("unsupported grammar keywords: " + ", ".join(sorted(unknown)))
        for key in ("oneOf", "anyOf"):
            for child in node.get(key, []): self.check(child)
        for child in node.get("properties", {}).values(): self.check(child)
        if "items" in node: self.check(node["items"])
        if "allOf" in node:
            for branch in self.branches(node): self.check(branch)
        kind = node.get("type")
        types = kind if isinstance(kind, list) else [kind]
        for key, compatible in (("minLength", "string"), ("maxLength", "string"),
                                ("minimum", "integer"), ("uniqueItems", "array"),
                                ("minItems", "array"), ("maxItems", "array")):
            if key in node and compatible not in types:
                raise ValueError("constraint/type mismatch: " + key)
        if kind == "object" and node.get("additionalProperties") is not False:
            raise ValueError("object grammar requires additionalProperties=false")
        if "minimum" in node and node["minimum"] not in (0, 1):
            raise ValueError("unsupported integer minimum")
        if "oneOf" in node or "anyOf" in node:
            if "oneOf" in node and "anyOf" in node:
                raise ValueError("unsupported combined alternatives")
            if set(node) - {"oneOf", "anyOf", "title", "description", "$id", "$schema"}:
                raise ValueError("unsupported constraints alongside alternatives")
        if "oneOf" in node:
            # A union implements oneOf only when branches are disjoint. The
            # wire contract uses required name/verdict/action discriminators.
            variants = node["oneOf"]
            tags = [{k: v["const"] for k, v in child.get("properties", {}).items()
                     if "const" in v and k in child.get("required", [])} for child in variants]
            common = set.intersection(*(set(tag) for tag in tags)) if tags else set()
            if not any(len({json.dumps(tag[k], sort_keys=True) for tag in tags}) == len(tags)
                       for k in common):
                raise ValueError("oneOf requires disjoint required const discriminators")
        for key in ("properties", "required", "additionalProperties"):
            if key in node and kind != "object":
                raise ValueError("constraint/type mismatch: " + key)
        if node.get("type") == "integer" and "minimum" not in node:
            raise ValueError("integer grammar requires explicit minimum 0 or 1")
        if any(t not in {None, "object", "array", "string", "integer", "null"} for t in types):
            raise ValueError("unsupported grammar type")

    def branches(self, node):
        conditions = node["allOf"]
        duplicate = {"if": {"properties": {"defect_type": {"const": "duplicate"}}},
                     "then": {"required": ["retained_proposal_id"], "properties": {
                         "correction": {"properties": {"action": {"const": "reject"}}}}},
                     "else": {"not": {"required": ["retained_proposal_id"]}}}
        other = {"if": {"properties": {"kind": {"const": "other"}}},
                 "then": {"properties": {"other_kind": {"type": "string", "minLength": 1}}},
                 "else": {"properties": {"other_kind": {"const": None}}}}
        if conditions not in ([duplicate], [other]) or node.get("type") != "object":
            raise ValueError("unsupported allOf conditional")
        field, value = ("defect_type", "duplicate") if conditions == [duplicate] else ("kind", "other")
        if field not in node.get("required", []):
            raise ValueError("conditional discriminator must be required")
        yes, no = copy.deepcopy(node), copy.deepcopy(node)
        del yes["allOf"]; del no["allOf"]
        values = no["properties"][field].get("enum")
        if not values or value not in values:
            raise ValueError("unsupported conditional discriminator")
        yes["properties"][field] = {"const": value}
        no["properties"][field]["enum"] = [v for v in values if v != value]
        if field == "defect_type":
            del no["properties"]["retained_proposal_id"]
            yes["required"].append("retained_proposal_id")
            corrections = yes["properties"]["correction"]["oneOf"]
            corrections[:] = [v for v in corrections if v["properties"]["action"]["const"] == "reject"]
            return [no] + ([yes] if self.allow_duplicate and corrections else [])
        yes["properties"]["other_kind"].update(type="string", minLength=1)
        # normalize inserts null then validates: absent other label is not valid.
        yes["required"].append("other_kind")
        no["properties"]["other_kind"] = {"const": None}
        return [no, yes]

    def emit(self, node):
        key = json.dumps(node, sort_keys=True)
        if key in self.cache: return self.cache[key]
        if "allOf" in node:
            expression = " | ".join(self.emit(branch) for branch in self.branches(node))
        elif "const" in node or "enum" in node:
            values = [node["const"]] if "const" in node else node["enum"]
            values = [v for v in values if Draft202012Validator(node).is_valid(v)]
            if not values: raise ValueError("empty grammar value domain")
            expression = " | ".join(terminal(v) for v in values)
        elif "oneOf" in node or "anyOf" in node:
            variants = node.get("oneOf", node.get("anyOf"))
            if not variants: raise ValueError("empty grammar alternatives")
            expression = " | ".join(self.emit(v) for v in variants)
        elif isinstance(node.get("type"), list):
            expression = " | ".join(self.emit({k: v for k, v in {**node, "type": t}.items()
                                              if t == "string" or k not in {"minLength", "maxLength"}})
                                    for t in node["type"])
        elif node.get("type") == "object":
            fields = list(node.get("properties", {}).items())
            required = set(node.get("required", []))
            if not required <= dict(fields).keys(): raise ValueError("unknown required field")
            # State tracks whether a previous optional/required field was emitted.
            states = {}
            for index in range(len(fields), -1, -1):
                for seen in (0, 1):
                    if index == len(fields): expression = '""'
                    else:
                        field, child = fields[index]
                        part = literal(("," if seen else "") + json.dumps(field) + ":")
                        part += " " + self.emit(child) + " " + states[index + 1, 1]
                        expression = part if field in required else states[index + 1, seen] + " | " + part
                    states[index, seen] = self.rule(expression)
            expression = literal("{") + " " + states[0, 0] + " " + literal("}")
        elif node.get("type") == "array":
            proposal_ids = self.decision_ids(node)
            if proposal_ids is not None:
                result = self.emit_decisions(node, proposal_ids)
                self.cache[key] = result
                return result
            lo, hi = node.get("minItems", 0), node.get("maxItems")
            if hi is None: raise ValueError("array requires explicit maxItems")
            if not 0 <= lo <= hi: raise ValueError("invalid array bounds")
            if hi == 0: body = '""'
            elif node.get("uniqueItems") and "enum" in node["items"]:
                values = list(dict.fromkeys(node["items"]["enum"]))
                values = [v for v in values if Draft202012Validator(node["items"]).is_valid(v)]
                hi = min(hi, len(values))
                if lo > hi: raise ValueError("empty unique array domain")
                states = {}
                for index in range(len(values), -1, -1):
                    for used in range(hi + 1):
                        alternatives = []
                        if index == len(values) or used == hi:
                            if used >= lo: alternatives.append('""')
                        else:
                            if (index + 1, used) in states: alternatives.append(states[index + 1, used])
                            if (index + 1, used + 1) in states:
                                alternatives.append((literal(",") + " " if used else "") +
                                                    terminal(values[index]) + " " + states[index + 1, used + 1])
                        if alternatives: states[index, used] = self.rule(" | ".join(alternatives))
                body = states[0, 0]
            else:
                if node.get("uniqueItems") and node["items"].get("type") != "object":
                    raise ValueError("unsupported uniqueItems domain; only objects have host guards")
                item = self.emit(node["items"])
                rest = self.rule(literal(",") + " " + item)
                body = item + " " + self.repeat(rest, max(0, lo - 1), hi - 1)
                if lo == 0: body = "(" + body + ")?"
            expression = literal("[") + " " + body + " " + literal("]")
        elif node.get("type") == "string":
            lo, hi = node.get("minLength", 0), node.get("maxLength")
            if lo < 0 or (hi is not None and lo > hi): raise ValueError("invalid string bounds")
            expression = literal('"') + " " + self.repeat("json-char", lo, hi) + " " + literal('"')
        elif node.get("type") == "integer":
            expression = ('"0" | ' if node.get("minimum", 0) == 0 else "") + '[1-9] [0-9]*'
        elif node.get("type") == "null": expression = literal("null")
        else: raise ValueError("unsupported grammar schema: " + key)
        result = self.rule(expression)
        self.cache[key] = result
        return result

    def decision_ids(self, node):
        """Recognize the bound v2/selection decision schema, without rewriting it.

        Keep items/oneOf intact so probe visitors can still narrow properties.
        Forced verdicts and absent evidence may remove some verdict branches.
        """
        variants = node.get("items", {}).get("oneOf", [])
        if not variants or not all(
                {"proposal_id", "verdict"} <= set(v.get("required", [])) and
                v.get("properties", {}).get("verdict", {}).get("const") in
                {"supported", "uncertain", "defect_found"} for v in variants):
            return None
        ids = variants[0]["properties"]["proposal_id"].get("enum")
        if (not isinstance(ids, list) or not all(isinstance(pid, str) for pid in ids)
                or len(ids) != len(set(ids)) or any(
                    v["properties"]["proposal_id"].get("enum") != ids for v in variants)
                or node.get("minItems") != len(ids) or node.get("maxItems") != len(ids)):
            raise ValueError("invalid_bound_decision_domain")
        if len(ids) > DECISION_RELATION_LIMIT:
            raise ValueError("decision_relation_limit_exceeded")
        return ids

    def emit_decisions(self, node, ids):
        """Finite states indexed by supported set and ordered proposal slot.

        Enumerate only 2**n supported sets, never verdict/anchor products.
        All non-supported verdicts remain alternatives at each remaining slot.
        An anchor in a later slot is constrained supported by the same state;
        hence self edges, uncertain anchors, duplicate chains and cycles vanish.
        Shared schema emission and suffixes bound the grammar to O(n * 2**n)
        states/alternatives, plus the existing evidence/string grammar.
        """
        variants = node["items"]["oneOf"]
        supported_available = any(v["properties"]["verdict"]["const"] == "supported"
                                  for v in variants)
        sequences, suffixes = [], {}
        for mask in range(1 << len(ids)) if supported_available else (0,):
            slots = []
            for index, pid in enumerate(ids):
                choices = []
                for variant in variants:
                    is_supported = variant["properties"]["verdict"]["const"] == "supported"
                    if is_supported != bool(mask & (1 << index)):
                        continue
                    # Expand through the virtual method: BoundaryCompiler's
                    # conditional and length restrictions must survive.
                    branches = self.branches(variant) if "allOf" in variant else [variant]
                    for branch in branches:
                        bound = copy.deepcopy(branch)
                        bound["properties"]["proposal_id"] = {"const": pid}
                        if bound["properties"].get("defect_type", {}).get("const") == "duplicate":
                            anchors = [aid for i, aid in enumerate(ids)
                                       if i != index and mask & (1 << i)]
                            if not anchors:
                                continue
                            bound["properties"]["retained_proposal_id"] = {"enum": anchors}
                        choices.append(self.emit(bound))
                if not choices:
                    break
                slots.append(tuple(choices))
            else:
                suffix = self.rule('""') if not ids else None
                for index in range(len(slots) - 1, -1, -1):
                    key = (slots[index], suffix, index == 0)
                    if key not in suffixes:
                        item = self.rule(" | ".join(slots[index]))
                        suffixes[key] = self.rule(
                            (literal(",") + " " if index else "") + item +
                            (" " + suffix if suffix else ""))
                    suffix = suffixes[key]
                sequences.append(suffix)
        if not sequences:
            raise ValueError("empty_decision_relation_domain")
        body = self.rule(" | ".join(dict.fromkeys(sequences)))
        return self.rule(literal("[") + " " + body + " " + literal("]"))

    def compile(self, schema):
        self.check(schema)
        root = self.emit(schema)
        return "root ::= " + root + "\n" + "\n".join(name + " ::= " + expr
                    for name, expr in self.rules.items()) + "\n"
