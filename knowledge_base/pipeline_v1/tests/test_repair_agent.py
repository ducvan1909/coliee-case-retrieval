"""Implementer smoke/invariants; synthetic context labels are never real gold.

Runtime fault fixtures intentionally patch source verification: those tests
contain no corpus source. Actual v6 builder tests exercise real source binding.
"""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from knowledge_base.pipeline_v1.au_candidate_store.core import _hash
from knowledge_base.pipeline_v1.repair_agent import RepairSession, MockAdapter, run_arm, build_tasks
from knowledge_base.pipeline_v1.repair_agent.core import MODEL, POLICY, load, safe_error
from knowledge_base.pipeline_v1.repair_agent.runtime import initial_messages, _restore, _persist

BASE = Path(__file__).resolve().parents[1]
RUN = BASE / "outputs/plan11_semantic_v6_gate_20261011/run/run.json"
OLD = RUN.with_name("review.bound.json")
NEW = BASE / "outputs/plan12_agent_repair_20261011/inputs/review.source_exact.v2.json"


def task_fixture():
    digest = _hash("synthetic")
    target = {"case_id": "011904", "source_hash": digest, "start_char": 0, "end_char": 7, "quote": "Rule X."}
    atom = {**target, "atom_id": "a"}
    context = {**target, "atom_id": "b", "start_char": 8, "end_char": 17, "quote": "Unless Y.", "direction": "after"}
    au = {"kind": "holding", "other_kind": None, "claim": "Rule X applies.", "evidence_ref_ids": ["a"],
          "speaker": "current_court", "attribution_role": "proposition", "needs_context": []}
    pid = "proposal-" + _hash(au)
    obligation = {"obligation_id": "o", "task_id": "t", "target_id": "raw-t", "obligation_type": "condition",
                  "requested_direction_or_ref": "after", "reason": "Synthetic missing condition only",
                  "producer": "synthetic_fixture", "run_id": "synthetic", "status": "pending",
                  "searched_spans": [], "stop_reason": None, "review_confirmation": None}
    return {"artifact_type": "RepairTask", "schema_version": "repair-task-v1", "task_id": "t",
            "case_id": "011904", "source_hash": digest, "target_id": "raw-t", "raw_targets": [target],
            "request": {}, "original_proposals": [{"proposal_id": pid, "proposal_sha256": _hash(au), "proposal": au, "aliases": []}],
            "original_responses": [], "supplied_atom_catalog": [atom], "expansion_atom_catalog": [context],
            "review_oracle": [], "error_origin": "agent_review", "technical_errors_origin": "host",
            "technical_errors": [], "selection": "repair", "semantic_errors": [], "obligations": [obligation],
            "model": MODEL, "policy": POLICY, "semantic_gold": False}


def submit(task, action="keep", replacements=None):
    witness = {"atom_id": task["supplied_atom_catalog"][0]["atom_id"], "quote": task["supplied_atom_catalog"][0]["quote"]}
    d = {"proposal_id": task["original_proposals"][0]["proposal_id"], "reason": "Synthetic assertion requiring independent review"}
    if action == "keep": d.update(verdict="supported", primary_proposition=witness)
    elif action == "unresolved": d.update(verdict="uncertain")
    else:
        d.update(verdict="defect_found", defect_type="qualification", witnesses=[witness], correction={"action": action})
        if action == "replace": d["correction"]["replacements"] = replacements or []
    return {"task_id": task["task_id"], "decisions": [d]}


def envelope(name, args):
    return {"tool_calls": [{"name": name, "arguments": args}]}


def manifest_fixture(count=1):
    tasks = []
    for i in range(count):
        t = task_fixture()
        t["task_id"] = "t" + str(i)
        t["obligations"][0]["task_id"] = t["task_id"]
        tasks.append(t)
    return {"tasks": tasks, "manifest_sha256": _hash(tasks), "source_workload": [{"case_id": "011904"}],
            "task_case_ids": ["011904"], "task_workload": "synthetic only"}


class ToolInvariants(unittest.TestCase):
    def setUp(self):
        self.task = task_fixture()
        self.session = RepairSession(self.task, "R2")

    def test_replace_one_into_many_pending_and_original_immutable(self):
        original = copy.deepcopy(self.task)
        au = copy.deepcopy(self.task["original_proposals"][0]["proposal"])
        replacements = [{"au": au, "primary_proposition": {"atom_id": "a", "quote": "Rule X."}},
                        {"au": {**au, "claim": "A distinct synthetic candidate."}, "primary_proposition": {"atom_id": "a", "quote": "Rule X."}}]
        result = self.session.call_tool("submit_revision", submit(self.task, "replace", replacements))
        self.assertTrue(result["ok"])
        self.assertEqual(2, len(result["result"]["verified_replacements"]))
        self.assertEqual(original, self.task)
        self.assertTrue(all(not r["accepted_semantic"] for r in result["result"]["verified_replacements"]))
        self.assertEqual("semantic_review_pending", result["result"]["semantic_status"])

    def test_context_primary_is_not_raw_target_owner_even_same_atom(self):
        # Atom crossing raw TARGET is insufficient: exact primary must be inside.
        t = copy.deepcopy(self.task)
        t["supplied_atom_catalog"][0].update(quote="Rule X. Unless Y.", end_char=17)
        session = RepairSession(t, "R2")
        args = submit(t)
        args["decisions"][0]["primary_proposition"]["quote"] = "Unless Y."
        result = session.call_tool("submit_revision", args)
        self.assertFalse(result["ok"])
        self.assertIsNone(session.state["revision"])

    def test_unread_evidence_and_foreign_offsets_fail_locally(self):
        au = copy.deepcopy(self.task["original_proposals"][0]["proposal"])
        au["evidence_ref_ids"] = ["b"]
        result = self.session.call_tool("submit_revision", submit(self.task, "replace", [{"au": au, "primary_proposition": {"atom_id": "b", "quote": "Unless Y."}}]))
        self.assertFalse(result["ok"])
        self.assertFalse(self.session.call_tool("open_span", {"atom_id": "foreign"})["ok"])
        self.assertFalse(self.session.call_tool("open_span", {"atom_id": "a", "end_char": 100})["ok"])
        self.assertTrue(self.session.call_tool("open_span", {"atom_id": "a"})["ok"])

    def test_reads_submit_never_satisfy_but_bound_confirmation_does(self):
        self.assertTrue(self.session.call_tool("expand_context", {"direction": "after", "reason": "Synthetic condition"})["ok"])
        self.assertEqual("pending", self.session.state["obligations"][0]["status"])
        self.assertFalse(self.session.call_tool("expand_context", {"direction": "after", "reason": "Again"})["ok"])
        self.session.call_tool("submit_revision", submit(self.task))
        self.assertEqual("pending", self.session.state["obligations"][0]["status"])
        confirmation = {"obligation_id": "o", "revision_sha256": _hash(self.session.state["revision"]),
                        "reviewer_id": "independent_fixture_reviewer", "reviewed": True,
                        "witnesses": [{"atom_id": "b", "quote": "Unless Y."}], "reason": "Explicit fixture review"}
        stale = {**confirmation, "revision_sha256": "0" * 64}
        with self.assertRaises(ValueError): self.session.confirm_obligation(stale)
        self.session.confirm_obligation(confirmation)
        self.assertEqual("satisfied", self.session.state["obligations"][0]["status"])

    def test_tool_caps_and_R1_only_submit(self):
        s = RepairSession(self.task, "R2")
        for _ in range(8): self.assertTrue(s.call_tool("get_related_aus", {})["ok"])
        self.assertFalse(s.call_tool("submit_revision", submit(self.task))["ok"])
        r1 = RepairSession(self.task, "R1")
        self.assertFalse(r1.call_tool("open_span", {"atom_id": "a"})["ok"])
        self.assertTrue(r1.call_tool("submit_revision", submit(self.task))["ok"])

    def test_prompt_hides_oracle_controls_and_expansion_text(self):
        t = copy.deepcopy(self.task)
        t["review_oracle"] = [{"secret": "accepted_gold_answer"}]
        prompt = json.dumps(initial_messages(t, "R2"))
        self.assertNotIn("accepted_gold_answer", prompt)
        self.assertNotIn("Unless Y.", prompt)


class RuntimeFaults(unittest.TestCase):
    def run_local(self, manifest, arm, root, adapter=None, task_ids=None):
        with patch("knowledge_base.pipeline_v1.repair_agent.runtime.verify_manifest", return_value=True):
            return run_arm(manifest, arm, root, adapter, task_ids)

    def test_two_turn_single_read_then_submit_resume_zero_calls(self):
        m = manifest_fixture(); t = m["tasks"][0]
        read = envelope("expand_context", {"direction":"after", "reason":"Synthetic condition"})
        script = {t["task_id"]: [read, envelope("submit_revision", submit(t))]}
        with tempfile.TemporaryDirectory() as root:
            adapter = MockAdapter(script)
            r = self.run_local(m, "R2", root, adapter)
            self.assertEqual("revision_submitted", r["tasks"][0]["status"])
            self.assertEqual(2, adapter.calls)
            resumed = MockAdapter(script)
            self.run_local(m, "R2", root, resumed)
            self.assertEqual(0, resumed.calls)
            self.assertEqual(0, r["cost_summary"]["provider_total_tokens_known"])
            self.assertEqual("pending", r["tasks"][0]["session"]["obligations"][0]["status"])

    def test_R0_no_calls_and_R1_direct_submission(self):
        m = manifest_fixture(); t = m["tasks"][0]
        with tempfile.TemporaryDirectory() as root:
            a = MockAdapter({t["task_id"]: [envelope("submit_revision", submit(t))]})
            self.run_local(m, "R0", root, a)
            self.assertEqual(0, a.calls)
            r = self.run_local(m, "R1", root, a)
            self.assertEqual(1, a.calls)
            self.assertEqual("revision_submitted", r["tasks"][0]["status"])

    def test_reservation_before_dispatch_failure_and_stop_unknown_usage(self):
        m = manifest_fixture(2)
        class Failure(MockAdapter):
            def __call__(self, messages, **kwargs):
                path = next(Path(root).rglob("checkpoint.json"))
                state = _restore(path)
                self.asserted_reserved = state["attempts"][-1]["charged_tokens"] > 0
                raise RuntimeError("provider unavailable")
        with tempfile.TemporaryDirectory() as root:
            a = Failure(); a.is_mock = False
            r = self.run_local(m, "R2", root, a)
            self.assertTrue(a.asserted_reserved)
            self.assertEqual("incomplete", r["status"])
            self.assertEqual(1, len(r["attempts"]))
            self.assertIsNone(r["attempts"][0]["provider_usage"])
            self.assertEqual("provider_stopped", r["tasks"][1]["status"])

    def test_actual_usage_caps_stop_before_tools(self):
        for usage in [{"prompt_tokens": 6001, "completion_tokens": 2, "total_tokens": 6003},
                      {"prompt_tokens": 1, "completion_tokens": 1201, "total_tokens": 1202},
                      {"total_tokens": 20001}]:
            m = manifest_fixture(2); t = m["tasks"][0]
            class Usage(MockAdapter):
                is_mock = False
                def __call__(self, messages, **kwargs):
                    return {"output": envelope("submit_revision", submit(t)), "provider_usage": usage}
            with tempfile.TemporaryDirectory() as root:
                r = self.run_local(m, "R1", root, Usage())
                self.assertEqual("incomplete", r["status"])
                self.assertEqual("actual_usage_cap_violation", r["tasks"][0]["status"])
                self.assertIsNone(r["tasks"][0]["session"]["revision"])
                self.assertEqual(1, len(r["attempts"]))

    def test_invalid_output_no_AU_conversion_and_new_input_not_reused(self):
        m = manifest_fixture()
        a = MockAdapter({"*": [{"tool_calls": []}]})
        with tempfile.TemporaryDirectory() as root:
            r = self.run_local(m, "R1", root, a)
            self.assertEqual("technical_invalid", r["tasks"][0]["status"])
            self.assertIsNone(r["tasks"][0]["session"]["revision"])
            m["tasks"][0]["original_proposals"][0]["proposal"]["claim"] = "Changed input"
            r2 = self.run_local(m, "R1", root, a)
            self.assertNotEqual(r["run_key"], r2["run_key"])

    def test_inflight_resume_never_redispatches_and_selection_explicit(self):
        m = manifest_fixture(2)
        with tempfile.TemporaryDirectory() as root:
            a = MockAdapter()
            r = self.run_local(m, "R1", root, a, ["t0"])
            cp = Path(r["output_root"]) / "checkpoint.json"
            state = _restore(cp)
            state["tasks"]["t0"]["status"] = "in_flight"
            state["attempts"][0]["status"] = "in_flight"
            _persist(cp, state)
            b = MockAdapter()
            resumed = self.run_local(m, "R1", root, b, ["t0"])
            self.assertEqual(0, b.calls)
            self.assertEqual("incomplete", resumed["status"])
            self.assertEqual(["t0"], resumed["selected_task_ids"])


class ActualBuilder(unittest.TestCase):
    def test_output_guard_precedes_writes_and_rejects_source_descendants(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "source"
            atoms = Path(root) / "atoms"
            for output in (source, source / "nested", atoms / "nested"):
                with self.assertRaisesRegex(ValueError, "output_root_overlaps_source"):
                    build_tasks(RUN, NEW, source, atoms, output)
                self.assertFalse(output.exists())
                m = {**manifest_fixture(), "source_store": str(source), "atom_root": str(atoms)}
                with self.assertRaisesRegex(ValueError, "output_root_overlaps_source"):
                    run_arm(m, "R0", output)
                self.assertFalse(output.exists())

    def test_old_bad_quote_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "witness_quote_missing_or_nonunique"):
            build_tasks(RUN, OLD, BASE / "outputs/source_store_v1", BASE / "outputs/plan04_sentence_atoms_v1")

    def test_corrected_real_manifest_grouping_provenance_and_no_invented_context(self):
        m = build_tasks(RUN, NEW, BASE / "outputs/source_store_v1", BASE / "outputs/plan04_sentence_atoms_v1")
        self.assertEqual(4, m["task_count"])
        self.assertEqual(5, len(m["source_workload"]))
        self.assertNotIn("013009", m["task_case_ids"])
        for t in m["tasks"]:
            self.assertEqual("agent_review", t["error_origin"])
            self.assertEqual([], t["obligations"])
            digests = [p["proposal_sha256"] for p in t["original_proposals"]]
            self.assertEqual(len(digests), len(set(digests)))
        self.assertGreater(len(next(t for t in m["tasks"] if t["case_id"] == "013948")["original_proposals"]), 1)

    def test_stale_review_digest_rejected_and_diagnostics_safe(self):
        review = load(NEW)
        review["reviews"][0]["run_sha256"] = "0" * 64
        with tempfile.TemporaryDirectory() as root:
            p = Path(root) / "review.json"; p.write_text(json.dumps(review), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "stale_review_binding"):
                build_tasks(RUN, p, BASE / "outputs/source_store_v1", BASE / "outputs/plan04_sentence_atoms_v1")
        self.assertEqual("ValueError", safe_error(ValueError("Bearer secret-url"))["code"])


class CompactRepairRegression(unittest.TestCase):
    run_local = RuntimeFaults.run_local
    def compact(self, task, action="unresolved"):
        replacements = None
        if action == "replace":
            au=copy.deepcopy(task["original_proposals"][0]["proposal"])
            del au["other_kind"]; del au["needs_context"]
            replacements=[{"au":au,"primary_proposition":{"atom_id":"a","quote":"Rule X."}}]
        return envelope("submit_revision", submit(task, action, replacements))

    def test_compact_defaults_keep_and_no_guessed_required_fields(self):
        from knowledge_base.pipeline_v1.repair_agent.wire import normalize
        t=task_fixture()
        for action in ("keep","replace","reject","unresolved"):
            full=normalize(self.compact(t,action),t,"R1",1,["a"])
            self.assertTrue(RepairSession(t,"R1").call_tool("submit_revision", full["tool_calls"][0]["arguments"])["ok"])
            if action=="replace":
                au=full["tool_calls"][0]["arguments"]["decisions"][0]["correction"]["replacements"][0]["au"]
                self.assertIsNone(au["other_kind"]);self.assertEqual([],au["needs_context"])
        bad=self.compact(t,"keep");del bad["tool_calls"][0]["arguments"]["decisions"][0]["primary_proposition"]
        with self.assertRaises(Exception):normalize(bad,t,"R1",1,["a"])
        for field in ("claim","speaker","evidence_ref_ids"):
            bad=self.compact(t,"replace");del bad["tool_calls"][0]["arguments"]["decisions"][0]["correction"]["replacements"][0]["au"][field]
            with self.assertRaises(Exception):normalize(bad,t,"R1",1,["a"])

    def test_host_only_conditional_bounds_and_foreign_ids(self):
        from knowledge_base.pipeline_v1.repair_agent.wire import normalize
        t=task_fixture()
        for field,value in [("claim",None),("claim","x"*301),("speaker",12),("other_kind","illegal label"),("evidence_ref_ids",["foreign"])]:
            bad=self.compact(t,"replace");bad["tool_calls"][0]["arguments"]["decisions"][0]["correction"]["replacements"][0]["au"][field]=value
            with self.assertRaises(Exception):normalize(bad,t,"R1",1,["a"])
        bad=self.compact(t);bad["tool_calls"][0]["arguments"]["decisions"][0]["reason"]="x"*121
        with self.assertRaises(Exception):normalize(bad,t,"R1",1,["a"])

    def test_one_call_final_submit_and_failed_partial_status_cache(self):
        m=manifest_fixture(2)
        for count in (2,9,15):
            bad={"tool_calls":[{"name":"get_repair_task","arguments":{}}]*count}
            with tempfile.TemporaryDirectory() as root:
                a=MockAdapter({"*":[bad]});r=self.run_local(m,"R2",root,a)
                self.assertEqual("failed",r["status"]);self.assertEqual("none_valid",r["revision_status"])
                resumed=MockAdapter({"*":[bad]});self.run_local(m,"R2",root,resumed);self.assertEqual(0,resumed.calls)
        script={"t0":[self.compact(m["tasks"][0])],"t1":[{"tool_calls":[]}]}
        with tempfile.TemporaryDirectory() as root:
            r=self.run_local(m,"R1",root,MockAdapter(script));self.assertEqual("partial",r["status"]);self.assertEqual("partial_valid",r["revision_status"])
        with tempfile.TemporaryDirectory() as root:
            r=self.run_local(manifest_fixture(),"R2",root,MockAdapter({"*":[envelope("get_repair_task",{}),envelope("get_repair_task",{})]}))
            self.assertEqual("failed",r["status"])

    def test_context_rebuild_no_duplicate_text_and_bound_payload(self):
        from knowledge_base.pipeline_v1.repair_agent.runtime import next_messages, model_result, estimate_preflight, estimate_input
        from knowledge_base.pipeline_v1.repair_agent.adapter import JobsAdapter
        t=task_fixture();s=RepairSession(t,"R2")
        event=s.call_tool("get_repair_task",{});self.assertNotIn("Rule X.",json.dumps(event))
        event=s.call_tool("open_span",{"atom_id":"a"});self.assertNotIn("quote",model_result(event)["result"])
        event=s.call_tool("expand_context",{"direction":"after","reason":"Read condition"})
        messages=next_messages(t,"R2",s,[event]);data=json.loads(messages[1]["content"])
        self.assertEqual(["a","b"],[a["atom_id"] for a in data["supplied_atom_catalog"]])
        self.assertNotIn("Unless Y.",json.dumps(data["tool_results"]))
        adapter=JobsAdapter({"model":MODEL,"jobs_url":"https://example.invalid/v1/jobs","token":"synthetic"})
        request=adapter.prepare_payload(messages,task=t,turn=2,arm="R2",attempt_id="0"*64)
        self.assertIn('b',request["ebnf"]);self.assertNotIn("response_format",request)
        self.assertGreater(estimate_input(request["messages"]),estimate_input(messages))
        self.assertLessEqual(estimate_input(request["messages"]),estimate_preflight(t,"R2")["second_turn_input_bound"])

    def test_actual_live_failures_and_provider_receipt_retained(self):
        from knowledge_base.pipeline_v1.repair_agent.adapter import JobsAdapter
        from knowledge_base.pipeline_v1.repair_agent.wire import normalize
        live=BASE / "outputs/plan12_live_20261011_164339/live"
        if not live.exists():self.skipTest("historical live fixtures not available")
        rows=[load(p) for p in live.glob("*/*/run.json")]
        length=next(a["response"] for r in rows for a in r["attempts"] if a["response"].get("finish_reason")=="length")
        self.assertIsNone(length["output"])
        many=next(a["response"]["output"] for r in rows for a in r["attempts"] if isinstance(a["response"].get("output"),dict) and len(a["response"]["output"].get("tool_calls",[]))>8)
        with self.assertRaises(Exception):normalize(many,task_fixture(),"R2",1,["a"])
        for reason,content in [("length",'{"tool_calls":'),("stop",'{"tool_calls":null}')]:
            usage={"prompt_tokens":11,"completion_tokens":17,"total_tokens":28}
            body={"choices":[{"finish_reason":reason,"message":{"content":content}}],"usage":usage}
            adapter=JobsAdapter({"model":MODEL,"jobs_url":"https://example.invalid/v1/jobs","token":"synthetic"})
            with patch("knowledge_base.pipeline_v1.repair_agent.adapter.complete_job",return_value=(body,{"job_id":"j","latency_ms":1})):
                r=adapter(initial_messages(task_fixture(),"R1"),task=task_fixture(),turn=1,arm="R1",attempt_id="0"*64)
            self.assertEqual(usage,r["provider_usage"]);self.assertEqual(reason,r["finish_reason"]);self.assertEqual("j",r["job_id"])

    def test_local_probe_generator_only_and_forced_branches(self):
        from knowledge_base.pipeline_v1.repair_agent.probe import run_probe
        with tempfile.TemporaryDirectory() as root:
            with patch("knowledge_base.pipeline_v1.repair_agent.adapter.complete_job",side_effect=AssertionError("offline probe must not dispatch")):
                r=run_probe(Path(root))
            self.assertEqual("prepared",r["status"]);self.assertEqual(0,r["cost_summary"]["attempts"])
            self.assertEqual(8,len(r["cases"]))
            request=load(Path(root)/"replace_types.payload.json")
            self.assertIn('replace',request["ebnf"]);self.assertNotIn('\\"uncertain\\"',request["ebnf"])
            self.assertNotIn("response_format",request)


class ValidateFirstRegression(unittest.TestCase):
    run_local = RuntimeFaults.run_local

    def test_action_only_is_rejected_by_runtime_even_mock_but_explicit_offline_exists(self):
        from knowledge_base.pipeline_v1.repair_agent.wire import normalize
        t = task_fixture()
        legacy = {"task_id":t["task_id"], "decisions":[{"proposal_id":t["original_proposals"][0]["proposal_id"],
            "action":"keep", "reason":"Historical compatibility", "replacements":[],
            "primary_proposition":{"atom_id":"a", "quote":"Rule X."}}]}
        with self.assertRaises(Exception): normalize(envelope("submit_revision", legacy),t,"R1",1,["a"])
        self.assertFalse(RepairSession(t,"R1").call_tool("submit_revision",legacy)["ok"])
        self.assertTrue(RepairSession(t,"R1",legacy_offline=True).call_tool("submit_revision",legacy)["ok"])
        with tempfile.TemporaryDirectory() as root:
            r=self.run_local(manifest_fixture(),"R1",root,MockAdapter({"*":[envelope("submit_revision",legacy)]}))
            self.assertEqual("failed",r["status"])
            self.assertIsNone(r["tasks"][0]["session"]["revision"])

    def test_uncertain_preservation_and_default_R2_one_request(self):
        m=manifest_fixture();t=m["tasks"][0]
        args=submit(t,"unresolved");args["decisions"][0]["needed_context"]=["attribution"]
        result=RepairSession(t,"R1").call_tool("submit_revision",args)
        self.assertTrue(result["ok"])
        revision=result["result"]
        self.assertEqual("repair-revision-v2",revision["schema_version"])
        self.assertEqual(t["original_proposals"],revision["original_proposals"])
        self.assertEqual("preserve_baseline",revision["preservation_decisions"][0]["decision"])
        self.assertEqual(["attribution"],revision["preservation_decisions"][0]["needed_context"])
        self.assertEqual([],revision["verified_replacements"])
        for arm in ("R1","R2"):
            with tempfile.TemporaryDirectory() as root:
                adapter=MockAdapter();r=self.run_local(m,arm,root,adapter)
                self.assertEqual("complete",r["status"]);self.assertEqual(1,adapter.calls)

    def test_defect_requires_exact_read_evidence_not_reason_or_absence_alone(self):
        t=task_fixture()
        for field in ("witnesses","defect_type","correction"):
            args=submit(t,"reject");del args["decisions"][0][field]
            self.assertFalse(RepairSession(t,"R1").call_tool("submit_revision",args)["ok"])
        for witness in ({"atom_id":"a","quote":"No support present"}, {"atom_id":"b","quote":"Unless Y."}):
            args=submit(t,"reject");args["decisions"][0]["witnesses"]=[witness]
            self.assertFalse(RepairSession(t,"R1").call_tool("submit_revision",args)["ok"])
        result=RepairSession(t,"R1").call_tool("submit_revision",submit(t,"reject"))
        self.assertTrue(result["ok"])
        v=result["result"]["verified_assessments"][0]
        self.assertFalse(v["defect_semantics_validated"])
        self.assertEqual("Rule X.",v["evidence_spans"][0]["quote"])

    def test_duplicate_requires_distinct_supported_retained_no_cycles_or_uncertain_anchor(self):
        t=task_fixture();other=copy.deepcopy(t["original_proposals"][0])
        other["proposal"]["claim"]="Second candidate";other["proposal_sha256"]=_hash(other["proposal"])
        other["proposal_id"]="proposal-"+other["proposal_sha256"];t["original_proposals"].append(other)
        args=submit(t,"reject");dup=args["decisions"][0]
        dup.update(defect_type="duplicate", retained_proposal_id=other["proposal_id"])
        supported=copy.deepcopy(submit(t)["decisions"][0]);supported["proposal_id"]=other["proposal_id"]
        args["decisions"].append(supported)
        self.assertTrue(RepairSession(t,"R1").call_tool("submit_revision",args)["ok"])
        for anchor in (dup["proposal_id"],"foreign"):
            bad=copy.deepcopy(args);bad["decisions"][0]["retained_proposal_id"]=anchor
            self.assertFalse(RepairSession(t,"R1").call_tool("submit_revision",bad)["ok"])
        bad=copy.deepcopy(args);bad["decisions"][1]={"proposal_id":other["proposal_id"],"verdict":"uncertain","reason":"Unclear"}
        self.assertFalse(RepairSession(t,"R1").call_tool("submit_revision",bad)["ok"])
        bad=copy.deepcopy(args);bad["decisions"][1]=copy.deepcopy(dup)
        bad["decisions"][1].update(proposal_id=other["proposal_id"],retained_proposal_id=dup["proposal_id"])
        self.assertFalse(RepairSession(t,"R1").call_tool("submit_revision",bad)["ok"])

    def test_prompt_independent_all_proposals_no_accepted_review_leak(self):
        t=task_fixture();t["review_oracle"]=[{"accepted":"secret accepted verdict"}]
        t["obligations"][0]["review_confirmation"]={"reason":"secret accepted verdict"}
        t["semantic_errors"]=[{"proposal_sha256":t["original_proposals"][0]["proposal_sha256"],"checks":{"attribution":"fail"},"reason":"Prior allegation"}]
        messages=initial_messages(t,"R1");data=json.loads(messages[1]["content"])
        self.assertNotIn("secret accepted verdict",json.dumps(messages))
        self.assertEqual("unverified_hypothesis",data["prior_reported_errors"][0]["status"])
        self.assertIn("EVERY original AU",messages[0]["content"])
        self.assertIn("Absence of support alone is NOT",messages[0]["content"])

    def test_actual_113d_supported_fixture_and_prior_false_reject_invalid(self):
        m=build_tasks(RUN,NEW,BASE/"outputs/source_store_v1",BASE/"outputs/plan04_sentence_atoms_v1")
        # Select source content, not case-specific runtime behavior or forced keep.
        quote="no written assessment on the basis of the factors set out in subparagraph 113(d)(i) or (ii) of the Act need be made"
        t=next(t for t in m["tasks"] if any(quote in a["quote"] for a in t["supplied_atom_catalog"]))
        atom=next(a for a in t["supplied_atom_catalog"] if quote in a["quote"] and any(r["start_char"]<=a["start_char"]+a["quote"].index(quote)<a["start_char"]+a["quote"].index(quote)+len(quote)<=r["end_char"] for r in t["raw_targets"]))
        selected=next(p for p in t["original_proposals"] if "113(d)" in p["proposal"]["claim"] and atom["atom_id"] in p["proposal"]["evidence_ref_ids"])
        decisions=[{"proposal_id":p["proposal_id"],"verdict":"uncertain","reason":"Independent review pending"} for p in t["original_proposals"]]
        d=next(d for d in decisions if d["proposal_id"]==selected["proposal_id"])
        d.update(verdict="supported",primary_proposition={"atom_id":atom["atom_id"],"quote":quote})
        args={"task_id":t["task_id"],"decisions":decisions}
        result=RepairSession(t,"R1").call_tool("submit_revision",args)
        self.assertTrue(result["ok"],result)
        self.assertEqual(t["original_proposals"],result["result"]["original_proposals"])
        bad=copy.deepcopy(args);d=next(d for d in bad["decisions"] if d["proposal_id"]==selected["proposal_id"])
        d.clear();d.update(proposal_id=selected["proposal_id"],verdict="defect_found",defect_type="evidence_support",reason="113(d) absent",correction={"action":"reject"})
        self.assertFalse(RepairSession(t,"R1").call_tool("submit_revision",bad)["ok"])
        prior=load(BASE/"outputs/plan12_validate_first_20261011/prior_all_reject.json")
        for row in prior["observations"]:
            args={"task_id":t["task_id"],"decisions":row["decisions"]}
            self.assertFalse(RepairSession(t,"R1").call_tool("submit_revision",args)["ok"])

    def test_zero_proposals_host_skip_preflight_resume_and_mixed_coverage(self):
        from knowledge_base.pipeline_v1.repair_agent.runtime import preflight
        m=manifest_fixture();m["tasks"][0]["original_proposals"]=[]
        with patch("knowledge_base.pipeline_v1.repair_agent.runtime.verify_manifest",return_value=True):
            p=preflight(m,"R2")
        self.assertEqual(0,p["max_attempts_required"]);self.assertEqual(0,p["worst_case_reserved_tokens"])
        for arm in ("R1","R2"):
            with tempfile.TemporaryDirectory() as root:
                a=MockAdapter();r=self.run_local(m,arm,root,a)
                self.assertEqual(0,a.calls);self.assertEqual("complete",r["status"])
                self.assertEqual("baseline_no_proposals",r["tasks"][0]["status"])
                self.assertIsNone(r["tasks"][0]["session"]["revision"])
                self.assertEqual({"valid":0,"selected":1,"validation_required":0,"no_proposals":1},r["revision_coverage"])
                self.assertEqual("no_validation_required",r["revision_status"])
                self.assertEqual("semantic_review_pending",r["semantic_status"])
                resumed=MockAdapter();self.run_local(m,arm,root,resumed);self.assertEqual(0,resumed.calls)
        m=manifest_fixture(2);m["tasks"][0]["original_proposals"]=[]
        with tempfile.TemporaryDirectory() as root:
            a=MockAdapter();r=self.run_local(m,"R1",root,a)
            self.assertEqual(1,a.calls);self.assertEqual("all_valid_pending",r["revision_status"])
            self.assertEqual({"valid":1,"selected":2,"validation_required":1,"no_proposals":1},r["revision_coverage"])

    def test_assessment_transaction_final_validation_failure_never_commits(self):
        from knowledge_base.pipeline_v1.repair_agent import tools
        original_validate=tools.validate
        def failing(name,value):
            if name=="revision" and value.get("schema_version")=="repair-revision-v2":
                raise ValueError("injected_final_schema_failure")
            return original_validate(name,value)
        t=task_fixture();session=RepairSession(t,"R1")
        with patch.object(tools,"validate",side_effect=failing):
            result=session.call_tool("submit_revision",submit(t))
        self.assertFalse(result["ok"])
        self.assertIsNone(session.state["revision"])
        self.assertTrue(session.call_tool("submit_revision",submit(t))["ok"])

    def test_normalize_validates_defaults_other_kind_and_missing_essentials(self):
        from knowledge_base.pipeline_v1.repair_agent.wire import normalize
        t=task_fixture();replacement={"au":copy.deepcopy(t["original_proposals"][0]["proposal"]),"primary_proposition":{"atom_id":"a","quote":"Rule X."}}
        del replacement["au"]["other_kind"];del replacement["au"]["needs_context"]
        replacement["au"]["kind"]="other"
        args=submit(t,"replace",[replacement])
        with self.assertRaises(Exception):normalize(envelope("submit_revision",args),t,"R1",1,["a"])
        replacement["au"]["other_kind"]="Defined custom kind"
        full=normalize(envelope("submit_revision",submit(t,"replace",[replacement])),t,"R1",1,["a"])
        au=full["tool_calls"][0]["arguments"]["decisions"][0]["correction"]["replacements"][0]["au"]
        self.assertEqual([],au["needs_context"])
        self.assertTrue(RepairSession(t,"R1").call_tool("submit_revision",full["tool_calls"][0]["arguments"])["ok"])

    def test_prepare_forces_all_verdict_branches_and_defect_corrections(self):
        from knowledge_base.pipeline_v1.repair_agent.probe import run_probe
        with tempfile.TemporaryDirectory() as root:
            with patch("knowledge_base.pipeline_v1.repair_agent.adapter.complete_job",side_effect=AssertionError("No remote")):
                result=run_probe(Path(root))
            self.assertEqual(8,len(result["cases"]));self.assertEqual(0,result["cost_summary"]["attempts"])
            for name,verdict in (("supported_witness","supported"),("uncertain","uncertain"),("replace_types","defect_found"),("defect_reject","defect_found")):
                payload=load(Path(root)/(name+".payload.json"))
                self.assertIn(verdict,payload["ebnf"])
                for other in {"supported","uncertain","defect_found"}-{verdict}:self.assertNotIn(other,payload["ebnf"])
                self.assertNotIn("response_format",payload)



if __name__ == "__main__":
    unittest.main()
