"""Local real-source replay. No provider inference and no gold access.

The explicit limits below are an engineering fixture, not a calibrated profile.
Run from the repository root after implementation is frozen.
"""
from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
from time import perf_counter

from pipeline_v2.agent_harness import Budget, RunIdentity
from pipeline_v2.agent_harness.contracts import ModelReply, encode, fingerprint
from pipeline_v2.agent_harness.modal_qwen import ModalQwenTransport
from pipeline_v2.full_search.source_tools import SourceToolsSession
from pipeline_v2.m4 import M3Tools
from pipeline_v2.m6 import AdaptiveConfig, AdaptiveHarness, M6_INSTRUCTIONS
from pipeline_v2.sparse_bm25.index import SparseSession


class Replay:
    def __init__(self, counter):
        self.count_tokens = counter
        self.calls = []

    def send_structured(self, payload, request_id, schema):
        body = json.loads(payload)
        tools = {row["name"]: row for row in body["available_tools"]}
        step = len(self.calls)
        if step == 0:
            action = {"action": "search_cases_by_issue", "args": {
                "issue": "standard of review",
                "a_paragraph_ref": next(iter(body["m6"]["a_paragraphs"])),
            }}
        elif step == 1:
            action = {"action": "read_case_passages", "args": {
                "candidate_ref": next(iter(body["m6"]["candidates"])), "focus": "standard of review"}}
        elif "assess_case_link" in tools and not body["active_assessment_count"]:
            fields = tools["assess_case_link"]["parameters"]["properties"]
            # Select only schema-valid synthetic labels; this does not assess legal correctness.
            args = {}
            for key, field in fields.items():
                if "enum" in field:
                    args[key] = field["enum"][0]
                elif field.get("type") == "array":
                    args[key] = []
                elif key == "speaker":
                    args[key] = {"role": "unknown"}
                elif "anyOf" in field:
                    args[key] = {"role": "unknown"}
                else:
                    args[key] = "Synthetic replay; no semantic conclusion."
            args.update(case_relation="unknown", passage_location="unresolved")
            # Optional text fields must not create a pending assessment in this fixture.
            args = {key: value for key, value in args.items()
                    if key in tools["assess_case_link"]["parameters"]["required"]}
            action = {"action": "assess_case_link", "args": args}
        elif body["active_assessment_count"]:
            action = {"action": "finish_case_review", "args": {"reason": "complete_policy"}}
        elif "reload_evidence" in tools:
            pairs = {key: refs for key, refs in body["m6"]["reloads"].items() if len(refs) == 2}
            action = {"action": "reload_evidence", "args": {"evidence_ref": next(iter(pairs))}}
        else:
            raise AssertionError("Replay cannot progress from current purpose tools")
        self.calls.append({"request_id": request_id, "action": action,
                           "available_tools": list(tools), "payload_tokens": self.count_tokens(payload)})
        return ModelReply(action, self.count_tokens(payload), 0, None)


def main():
    root = Path.cwd()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    directory = root / "pipeline_v2/reviews/m6_local_v1" / ("corpus_replay_" + stamp)
    # Tokenizer initialization is local. Fail loudly if anything tries to create a remote client.
    def no_remote():
        raise AssertionError("Local replay must not create a Modal client")
    tokenizer = ModalQwenTransport(root / "cache/tokenizers/qwen36_27b_fp8",
                                   instructions=M6_INSTRUCTIONS, remote_factory=no_remote)
    replay = Replay(tokenizer.count_tokens)
    budget = Budget(12, 12, 120000, 16384, 512, 126144, 0)
    config = AdaptiveConfig(channel="lexical_both", search_limit=3, read_limit=2,
                            no_progress_actions=4, max_reviews=1, audit_untriggered=1)
    started = perf_counter()
    with closing(SparseSession(root)) as lexical:
        with closing(SourceToolsSession(root, snapshot=lexical)) as sources:
            tools = M3Tools(sources, lexical, "017984.txt", byte_budget=4096, map_limit=5)
            initial, whole = tools.query_start()
            identity = RunIdentity(directory.name, "017984.txt", whole.source_hash,
                                   fingerprint(lexical.binding), fingerprint(lexical.index_binding),
                                   fingerprint([asdict(budget), asdict(config), "local-replay-only"]),
                                   "synthetic-controller-not-a-model", tokenizer.prompt_fingerprint,
                                   tools.fingerprint, tokenizer.tokenizer_fingerprint)
            harness = AdaptiveHarness(directory, identity=identity, budget=budget, m3_tools=tools,
                                      transport=replay, config=config,
                                      initial_observation=initial, query_excerpt=whole)
            preview = harness.prepare()
            assert preview["status"] == "ready", preview
            result = harness.run()
            # Resume the same frozen run without any additional transport call.
            before = len(replay.calls)
            resumed = harness.run()
            checks = {
                "bounded_stop": result["stop_reason"] == "complete",
                "pending_selector": result["selection_status"] == "pending_selection" and result["prediction"] is None,
                "accepted_assessment": len(result["active_assessment_ids"]) == 1,
                "no_retry": result["usage"]["retries"] == 0,
                "resume_no_send": len(replay.calls) == before and resumed["usage"] == result["usage"],
                "no_modal": tokenizer.receipts == [],
            }
    report = {"status": "PASS" if all(checks.values()) else "FAIL", "checks": checks,
              "model_requests": 0, "replay_turns": replay.calls, "budget": asdict(budget),
              "adaptive_config": asdict(config), "first_payload_tokens": preview["input_tokens"],
              "result": result, "elapsed_seconds": perf_counter() - started,
              "limitation": "Real corpus/tool/tokenizer integration with synthetic actions and labels; no semantic or live-model acceptance."}
    (directory / "report.json").write_bytes(encode(report))
    print(json.dumps({"status": report["status"], "checks": checks, "report": str(directory / "report.json")}, ensure_ascii=False))
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
