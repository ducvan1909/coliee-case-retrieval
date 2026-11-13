"""The local M4 action, admission and recovery loop."""

from dataclasses import asdict
import json
from math import isfinite
from time import perf_counter

from .contracts import (
    Budget, HarnessError, ModelReply, RunIdentity, SourceExcerpt, ToolResult,
    TransportError, encode, fingerprint, integer,
)
from .assessment import AssessmentStateError, assessment_validator_fingerprint, validate_assessment_state
from .evidence import (
    SourceDrift, assessment_refs, excerpt, normalize_result, slice_record, string_list, validate_assessments,
)
from .ledger import Ledger, RunState
from .schema import (
    ASSESSMENT_SCHEMA_VERSION, ASSESSMENT_VALIDATOR_VERSION, LEGACY_RESPONSE_SCHEMA_VERSION,
    RESPONSE_SCHEMA_VERSION, SEARCH_ACTIONS, TOOL_ACTIONS, ResponseSchemaError, parse_model_response,
    response_schema, response_schema_fingerprint, validate_model_response,
)


def _pending_summary(row):
    fields = ("source_need_id", "candidate_id", "case_relation", "passage_location", "missing_evidence",
              "reported_missing_evidence")
    return {name: row[name] for name in fields if row.get(name) is not None}


class AgentHarness:
    """Resume a single query run using injected local tools and replay transport."""

    def __init__(self, run_dir, *, identity, budget, baseline, tools, count_tokens, transport,
                 initial_observation=None, query_excerpt=None, verify_source=None, response_contract=None,
                 initial_candidate_excerpts=()):
        if not isinstance(identity, RunIdentity) or not isinstance(budget, Budget):
            raise HarnessError("Expected RunIdentity and Budget")
        baseline = string_list(baseline, "baseline candidate IDs")
        if identity.query_id in baseline:
            raise HarnessError("Baseline cannot predict the query case itself")
        self.identity = identity
        self.budget = budget
        self.baseline = baseline
        self.tools = dict(tools)
        if not self.tools.keys() <= TOOL_ACTIONS or not all(callable(tool) for tool in self.tools.values()):
            raise HarnessError("Invalid local tool mapping")
        self.structured_send = getattr(transport, "send_structured", None)
        if not callable(count_tokens) or not (callable(transport) or callable(self.structured_send)):
            raise HarnessError("Expected a token counter and transport")
        if response_contract not in (None, LEGACY_RESPONSE_SCHEMA_VERSION, RESPONSE_SCHEMA_VERSION):
            raise HarnessError("Unknown response contract")
        self.response_contract = response_contract
        if verify_source is not None and not callable(verify_source):
            raise HarnessError("Expected a source verifier")
        self.count_tokens = count_tokens
        self.transport = transport
        self.verify_source = verify_source
        self.initial_supplied = initial_observation is not None
        self.initial = initial_observation
        if initial_observation is None or isinstance(initial_observation, dict):
            self.initial = ToolResult({} if initial_observation is None else initial_observation)
        self.initial_candidate_excerpts = tuple(initial_candidate_excerpts)
        if self.initial_candidate_excerpts:
            if not isinstance(self.initial, ToolResult):
                raise HarnessError("Candidate evidence requires an initial ToolResult")
            if any(not isinstance(row, SourceExcerpt) or row.case_id != identity.query_id
                   for row in self.initial.excerpts):
                raise HarnessError("Initial query evidence must belong to the query case")
            for row in self.initial_candidate_excerpts:
                if (not isinstance(row, SourceExcerpt) or row.case_id == identity.query_id
                        or row.case_id not in self.initial.candidates):
                    raise HarnessError("Initial candidate evidence must belong to a registered candidate")
            self.initial = ToolResult(
                self.initial.observation, (*self.initial.excerpts, *self.initial_candidate_excerpts),
                self.initial.candidates, self.initial.source_requests,
            )
        self.full_query = None
        if query_excerpt is not None:
            if (not isinstance(query_excerpt, SourceExcerpt) or query_excerpt.case_id != identity.query_id
                    or query_excerpt.source_hash != identity.query_source_hash
                    or query_excerpt.text_sha256 != identity.query_source_hash or query_excerpt.span_bytes[0] != 0):
                raise HarnessError("Whole-query excerpt must match the frozen query source")
            self.full_query = query_excerpt.to_record()
        self.config = {
            "schema_version": "m4-run-v1", "identity": asdict(identity), "budget": asdict(budget),
            "baseline": baseline, "tool_actions": sorted(self.tools),
            "verify_source": verify_source is not None,
        }
        if self.initial_candidate_excerpts:
            self.config["initial_candidate_evidence"] = fingerprint([
                row.to_record() for row in self.initial_candidate_excerpts
            ])
        self.ledger = Ledger(run_dir)

    def events(self):
        return self.ledger.read()

    def inspect(self):
        return RunState(self.events()).snapshot()

    @staticmethod
    def _write(db, state, kind, **fields):
        event = Ledger.append(db, kind, **fields)
        state.apply(event)
        return event

    def _start(self, db, state):
        frozen = state.config.get("response_contract", LEGACY_RESPONSE_SCHEMA_VERSION) if state.config else None
        contract = self.response_contract or frozen or RESPONSE_SCHEMA_VERSION
        expected = dict(self.config)
        if contract == RESPONSE_SCHEMA_VERSION:
            expected.update(
                response_contract=contract, assessment_schema_version=ASSESSMENT_SCHEMA_VERSION,
                response_schema_fingerprint=response_schema_fingerprint(self.tools),
                assessment_validator_version=ASSESSMENT_VALIDATOR_VERSION,
                assessment_validator_fingerprint=assessment_validator_fingerprint(),
                transport_mode="structured" if callable(self.structured_send) else "replay",
            )
        elif not callable(self.transport):
            raise HarnessError("Legacy runs require the two-argument transport")
        if state.config is not None:
            if state.config != expected:
                raise HarnessError("Run identity, budget, baseline, tool or response binding differs from the frozen run")
            if self.initial_supplied or self.full_query is not None:
                fresh = RunState()
                fresh.source_hashes[self.identity.query_id] = self.identity.query_source_hash
                if self.initial_supplied and encode(normalize_result(self.initial, fresh)) != encode(state.initial_result):
                    raise HarnessError("Initial observation differs from the frozen run")
                if self.full_query is not None and encode(self.full_query) != encode(state.full_query):
                    raise HarnessError("Whole-query excerpt differs from the frozen run")
            return
        state.source_hashes[self.identity.query_id] = self.identity.query_source_hash
        initial = normalize_result(self.initial, state)
        allowed = {self.identity.query_id}
        if self.initial_candidate_excerpts:
            allowed.update(self.initial.candidates)
        if any(row["case_id"] not in allowed for row in initial["excerpts"]):
            raise HarnessError("Initial source excerpts must belong to the query case")
        if self.full_query is not None:
            check = RunState()
            check.catalog[self.full_query["ref"]] = self.full_query
            for row in initial["excerpts"]:
                if row["case_id"] == self.identity.query_id and row["span_bytes"][1] > self.full_query["span_bytes"][1]:
                    raise SourceDrift(self.identity.query_id)
            normalize_result(self.initial, check)
        self._write(db, state, "run_created", config=expected, initial_result=initial,
                    full_query=self.full_query)

    def run(self):
        with self.ledger.writer() as db:
            state = RunState(self.ledger.read(db))
            self._start(db, state)
            self._recover(db, state)
            while state.final is None:
                try:
                    if state.pending_action is not None:
                        self._apply_action(db, state)
                    else:
                        self._turn(db, state)
                except SourceDrift as exc:
                    self._record_drift(db, state, exc.case_id)
            return state.snapshot()

    def _recover(self, db, state):
        if state.in_flight is not None:
            self._receipt(db, state, state.in_flight, "unknown", error="interrupted_after_admission")
        if state.active_action is not None:
            # An interrupted tool call has no durable result and is never replayed.
            self._action_result(db, state, "unknown", reason="interrupted_action",
                                final=self._final("failure", "interrupted_action"))

    def _verify(self, records):
        if self.verify_source is None:
            return
        seen = set()
        for row in records:
            identity = row["case_id"], row["source_hash"]
            if identity not in seen:
                try:
                    result = self.verify_source(*identity)
                except SourceDrift:
                    raise
                except Exception as exc:
                    raise SourceDrift(identity[0]) from exc
                if result is False:
                    raise SourceDrift(identity[0])
                seen.add(identity)

    def _record_drift(self, db, state, case_id, *, started=None):
        affected = [
            assessment_id for assessment_id in state.active_assessments.values()
            if case_id is None or any(state.catalog[ref]["case_id"] == case_id
                   for ref in assessment_refs(state.assessments[assessment_id]))
        ]
        pending = [pair for pair, row in state.pending_assessments.items()
                   if case_id in (None, row["query_id"], row["candidate_id"])
                   or any(state.catalog[ref]["case_id"] == case_id for ref in assessment_refs(row))]
        self._write(db, state, "source_drift", case_id=case_id, reason="source_drift",
                    invalidated_assessments=affected, invalidated_pending=pending,
                    final=self._final("failure", "source_drift"),
                    action_id=state.active_action["action_id"] if state.active_action else None,
                    local_elapsed_ms=None if started is None else (perf_counter() - started) * 1000)

    def _final(self, reason, detail, prediction=None, assessment_ids=()):
        fallback = reason != "complete"
        return {
            "stop_reason": reason, "stop_detail": detail, "fallback": fallback,
            "prediction": self.baseline if fallback else prediction,
            "prediction_assessment_ids": list(assessment_ids),
        }

    def _stop(self, db, state, reason, detail):
        self._write(db, state, "run_stopped", final=self._final(reason, detail))

    def _count(self, payload):
        count = self.count_tokens(payload)
        if not integer(count):
            raise HarnessError("Token counter must return a nonnegative integer")
        return count

    def _fit_payload(self, state, cap):
        available = list(state.pending)
        payload = {
            "query_id": self.identity.query_id, "query_source_hash": self.identity.query_source_hash,
            "max_output_tokens": self.budget.max_output_tokens, "excerpts": [],
            "current_payload_source_refs": [], "pending_source_count": len(available),
            "observation_omitted": bool(state.observation), "candidate_count": len(state.candidates),
            "active_assessment_count": len(state.active_assessments),
            "query_delivery": "navigation" if not state.full_query_considered else "continuation",
        }

        def offer(**fields):
            candidate = {**payload, **fields}
            if self._count(encode(candidate)) > cap:
                return False
            payload.update(fields)
            return True

        def offer_excerpts(rows, pending_count, **fields):
            return offer(excerpts=rows, current_payload_source_refs=[row["ref"] for row in rows],
                         pending_source_count=pending_count, **fields)

        consumed, remaining = [], []
        if not state.full_query_considered and state.full_query is not None:
            full = state.full_query
            query_refs = [ref for ref in available if state.catalog[ref]["case_id"] == self.identity.query_id]
            if offer_excerpts([full], len(available) - len(query_refs), query_delivery="full",
                              observation_omitted=False):
                consumed.extend(query_refs)
        if not state.full_query_considered and payload["query_delivery"] != "full" and state.observation:
            if not offer(observation=state.observation, observation_omitted=False):
                return None
        for ref in available:
            if ref in consumed:
                continue
            row = state.catalog[ref]
            pending = len(available) - len(consumed)
            if offer_excerpts([*payload["excerpts"], row], pending - 1):
                consumed.append(ref)
                continue
            included = payload["excerpts"]
            clipped = self._fit_prefix(row, lambda part: offer_excerpts([*included, part], pending))
            if clipped is not None:
                consumed.append(ref)
                remaining.append(clipped)
            break
        if state.full_query_considered and state.observation:
            offer(observation=state.observation, observation_omitted=False)
        if available and not payload["excerpts"] and "observation" not in payload:
            return None
        if state.source_requests:
            offer(source_requests=state.source_requests[-1:])
        if state.candidates:
            offer(candidates=list(state.candidates))
        if state.active_assessments:
            offer(assessments=[{key: value for key, value in state.assessments[assessment_id].items()
                                if key != "raw_evidence"}
                               for assessment_id in state.active_assessments.values()])
        if state.pending_assessments:
            offer(pending_assessments=[_pending_summary(row) for row in state.pending_assessments.values()])
        if state.delivered:
            offer(reloadable_source_refs=sorted(state.delivered))
        body = encode(payload)
        count = self._count(body)
        if count > cap:
            return None
        return body, count, consumed, remaining, payload["excerpts"]

    @staticmethod
    def _fit_prefix(row, offer):
        source = excerpt(row)
        start, end = source.span_bytes
        # Check actual serialization at each step. The largest possible prefix
        # is not needed for correctness, and tokenizers may be nonmonotonic.
        low, high = 1, len(source.text) - 1
        best = None
        # Pass independent trial prefixes to the caller. The caller's base
        # excerpts are held fixed by its closure.
        while low <= high:
            count = (low + high) // 2
            split = start + len(source.text[:count].encode("utf-8"))
            if offer(slice_record(row, start, split)):
                best = split
                low = count + 1
            else:
                high = count - 1
        return None if best is None else slice_record(row, best, end)

    def _turn(self, db, state):
        previous = state.last_receipt
        retry_of = None
        if previous is not None and previous["status"] != "success":
            if previous["status"] != "retryable_error" or state.retries >= self.budget.max_retries:
                self._stop(db, state, "failure", previous["error"])
                return
            retry_of = previous["request_id"]
        usage = state.usage()
        if usage["requests"] >= self.budget.max_requests or usage["actions"] >= self.budget.max_actions:
            self._stop(db, state, "budget", "request_cap" if usage["requests"] >= self.budget.max_requests
                       else "action_cap")
            return
        cap = min(self.budget.max_payload_tokens,
                  self.budget.max_input_tokens - usage["charged_input_tokens"])
        if self.budget.max_total_tokens is not None:
            cap = min(cap, self.budget.max_total_tokens - usage["charged_input_tokens"]
                      - usage["charged_output_tokens"] - self.budget.max_output_tokens)
        try:
            prepared = self._fit_payload(state, cap) if cap >= 0 else None
        except Exception as exc:
            self._stop(db, state, "failure", f"token_count_error:{type(exc).__name__}")
            return
        if prepared is None:
            self._stop(db, state, "budget", "payload_token_cap")
            return
        body, count, consumed, remaining, rows = prepared
        self._verify(rows)
        request_id = fingerprint([self.identity.run_id, "request", usage["requests"] + 1])
        admission = self._write(
            db, state, "request_admitted", request_id=request_id, retry_of=retry_of,
            payload=body.decode("utf-8"), admitted_input_tokens=count,
            output_token_cap=self.budget.max_output_tokens, consumed_refs=consumed,
            remaining_excerpts=remaining, excerpts=rows, current_payload_source_refs=[row["ref"] for row in rows],
        )
        self._send(db, state, admission, body)

    def _send(self, db, state, admission, body):
        started = perf_counter()
        try:
            if state.config.get("transport_mode") == "structured":
                reply = self.structured_send(body, admission["request_id"], response_schema(self.tools))
            else:
                reply = self.transport(body, admission["request_id"])
        except TransportError as exc:
            status = "unknown" if exc.unknown else "retryable_error" if exc.retryable else "error"
            self._receipt(db, state, admission, status, telemetry=exc,
                          error=f"transport_{status}", started=started)
            return
        except Exception as exc:
            self._receipt(db, state, admission, "unknown", error=type(exc).__name__, started=started)
            return
        if not isinstance(reply, ModelReply):
            self._receipt(db, state, admission, "malformed", received=True,
                          error="invalid_model_reply", started=started,
                          schema_validation="rejected" if "response_contract" in state.config else None)
            return
        if state.config.get("response_contract") == RESPONSE_SCHEMA_VERSION:
            try:
                action = validate_model_response(reply.action, self.tools)
            except ResponseSchemaError as exc:
                self._receipt(db, state, admission, "malformed", telemetry=reply, received=True,
                              error=f"response_schema:{exc}", started=started, schema_validation="rejected")
                return
            self._receipt(db, state, admission, "success", telemetry=reply, received=True,
                          action=action, started=started, schema_validation="passed")
            return
        try:
            action = parse_model_response(reply.action)
            if (not isinstance(action, dict) or set(action) != {"action", "args"}
                    or not isinstance(action["action"], str)
                    or not isinstance(action["args"], dict)):
                raise HarnessError("Invalid action envelope")
            encode(action)
        except (TypeError, ValueError, HarnessError):
            self._receipt(db, state, admission, "malformed", telemetry=reply, received=True,
                          error="invalid_action_envelope", started=started)
            return
        self._receipt(db, state, admission, "success", telemetry=reply, received=True,
                      action=action, started=started)

    def _receipt(self, db, state, admission, status, *, telemetry=None, received=False,
                 error=None, action=None, started=None, schema_validation=None):
        tokens = {name: getattr(telemetry, name, None) for name in ("input_tokens", "output_tokens")}
        latency = getattr(telemetry, "latency_ms", None)
        telemetry_error = None
        for name, count in tokens.items():
            if count is not None and not integer(count):
                tokens[name] = None
                telemetry_error = "invalid_provider_token_usage"
        if latency is not None and (type(latency) not in (int, float) or not isfinite(latency) or latency < 0):
            latency = None
            telemetry_error = "invalid_provider_latency"
        if ((tokens["input_tokens"] or 0) > admission["admitted_input_tokens"]
                or (tokens["output_tokens"] or 0) > admission["output_token_cap"]):
            telemetry_error = "provider_usage_exceeded_admission"
        if telemetry_error and status not in {"malformed", "unknown"}:
            status, error = "error", telemetry_error
        self._write(db, state, "request_result", request_id=admission["request_id"], status=status,
                    received_response=received, error=error, action=action, provider_latency_ms=latency,
                    transport_elapsed_ms=None if started is None else (perf_counter() - started) * 1000,
                    telemetry_error=telemetry_error, schema_validation=schema_validation, **tokens)

    def _action_result(self, db, state, status, *, result=None, reason=None, reload_refs=(),
                       assessments=(), pending_assessments=(), invalidated=(), final=None, started=None):
        self._write(
            db, state, "action_result", action_id=state.active_action["action_id"], status=status,
            result=result, reason=reason, reload_refs=reload_refs, assessments=assessments,
            pending_assessments=pending_assessments, invalidated_assessments=invalidated, final=final,
            local_elapsed_ms=None if started is None else (perf_counter() - started) * 1000,
        )

    def _apply_action(self, db, state):
        receipt = state.pending_action
        action = receipt["action"]
        name, args = action["action"], action["args"]
        action_id = fingerprint([receipt["request_id"], "action"])
        digest = fingerprint(action)
        duplicate = name in self.tools and digest in state.tool_actions
        executes = name in self.tools and not duplicate
        self._write(db, state, "action_started", action_id=action_id, request_id=receipt["request_id"],
                    action=action, action_fingerprint=digest, executes_tool=executes)
        started = perf_counter()
        status = "success"
        outcome = {}
        structured = state.config.get("response_contract") == RESPONSE_SCHEMA_VERSION
        try:
            if duplicate:
                status = "duplicate"
                outcome = {
                    "result": normalize_result(ToolResult({"action": name, "status": status}), state),
                    "reason": "duplicate_action",
                }
            elif executes:
                outcome["result"] = normalize_result(self.tools[name](json.loads(encode(args))), state,
                                                     search=name in SEARCH_ACTIONS, preserve_provenance=structured)
            elif name == "reload_source":
                outcome = self._reload(state, args)
            elif name == "assess_links":
                if structured:
                    rows, pending, invalidated = validate_assessment_state(args, state, action_id)
                else:
                    rows, invalidated = validate_assessments(args, state, action_id)
                    pending = []
                refs = set().union(*(assessment_refs(row) for row in [*rows, *pending]))
                self._verify(state.catalog[ref] for ref in refs)
                status = "pending_evidence" if pending else "success"
                observation = {"action": name, "status": status,
                               "assessment_ids": [row["assessment_id"] for row in rows]}
                if pending:
                    observation["pending"] = [_pending_summary(row) for row in pending]
                outcome = {"result": normalize_result(ToolResult(observation), state), "assessments": rows,
                           "pending_assessments": pending, "invalidated": invalidated,
                           "reason": "missing_evidence" if pending else "assessment_revision"}
            elif name == "stop":
                outcome["final"] = self._validate_stop(state, args)
            else:
                raise HarnessError("Unknown or unavailable controller action")
        except SourceDrift as exc:
            self._record_drift(db, state, exc.case_id, started=started)
            return
        except Exception as exc:
            if isinstance(exc, AssessmentStateError):
                reason = f"assessment_state:{exc}"
            else:
                reason = str(exc) if isinstance(exc, HarnessError) else type(exc).__name__
            status = "error"
            outcome = {"reason": reason, "final": self._final("failure", reason)}
        self._action_result(db, state, status, **outcome, started=started)

    def _reload(self, state, args):
        if set(args) != {"refs"}:
            raise HarnessError("Expected reload source refs")
        refs = string_list(args["refs"], "reload source refs", nonempty=True)
        if not set(refs) <= state.catalog.keys():
            raise HarnessError("Unknown reload source refs")
        result = normalize_result(ToolResult({"action": "reload_source", "queued_refs": refs}), state)
        return {"result": result, "reload_refs": refs}

    def _validate_stop(self, state, args):
        reason = args.get("reason")
        if not isinstance(reason, str) or reason not in {"complete", "budget", "no_progress", "failure"}:
            raise HarnessError("Invalid stop reason")
        if reason != "complete":
            if set(args) != {"reason"}:
                raise HarnessError("Fallback stop only accepts a reason")
            return self._final(reason, "controller_stop")
        if set(args) - {"reason", "prediction", "assessment_ids"} or "prediction" not in args:
            raise HarnessError("Complete stop requires an explicit prediction")
        prediction = string_list(args["prediction"], "prediction candidate IDs")
        selected = string_list(args.get("assessment_ids", []), "prediction assessment IDs")
        if not set(selected) <= set(state.active_assessments.values()):
            raise HarnessError("Prediction references inactive or unknown assessments")
        rows = [state.assessments[assessment_id] for assessment_id in selected]
        if set(prediction) != {row["candidate_id"] for row in rows}:
            raise HarnessError("Each predicted candidate requires an active assessment")
        refs = set().union(*(assessment_refs(row) for row in rows))
        if not refs <= set(state.current):
            raise HarnessError("Prediction references require raw text in the current payload")
        self._verify(state.catalog[ref] for ref in refs)
        return self._final(reason, "controller_stop", prediction, selected)
