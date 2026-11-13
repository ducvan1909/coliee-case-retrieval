"""Append-only run storage and replayable state."""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from .contracts import HarnessError, encode


class Ledger:
    def __init__(self, run_dir):
        self.path = Path(run_dir)

    @contextmanager
    def writer(self):
        self.path.mkdir(parents=True, exist_ok=True)
        # The OS releases this lock when the process exits. Event commits use a
        # separate database so an admission can survive loss of the writer.
        with self._connect("writer.sqlite3", timeout=0) as lock:
            try:
                lock.execute("BEGIN EXCLUSIVE")
            except sqlite3.OperationalError as exc:
                raise HarnessError("Another writer owns this run") from exc
            with self._connect("events.sqlite3") as db:
                db.execute("PRAGMA synchronous = FULL")
                db.executescript("""
                    CREATE TABLE IF NOT EXISTS events(
                        seq INTEGER PRIMARY KEY, record BLOB NOT NULL
                    );
                    CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
                        BEGIN SELECT RAISE(ABORT, 'M4 events are append-only'); END;
                    CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
                        BEGIN SELECT RAISE(ABORT, 'M4 events are append-only'); END;
                """)
                yield db

    @contextmanager
    def _connect(self, name, **kwargs):
        db = sqlite3.connect(self.path / name, **kwargs)
        try:
            yield db
        finally:
            db.close()

    def read(self, db=None):
        if db is not None:
            return self._read(db)
        path = self.path / "events.sqlite3"
        if not path.is_file():
            return []
        uri = path.resolve().as_uri() + "?mode=ro"
        reader = sqlite3.connect(uri, uri=True)
        try:
            exists = reader.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='events'"
            ).fetchone()
            return self._read(reader) if exists else []
        finally:
            reader.close()

    @staticmethod
    def _read(db):
        return [{"seq": seq, **json.loads(record)}
                for seq, record in db.execute("SELECT seq, record FROM events ORDER BY seq")]

    @staticmethod
    def append(db, kind, **fields):
        event = {"kind": kind, "at_utc": datetime.now(timezone.utc).isoformat(), **fields}
        body = encode(event)
        with db:
            seq = db.execute("INSERT INTO events(record) VALUES (?)", (body,)).lastrowid
        return {"seq": seq, **json.loads(body)}


class RunState:
    def __init__(self, events=()):
        self.config = None
        self.initial_result = None
        self.catalog = {}
        self.source_hashes = {}
        self.source_requests = []
        self.pending = []
        self.delivered = set()
        self.current = []
        self.current_records = {}
        self.observation = None
        self.full_query = None
        self.full_query_considered = False
        self.candidates = {}
        self.assessments = {}
        self.active_assessments = {}
        self.pending_assessments = {}
        self.assessment_outcomes = {
            "accepted": 0, "pending_evidence": 0, "passed_actions": 0,
            "pending_actions": 0, "rejected_actions": 0,
        }
        self.needs = {}
        self.tool_actions = set()
        self.requests = {}
        self.receipts = {}
        self.in_flight = None
        self.last_receipt = None
        self.pending_action = None
        self.active_action = None
        self.actions = 0
        self.tool_attempts = {}
        self.retries = 0
        self.final = None
        for event in events:
            self.apply(event)

    def add_result(self, result):
        self.observation = result["observation"]
        self.candidates.update(dict.fromkeys(result["candidates"]))
        self.source_requests.extend(result["source_requests"])
        self.source_hashes.update(result["source_hashes"])
        refs = []
        for record in result["excerpts"]:
            ref = record["ref"]
            self.catalog.setdefault(ref, record)
            refs.append(ref)
        self.queue(refs)

    def queue(self, refs):
        requested = set(refs)
        self.pending = [*refs, *(ref for ref in self.pending if ref not in requested)]

    def invalidate(self, refs, event):
        for assessment_id in refs:
            self.assessments[assessment_id]["invalidated_at"] = event["seq"]
            self.assessments[assessment_id]["invalidation_reason"] = event["reason"]
            row = self.assessments[assessment_id]
            pair = (row["source_need_id"], row["candidate_id"])
            if self.active_assessments.get(pair) == assessment_id:
                del self.active_assessments[pair]

    def apply(self, event):
        kind = event["kind"]
        if kind == "run_created":
            self.config = event["config"]
            self.candidates.update(dict.fromkeys(self.config["baseline"]))
            identity = self.config["identity"]
            self.source_hashes[identity["query_id"]] = identity["query_source_hash"]
            self.full_query = event["full_query"]
            self.initial_result = event["initial_result"]
            self.add_result(self.initial_result)
        elif kind == "request_admitted":
            request_id = event["request_id"]
            self.in_flight = event
            self.requests[request_id] = event
            self.retries += event["retry_of"] is not None
            self.current = []
            self.current_records = {}
        elif kind == "request_result":
            self.in_flight = None
            self.last_receipt = event
            self.receipts[event["request_id"]] = event
            if event["received_response"]:
                request = self.requests[event["request_id"]]
                self.full_query_considered = True
                for consumed in request["consumed_refs"]:
                    self.pending.remove(consumed)
                for record in request["remaining_excerpts"]:
                    self.catalog.setdefault(record["ref"], record)
                self.queue([record["ref"] for record in request["remaining_excerpts"]])
                for record in request["excerpts"]:
                    self.catalog.setdefault(record["ref"], record)
                self.current = request["current_payload_source_refs"]
                self.current_records = {row["ref"]: row for row in request["excerpts"]}
                self.delivered.update(self.current)
            if event["status"] == "success":
                self.pending_action = event
        elif kind == "action_started":
            self.pending_action = None
            self.active_action = event
            self.actions += 1
            if event["executes_tool"]:
                self.tool_actions.add(event["action_fingerprint"])
                self.tool_attempts[event["action_id"]] = None
        elif kind == "action_result":
            self.active_action = None
            if event["action_id"] in self.tool_attempts:
                self.tool_attempts[event["action_id"]] = event["local_elapsed_ms"]
            if event["result"] is not None:
                self.add_result(event["result"])
            self.queue(event["reload_refs"])
            self.invalidate(event["invalidated_assessments"], event)
            if (event["reason"] or "").startswith("assessment_state:"):
                self.assessment_outcomes["rejected_actions"] += 1
            pending_assessments = event.get("pending_assessments", ())
            if pending_assessments:
                self.assessment_outcomes["pending_actions"] += 1
            elif event["assessments"]:
                self.assessment_outcomes["passed_actions"] += 1
            contexts = {row["source_need_id"]: row["a_context_refs"]
                        for row in [*event["assessments"], *pending_assessments] if row["a_context_refs"]}
            for pair, row in list(self.pending_assessments.items()):
                if pair[0] in contexts and row["a_context_refs"] and row["a_context_refs"] != contexts[pair[0]]:
                    del self.pending_assessments[pair]
            self.needs.update(contexts)
            for row in pending_assessments:
                pair = row["source_need_id"], row["candidate_id"]
                self.pending_assessments[pair] = {**row, "recorded_at": event["seq"]}
                self.assessment_outcomes["pending_evidence"] += 1
            for row in event["assessments"]:
                assessment_id = row["assessment_id"]
                self.assessments[assessment_id] = {**row, "created_at": event["seq"]}
                pair = row["source_need_id"], row["candidate_id"]
                self.active_assessments[pair] = assessment_id
                self.pending_assessments.pop(pair, None)
                self.assessment_outcomes["accepted"] += 1
            if event["final"] is not None:
                self.final = event["final"]
        elif kind == "source_drift":
            self.invalidate(event["invalidated_assessments"], event)
            for pair in event.get("invalidated_pending", ()):
                self.pending_assessments.pop(tuple(pair), None)
            if event["action_id"] in self.tool_attempts:
                self.tool_attempts[event["action_id"]] = event["local_elapsed_ms"]
            self.active_action = None
            self.pending_action = None
            self.final = event["final"]
        elif kind == "run_stopped":
            self.final = event["final"]
        else:
            raise HarnessError(f"Unknown ledger event {kind}")

    def usage(self):
        receipts = list(self.receipts.values())
        admitted_input = sum(request["admitted_input_tokens"] for request in self.requests.values())
        reported_input = sum(receipt["input_tokens"] or 0 for receipt in receipts)
        reported_output = sum(receipt["output_tokens"] or 0 for receipt in receipts)
        transport_times = [row["transport_elapsed_ms"] for row in receipts if row["transport_elapsed_ms"] is not None]
        provider_times = [row["provider_latency_ms"] for row in receipts if row["provider_latency_ms"] is not None]
        tool_times = [elapsed for elapsed in self.tool_attempts.values() if elapsed is not None]
        charged_input = charged_output = 0
        for request_id, request in self.requests.items():
            receipt = self.receipts.get(request_id, {})
            output = receipt.get("output_tokens")
            charged_input += max(request["admitted_input_tokens"], receipt.get("input_tokens") or 0)
            charged_output += request["output_token_cap"] if output is None else output
        return {
            "requests": len(self.requests), "retries": self.retries,
            "actions": self.actions, "tool_calls": len(self.tool_attempts),
            "observed_transport_elapsed_ms": sum(transport_times),
            "reported_provider_latency_ms": sum(provider_times),
            "observed_tool_elapsed_ms": sum(tool_times),
            "unknown_transport_elapsed_requests": len(self.requests) - len(transport_times),
            "unknown_provider_latency_requests": len(self.requests) - len(provider_times),
            "unknown_tool_elapsed_calls": len(self.tool_attempts) - len(tool_times),
            "admitted_input_tokens": admitted_input,
            "reported_input_tokens": reported_input, "reported_output_tokens": reported_output,
            "unknown_input_token_requests": len(self.requests) - sum(
                receipt["input_tokens"] is not None for receipt in receipts),
            "unknown_output_token_requests": len(self.requests) - sum(
                receipt["output_tokens"] is not None for receipt in receipts),
            "charged_input_tokens": charged_input, "charged_output_tokens": charged_output,
            "unknown_receipts": sum(receipt["status"] == "unknown" for receipt in receipts),
            "repeated_source_refs": sum(
                len(self.requests[receipt["request_id"]]["current_payload_source_refs"])
                for receipt in receipts if receipt["received_response"]
            ) - len(self.delivered),
        }

    def snapshot(self):
        result = {
            "config": self.config, "usage": self.usage(),
            "candidates": list(self.candidates), "source_needs": self.needs,
            "source_requests": self.source_requests, "source_catalog": self.catalog,
            "pending_source_refs": self.pending, "delivered_source_refs": sorted(self.delivered),
            "current_payload_source_refs": self.current,
            "assessments": list(self.assessments.values()),
            "active_assessment_ids": list(self.active_assessments.values()),
            "pending_request_id": self.in_flight["request_id"] if self.in_flight else None,
            "pending_action_id": self.active_action["action_id"] if self.active_action else None,
            "stop_reason": None, "prediction": None, "fallback": None,
            **(self.final or {}),
        }
        if self.config and "response_contract" in self.config:
            result.update(
                pending_assessments=list(self.pending_assessments.values()),
                candidate_states=self.candidate_states(),
                assessment_validation={
                    **self.assessment_outcomes,
                    "schema_passed_responses": sum(row.get("schema_validation") == "passed"
                                                   for row in self.receipts.values()),
                    "schema_rejected_responses": sum(row.get("schema_validation") == "rejected"
                                                     for row in self.receipts.values()),
                },
            )
        return result

    def candidate_states(self):
        states = {}
        for candidate in self.candidates:
            accepted = [self.assessments[key] for (_, current), key in self.active_assessments.items()
                        if current == candidate]
            pending = [row for (_, current), row in self.pending_assessments.items() if current == candidate]
            relations = {row["case_relation"] for row in accepted}
            missing = {reason for row in pending for reason in row["missing_evidence"]}
            if not accepted and not pending:
                missing = {"a_context_refs", "b_passage_refs"}
            states[candidate] = {
                "status": "accepted" if accepted else "pending_evidence" if pending else "retrieval_only",
                "case_relation": next(iter(relations)) if len(relations) == 1 else "unknown",
                "missing_evidence": sorted(missing),
                "assessment_ids": [row["assessment_id"] for row in accepted],
            }
        return states
