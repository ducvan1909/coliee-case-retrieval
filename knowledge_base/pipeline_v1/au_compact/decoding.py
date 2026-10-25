"""Offline hard grammar for SGLang ChatCompletions' top-level ``ebnf`` field.

The caller must not also send response_format. Host validation remains required.
Evidence uses lexicographically sorted IDs; context flags use schema enum order.
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path


_SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "contracts" /
                      "compact_au_model_output.v1.json").read_text(encoding="utf-8"))
_TOP = _SCHEMA["properties"]
_AU = _SCHEMA["$defs"]["au"]["properties"]


def _literal(text: str) -> str:
    # Two encodings: JSON output bytes, then a safely quoted EBNF terminal.
    return json.dumps(text, ensure_ascii=True)


def _json_literal(value: str) -> str:
    return _literal(json.dumps(value, ensure_ascii=True))


def _id(value: str, name: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise ValueError(f"{name} must be a nonempty string of at most 128 characters")
    # Never trim or rewrite an identity. Reject unpaired surrogates instead.
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{name} must contain Unicode scalar values") from exc
    return value


def _ids(values: Iterable[str], name: str) -> set[str]:
    if isinstance(values, (str, bytes)):
        raise ValueError(f"{name} must be an iterable of IDs, not text")
    try:
        result = {_id(value, name) for value in values}
    except TypeError as exc:
        raise ValueError(f"{name} must be an iterable of IDs") from exc
    if not result:
        raise ValueError(f"{name} must be nonempty")
    return result


def build_decoding(request_id, target_id, allowed_atom_ids, target_atom_ids,
                   *, string_mode="bounded") -> dict:
    """Return only ``{'ebnf': grammar}``, with exact locked request/target IDs.

    ID collections are deduplicated without changing their values. Evidence
    suffix states (index, remaining slots, target seen) grow linearly in the
    catalog size, rather than enumerating all one-to-three-ID combinations.
    """
    if string_mode not in {"bounded", "host_validated"}:
        raise ValueError("unknown string decoder")
    request_id = _id(request_id, "request_id")
    target_id = _id(target_id, "target_id")
    allowed = _ids(allowed_atom_ids, "allowed_atom_ids")
    targets = _ids(target_atom_ids, "target_atom_ids")
    if not targets <= allowed:
        raise ValueError("target_atom_ids must be a subset of allowed_atom_ids")
    atoms = sorted(allowed)
    rules = []

    def rule(name, alternatives):
        rules.append(name + " ::= " + " | ".join(alternatives))

    def enum(name, values):
        rule(name, [_json_literal(value) for value in values if value is not None])

    prefix = '{"request_id":' + json.dumps(request_id, ensure_ascii=True)
    prefix += ',"target_id":' + json.dumps(target_id, ensure_ascii=True) + ',"decision":'
    rule("root", [_literal(prefix) + ' decision ' + _literal("}")])
    rule("decision", [
        _literal('"positive","coverage_status":') + ' coverage ' +
        _literal(',"aus":[') + ' au ("," au){0,2} ' +
        _literal('],"hard_negative_reason":null,"unresolved_reason":null'),
        _literal('"hard_negative","coverage_status":"complete","aus":[],"hard_negative_reason":') +
        ' hard-reason ' + _literal(',"unresolved_reason":null'),
        _literal('"unresolved","coverage_status":') + ' coverage ' +
        _literal(',"aus":[],"hard_negative_reason":null,"unresolved_reason":') + ' unresolved-reason',
    ])
    enum("coverage", _TOP["coverage_status"]["enum"])
    enum("hard-reason", _TOP["hard_negative_reason"]["enum"])
    enum("unresolved-reason", _TOP["unresolved_reason"]["enum"])
    enum("kind", [kind for kind in _AU["kind"]["enum"] if kind != "other"])
    enum("speaker", _AU["speaker"]["enum"])
    enum("role", _AU["attribution_role"]["enum"])
    rule("au", [_literal('{"kind":') + ' kind-label ' + _literal(',"claim":') +
                ' claim ' + _literal(',"evidence_ref_ids":[') + ' ev-0-3-0 ' +
                _literal('],"speaker":') + ' speaker ' + _literal(',"attribution_role":') +
                ' role ' + _literal(',"needs_context":[') + ' ctx-0-0 ' + _literal("]}")])
    rule("kind-label", ['kind ' + _literal(',"other_kind":null'),
                        _literal('"other","other_kind":') + ' label'])
    # The ablation removes expensive bounded repetition only; the unchanged
    # host schema still rejects claims/labels longer than 300/160 characters.
    claim_body = "json-char{1,300}" if string_mode == "bounded" else "json-char+"
    label_body = "json-char{1,160}" if string_mode == "bounded" else "json-char+"
    rule("claim", ['"\\\"" ' + claim_body + ' "\\\""'])
    rule("label", ['"\\\"" ' + label_body + ' "\\\""'])
    # A Unicode surrogate pair is one decoded character. Lone surrogates are
    # excluded, as are raw controls and invalid JSON escape sequences.
    # XGrammar 0.2.1 narrows non-ASCII endpoints in negated classes to
    # uint8_t: excluding D800-DFFF there accidentally excludes all ASCII.
    # Positive scalar ranges preserve JSON's exclusions without that path.
    rule("json-char", [r'[\x20-\x21\x23-\x5b\x5d-\uD7FF\uE000-\U0010FFFF]',
                       r'"\\" (["\\/bfnrt] | "u" scalar-hex)',
                       r'"\\u" [dD] [89aAbB] hex hex "\\u" [dD] [c-fC-F] hex hex'])
    rule("scalar-hex", ['[0-9a-cA-Ce-fE-F] hex hex hex', '[dD] [0-7] hex hex'])
    rule("hex", ['[0-9a-fA-F]'])

    flags = _AU["needs_context"]["items"]["enum"]
    for index in range(len(flags), -1, -1):
        for selected in (0, 1):
            alternatives = ['""'] if index == len(flags) else [
                f"ctx-{index + 1}-{selected}",
                (_literal(",") + " " if selected else "") +
                _json_literal(flags[index]) + f" ctx-{index + 1}-1",
            ]
            rule(f"ctx-{index}-{selected}", alternatives)

    suffix_target = [False] * (len(atoms) + 1)
    for index in range(len(atoms) - 1, -1, -1):
        suffix_target[index] = atoms[index] in targets or suffix_target[index + 1]

    def productive(index, remaining, seen):
        return (seen and remaining < 3) or (remaining > 0 and suffix_target[index])

    for index in range(len(atoms), -1, -1):
        for remaining in range(4):
            for seen in (0, 1):
                if not productive(index, remaining, seen):
                    continue
                alternatives = []
                if index == len(atoms) or remaining == 0:
                    alternatives.append('""')
                else:
                    if productive(index + 1, remaining, seen):
                        alternatives.append(f"ev-{index + 1}-{remaining}-{seen}")
                    next_seen = int(bool(seen or atoms[index] in targets))
                    if productive(index + 1, remaining - 1, next_seen):
                        alternatives.append((_literal(",") + " " if remaining < 3 else "") +
                                            _json_literal(atoms[index]) +
                                            f" ev-{index + 1}-{remaining - 1}-{next_seen}")
                rule(f"ev-{index}-{remaining}-{seen}", alternatives)
    return {"ebnf": "\n".join(rules) + "\n"}
