"""Constrain the engineering corpus check to one search, open and assessment."""

from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import re

from jsonschema import Draft202012Validator

from .contracts import HarnessError, ModelReply, TransportError, encode, fingerprint, integer, source_hash
from .model_tools import CORPUS_MODEL_TOOLS
from .schema import ResponseSchemaError, parse_model_response


CORPUS_ACTION_POLICY_VERSION = "m4-corpus-actions-v3"
CORPUS_SOURCE_NEED_ID = "need-1"
CORPUS_REASON_LIMIT = 120


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _object(properties):
    return {"type": "object", "properties": properties, "required": list(properties),
            "additionalProperties": False}


def _constant(value):
    return {"const": value}


def _current_excerpts(body):
    refs = body.get("current_payload_source_refs", [])
    return [row for row in body.get("excerpts", []) if isinstance(row, dict)
            and _text(row.get("ref")) and row["ref"] in refs
            and _text(row.get("case_id")) and _text(row.get("text"))]


def _first_open_ref(observation, query_id):
    for hit in observation.get("hits", []):
        ref = hit.get("open_ref") if isinstance(hit, dict) else None
        if (
            isinstance(ref, dict) and set(ref) == {"case_id", "source_hash", "passage_ids"}
            and _text(ref["case_id"]) and ref["case_id"] != query_id
            and ref["case_id"] == hit.get("case_id", ref["case_id"])
            and source_hash(ref["source_hash"])
            and isinstance(ref["passage_ids"], list) and ref["passage_ids"]
            and all(_text(value) for value in ref["passage_ids"])
        ):
            return ref
    return None


def _branch(schema, action, *, complete=False):
    matches = []
    for branch in schema["anyOf"]:
        properties = branch["properties"]
        if properties["action"].get("const") != action:
            continue
        if action != "stop" or ("prediction" in properties["args"]["properties"]) == complete:
            matches.append(branch)
    if len(matches) != 1:
        raise HarnessError(f"M4 corpus action is unavailable or ambiguous: {action}")
    return matches[0]


def _plan(body):
    query_id = body["query_id"]
    observation = body.get("observation", {})
    current = _current_excerpts(body)
    query_rows = [row for row in current if row["case_id"] == query_id]
    candidate_rows = [row for row in current if row["case_id"] != query_id]
    if integer(body.get("active_assessment_count"), 1):
        return "stop", {"reason": "complete", "prediction": []}
    if len(query_rows) == len(candidate_rows) == 1 and observation.get("action") != "assess_links":
        return "assess_links", {
            "source_need_id": CORPUS_SOURCE_NEED_ID,
            "candidate_id": candidate_rows[0]["case_id"],
            "a_context_refs": [query_rows[0]["ref"]],
            "b_passage_refs": [candidate_rows[0]["ref"]],
            "speaker": {"role": "unknown"},
        }
    open_ref = _first_open_ref(observation, query_id)
    if open_ref and not candidate_rows:
        return "open_source", open_ref
    reload_refs = body.get("reloadable_source_refs", [])
    if candidate_rows and not query_rows and observation.get("case_id") == candidate_rows[0]["case_id"]:
        # This is the first delivery after the single B open. All earlier refs are A.
        b_ref = candidate_rows[0]["ref"]
        a_ref = next((ref for ref in reload_refs if _text(ref) and ref != b_ref), None)
        if a_ref is not None:
            return "reload_source", {"refs": [a_ref, b_ref]}
    if (
        body.get("query_delivery") == "navigation" and body.get("candidate_count") == 0
        and observation.get("kind") == "query_map" and query_rows and not reload_refs
    ):
        return "search_corpus", {"channel": "passage_bm25", "limit": 1}
    return "stop", {"reason": "no_progress"}


def _model_payload(payload):
    body = parse_model_response(payload.decode("utf-8"))
    if not isinstance(body, dict) or "available_tool" in body:
        raise HarnessError("Expected an unaugmented M4 corpus payload")
    action, binding = _plan(body)
    tool = CORPUS_MODEL_TOOLS[action]
    return action, binding, tool["name"], encode({**body, "available_tool": tool})


def _model_schema(schema, internal, action, model_action):
    branch = deepcopy(internal)
    properties = branch["properties"]
    properties["action"] = _constant(model_action)
    if action == "search_corpus":
        properties["args"] = _object({"issue": {"type": "string", "minLength": 1, "maxLength": 160}})
    elif action == "assess_links":
        fields = properties["args"]["properties"]["assessments"]["items"]["properties"]
        properties["args"] = _object({
            "case_relation": fields["case_relation"],
            "passage_location": fields["passage_location"],
            "reason": {**fields["reason"], "maxLength": CORPUS_REASON_LIMIT},
        })
    else:
        properties["args"] = _object({})
    return {**schema, "anyOf": [branch]}


def _internal_action(action, binding, model_args):
    if action == "search_corpus":
        cue = model_args["issue"].strip()
        if not cue or re.search(r"\b\d+\.txt\b", cue, re.IGNORECASE) is not None:
            raise ResponseSchemaError("invalid_issue_search_phrase")
        args = {**binding, "text": cue}
    elif action == "assess_links":
        reason = model_args["reason"].strip()
        if not reason:
            raise ResponseSchemaError("blank_corpus_assessment_reason")
        args = {"assessments": [{**binding, **model_args, "reason": reason}]}
    else:
        args = binding
    return {"action": action, "args": args}


class CorpusActionTransport:
    """Use a single state-compatible schema branch for each paid corpus check turn."""

    def __init__(self, transport):
        self._transport = transport
        self.tokenizer_fingerprint = transport.tokenizer_fingerprint
        policy_hash = sha256(Path(__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        self.prompt_fingerprint = fingerprint([
            transport.prompt_fingerprint, CORPUS_ACTION_POLICY_VERSION, policy_hash, CORPUS_MODEL_TOOLS,
        ])
        self.policy_receipts = []

    @property
    def receipts(self):
        return self._transport.receipts

    @property
    def last_call_id(self):
        return self._transport.last_call_id

    def count_tokens(self, payload):
        _, _, _, augmented = _model_payload(payload)
        return self._transport.count_tokens(augmented)

    def send_structured(self, payload, request_id, schema):
        receipt = {"request_id": request_id, "allowed_action": None,
                   "model_action": None, "model_payload_sha256": None, "narrowed_schema_fingerprint": None}
        self.policy_receipts.append(receipt)
        try:
            allowed, binding, model_action, augmented = _model_payload(payload)
            internal = _branch(schema, allowed, complete=binding.get("reason") == "complete")
            narrowed = _model_schema(schema, internal, allowed, model_action)
            receipt.update(allowed_action=allowed, model_action=model_action,
                           model_payload_sha256=sha256(augmented).hexdigest(),
                           narrowed_schema_fingerprint=fingerprint(narrowed))
        except (AttributeError, TypeError, ValueError, KeyError, HarnessError) as exc:
            receipt.update(status="error", error_code="corpus_action_policy_input")
            raise TransportError("corpus_action_policy_input") from exc
        try:
            reply = self._transport.send_structured(augmented, request_id, narrowed)
        except TransportError as exc:
            receipt.update(status="unknown" if exc.unknown else "error", error_code="underlying_transport")
            raise
        if not isinstance(reply, ModelReply):
            receipt.update(status="rejected", error_code="corpus_action_policy_result")
            raise TransportError("corpus_action_policy_result")
        try:
            model_reply = parse_model_response(reply.action)
            if not Draft202012Validator(narrowed).is_valid(model_reply):
                raise ResponseSchemaError("invalid_model_tool_reply")
            action = _internal_action(allowed, binding, model_reply["args"])
            if not Draft202012Validator(internal).is_valid(action):
                raise ResponseSchemaError("invalid_translated_action")
        except ResponseSchemaError as exc:
            receipt.update(status="rejected", error_code="corpus_action_policy_rejected")
            raise TransportError("corpus_action_policy_rejected", input_tokens=reply.input_tokens,
                                 output_tokens=reply.output_tokens, latency_ms=reply.latency_ms) from exc
        receipt.update(status="accepted", error_code=None)
        return replace(reply, action=action)
