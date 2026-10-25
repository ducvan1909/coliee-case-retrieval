from __future__ import annotations
import copy, hashlib, json, shutil, tempfile, unittest
from pathlib import Path

from knowledge_base.pipeline_v1.context_hints import ContextHintAPI, ContextHintError, ContextHintQueryError, build_context_hints, load_and_validate_context_hint_build, run_context_hint_rules, validate_context_hint_map
from knowledge_base.pipeline_v1.sentence_atoms import segment_case
from knowledge_base.pipeline_v1.sentence_atoms.segmenter import canonical_hash
from knowledge_base.pipeline_v1.sidecars import run_sidecar_workers
from knowledge_base.pipeline_v1.structural_prepass import parse_source

P = Path(__file__).resolve().parents[1]
SB = json.loads((P/"policies/sourceblock_policy.v1.json").read_text(encoding="utf-8"))
SA = json.loads((P/"policies/sentence_atom_policy.v1.json").read_text(encoding="utf-8"))
SC = json.loads((P/"policies/sidecar_policy.v1.json").read_text(encoding="utf-8"))
CH = json.loads((P/"policies/context_hint_policy.v1.json").read_text(encoding="utf-8"))


class Plan06Tests(unittest.TestCase):
    def make(self, text, faults=None, policy=None):
        sh=hashlib.sha256(text.encode()).hexdigest(); blocks=parse_source(text=text,case_id="000001",source_hash=sh,policy=SB); atoms=segment_case(text,blocks,SA); sidecars=run_sidecar_workers(text,blocks,atoms,SC,canonical_hash(SC)); pol=policy or CH; hints=run_context_hint_rules(text,blocks,atoms,sidecars,pol,canonical_hash(pol),faults); return blocks,atoms,sidecars,hints,pol

    def types(self, value): return [h["hint_type"] for h in value["hints"]]

    def build_fixture(self):
        report=json.loads((P/"reports/plan06_context_hint_validation.latest.json").read_text(encoding="utf-8")); original=Path(report["outputs"]["output_root"]); temp=tempfile.TemporaryDirectory(); root=Path(temp.name)
        manifest=json.loads(Path(report["outputs"]["build_manifest"]).read_text(encoding="utf-8"))
        for row in manifest["cases"]:
            destination=root/row["artifact_ref"]; destination.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(original/row["artifact_ref"],destination)
        manifest_path=root/"context_hint_build_manifest.json"; manifest_path.write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf-8")
        cap=root/"cap_dedup_ledger.jsonl"; events=root/"rule_event_ledger.jsonl"; shutil.copy2(report["outputs"]["cap_dedup_ledger"],cap); shutil.copy2(report["outputs"]["rule_event_ledger"],events)
        kwargs={"manifest_path":manifest_path,"cap_ledger_path":cap,"rule_event_ledger_path":events,"source_store":report["inputs"]["source_store"],"plan03_report":report["inputs"]["plan03_report"],"plan04_report":report["inputs"]["plan04_report"],"plan05_report":report["inputs"]["plan05_report"],"sourceblock_policy":P/"policies/sourceblock_policy.v1.json","sentence_policy":P/"policies/sentence_atom_policy.v1.json","sidecar_policy":P/"policies/sidecar_policy.v1.json","policy_path":report["inputs"]["policy"]}
        return temp,root,manifest,kwargs

    def test_unbalanced_quote_cross_block_and_balanced_quote_negative(self):
        _,_,_,open_map,_=self.make('[1]\nThe Court said "unfinished\n[2]\ncontinued words.\n')
        self.assertIn("open_quote",self.types(open_map)); self.assertIn("quote_continuation",self.types(open_map))
        _,_,_,closed,_=self.make('[1]\nThe Court said "finished".\n[2]\nNew sentence.\n')
        self.assertNotIn("open_quote",self.types(closed)); self.assertNotIn("quote_continuation",self.types(closed))

    def test_list_lead_in_requires_colon(self):
        _,_,_,yes,_=self.make("[1] The factors are:\n[2]\n(a) first factor\n")
        self.assertIn("open_list",self.types(yes))
        _,_,_,no,_=self.make("[1] The factors are stated.\n[2]\n(a) first factor\n")
        self.assertNotIn("open_list",self.types(no))

    def test_reference_true_cue_and_incidental_above_false_positive(self):
        _,_,_,yes,_=self.make("[1]\nFirst proposition.\n[2]\nAs noted above, it applies.\n")
        self.assertIn("reference_to_previous",self.types(yes))
        _,_,_,no,_=self.make("[1]\nFirst.\n[2]\nThe award is above ten dollars.\n")
        self.assertNotIn("reference_to_previous",self.types(no))

    def test_citation_continuation_boundary_and_first_block_unresolved(self):
        _,_,_,yes,_=self.make("[1]\nSmith v Jones, 2010 SCC 2.\n[2]\nIbid. at para. 4.\n")
        hint=next(h for h in yes["hints"] if h["hint_type"]=="citation_continuation"); self.assertEqual(hint["direction"],"previous"); self.assertEqual(hint["status"],"candidate")
        _,_,_,first,_=self.make("Ibid. at para. 4.\n")
        hint=next(h for h in first["hints"] if h["hint_type"]=="citation_continuation"); self.assertEqual(hint["status"],"unresolved"); self.assertEqual(hint["related_spans"],[])

    def test_speaker_same_different_absent_and_no_identity(self):
        _,_,_,same,_=self.make("[1]\nThe Court finds one.\n[2]\nThe Court concludes two.\n")
        h=[x for x in same["hints"] if x["hint_type"]=="speaker_continuity_candidate"]; self.assertEqual(len(h),1); self.assertNotIn('"speaker"',json.dumps(h))
        _,_,_,different,_=self.make("[1]\nThe applicant submits one.\n[2]\nThe Court concludes two.\n")
        self.assertNotIn("speaker_continuity_candidate",self.types(different))
        _,_,_,absent,_=self.make("[1]\nOrdinary one.\n[2]\nOrdinary two.\n")
        self.assertNotIn("speaker_continuity_candidate",self.types(absent))

    def test_heading_relation_does_not_create_hint_and_targets_preserved(self):
        blocks,_,_,value,_=self.make("ANALYSIS\n[1]\nOrdinary paragraph.\n")
        self.assertEqual(value["target_block_ids"],[b["block_id"] for b in blocks["blocks"]]); self.assertEqual(value["hints"],[])

    def test_cap_dedup_is_deterministic_and_records_drop(self):
        policy=copy.deepcopy(CH); policy["caps"]["max_hints_per_target"]=1
        _,_,_,value,_=self.make('[1]\nThe Court said "unfinished\n[2]\nAs noted above, continued.\n',policy=policy)
        self.assertEqual(value["post_policy_count"],2); self.assertGreater(value["pre_policy_count"],value["post_policy_count"]); self.assertTrue(any(x["reason"]=="target_hint_cap" for x in value["policy_ledger"]))

    def test_query_half_open_empty_touching_filters_and_estimate(self):
        _,_,_,value,_=self.make("[1]\nFirst.\n[2]\nAs noted above, second.\n")
        api=ContextHintAPI("[1]\nFirst.\n[2]\nAs noted above, second.\n",value); hint=value["hints"][0]; s=hint["target_span"]["start_char"]
        self.assertEqual(api.query_hints(start_char=s,end_char=s),[]); self.assertEqual(api.query_hints(start_char=0,end_char=s),[]); self.assertEqual(len(api.query_hints(start_char=s,end_char=s+1,hint_type="reference_to_previous",direction="previous",status="candidate")),1); self.assertGreater(api.estimate_additions()["unique_related_chars"],0)
        with self.assertRaises(ContextHintQueryError): api.query_hints(case_id="999999")

    def test_rule_failure_isolated_partial_rejected_by_default(self):
        blocks,atoms,sidecars,value,policy=self.make('[1]\nThe Court said "unfinished\n[2]\ncontinued.\n',{"quote_continuation"})
        self.assertEqual(value["run_status"],"partial"); self.assertTrue(value["hints"]); self.assertEqual(len(value["rule_events"]),1)
        with self.assertRaises(ContextHintError) as cm: validate_context_hint_map(value,'[1]\nThe Court said "unfinished\n[2]\ncontinued.\n',blocks,atoms,sidecars,policy)
        self.assertEqual(cm.exception.code,"partial_artifact")
        validate_context_hint_map(value,'[1]\nThe Court said "unfinished\n[2]\ncontinued.\n',blocks,atoms,sidecars,policy,allow_partial=True)

    def test_mutation_source_parent_policy_and_forbidden_field_rejected(self):
        text="[1]\nFirst.\n[2]\nAs noted above, second.\n"; blocks,atoms,sidecars,value,policy=self.make(text)
        validate_context_hint_map(value,text,blocks,atoms,sidecars,policy)
        with self.assertRaises(ContextHintError) as cm: validate_context_hint_map(value,text+"x",blocks,atoms,sidecars,policy)
        self.assertEqual(cm.exception.code,"source_hash_mismatch")
        bad=copy.deepcopy(value); bad["hints"][0]["status"]="unresolved"
        with self.assertRaises(ContextHintError): validate_context_hint_map(bad,text,blocks,atoms,sidecars,policy)
        bad=copy.deepcopy(value); bad["sourceblock_cache_key"]="0"*64
        with self.assertRaises(ContextHintError): validate_context_hint_map(bad,text,blocks,atoms,sidecars,policy)
        changed=copy.deepcopy(policy); changed["caps"]["max_hints_per_case"]-=1
        with self.assertRaises(ContextHintError): validate_context_hint_map(value,text,blocks,atoms,sidecars,changed)
        bad=copy.deepcopy(value); bad["hints"][0]["speaker"]="court"
        with self.assertRaises(ContextHintError): validate_context_hint_map(bad,text,blocks,atoms,sidecars,policy)

    def test_checked_in_kos5_report_and_schemas(self):
        from jsonschema import Draft202012Validator
        for name in ("context_hint.v1.json","context_hint_build_manifest.v1.json","context_hint_ledger_event.v1.json"):
            schema=json.loads((P/"contracts"/name).read_text(encoding="utf-8")); Draft202012Validator.check_schema(schema)
        report=json.loads((P/"reports/plan06_context_hint_validation.latest.json").read_text(encoding="utf-8"))
        self.assertEqual(report["status"],"pass"); self.assertEqual(report["summary"]["case_count"],5); self.assertEqual(report["summary"]["target_count"],431); self.assertEqual(report["metrics_not_reported"],["precision","recall","F1"])
        self.assertTrue(all(report["gates"].values()))

    def test_build_reader_recomputes_metrics_and_rejects_missing_or_unsafe_refs(self):
        temp,root,manifest,kwargs=self.build_fixture()
        try:
            _,checks=load_and_validate_context_hint_build(**kwargs); self.assertEqual(checks["totals"]["hint_count"],28); self.assertEqual(checks["totals"]["target_count"],431); self.assertEqual(checks["totals"]["repeated_proposed_chars"],978)
            for field,value in (("hint_count",999999),("target_count",999999),("post_policy_count",999999)):
                bad=copy.deepcopy(manifest); bad["cases"][0][field]=value; kwargs["manifest_path"].write_text(json.dumps(bad),encoding="utf-8")
                with self.subTest(field=field),self.assertRaises(ContextHintError) as cm: load_and_validate_context_hint_build(**kwargs)
                self.assertEqual(cm.exception.code,"manifest_metric_mismatch")
            bad=copy.deepcopy(manifest); bad["summary"]["hint_count"]+=1; kwargs["manifest_path"].write_text(json.dumps(bad),encoding="utf-8")
            with self.assertRaises(ContextHintError) as cm: load_and_validate_context_hint_build(**kwargs)
            self.assertEqual(cm.exception.code,"manifest_metric_mismatch")
            bad=copy.deepcopy(manifest); bad["cases"][0]["artifact_ref"]=bad["cases"][0]["artifact_ref"].replace("context_hint_map.json","missing_context_hint_map.json"); kwargs["manifest_path"].write_text(json.dumps(bad),encoding="utf-8")
            with self.assertRaises(ContextHintError): load_and_validate_context_hint_build(**kwargs)
            bad=copy.deepcopy(manifest); bad["cases"][0]["artifact_ref"]="../escape/context_hint_map.json"; kwargs["manifest_path"].write_text(json.dumps(bad),encoding="utf-8")
            with self.assertRaises(ContextHintError): load_and_validate_context_hint_build(**kwargs)
        finally: temp.cleanup()

    def test_build_reader_rejects_duplicate_missing_partial_and_corrupt_map(self):
        for mutation in ("duplicate","missing","partial","corrupt"):
            temp,root,manifest,kwargs=self.build_fixture()
            try:
                if mutation=="duplicate": manifest["cases"][1]=copy.deepcopy(manifest["cases"][0]); kwargs["manifest_path"].write_text(json.dumps(manifest),encoding="utf-8")
                elif mutation=="missing": manifest["cases"]=manifest["cases"][:-1]; kwargs["manifest_path"].write_text(json.dumps(manifest),encoding="utf-8")
                else:
                    artifact=root/manifest["cases"][0]["artifact_ref"]
                    if mutation=="partial":
                        value=json.loads(artifact.read_text(encoding="utf-8")); value["run_status"]="partial"; value["failed_rules"]=["open_quote"]; artifact.write_text(json.dumps(value),encoding="utf-8")
                    else: artifact.write_text('{"truncated":',encoding="utf-8")
                with self.subTest(mutation=mutation),self.assertRaises(ContextHintError): load_and_validate_context_hint_build(**kwargs)
            finally: temp.cleanup()

    def test_build_reader_rejects_malformed_missing_extra_and_wrong_type_ledgers(self):
        for mutation in ("malformed","missing","extra","wrong_type"):
            temp,root,manifest,kwargs=self.build_fixture()
            try:
                path=kwargs["cap_ledger_path"]
                if mutation=="malformed": path.write_text('{"truncated":\n',encoding="utf-8")
                elif mutation=="missing": path.write_text("",encoding="utf-8")
                elif mutation=="extra": path.write_text(path.read_text(encoding="utf-8")+path.read_text(encoding="utf-8").splitlines()[0]+"\n",encoding="utf-8")
                else:
                    row=json.loads(path.read_text(encoding="utf-8").splitlines()[0]); row["action"]=7; path.write_text(json.dumps(row)+"\n",encoding="utf-8")
                with self.subTest(mutation=mutation),self.assertRaises(ContextHintError): load_and_validate_context_hint_build(**kwargs)
            finally: temp.cleanup()

    def test_build_refuses_reuse_when_current_manifest_is_corrupt(self):
        temp,root,manifest,kwargs=self.build_fixture()
        try:
            manifest["cases"][0]["hint_count"]+=1; kwargs["manifest_path"].write_text(json.dumps(manifest),encoding="utf-8")
            report=json.loads((P/"reports/plan06_context_hint_validation.latest.json").read_text(encoding="utf-8"))
            with self.assertRaises(ContextHintError) as cm:
                build_context_hints(source_store=report["inputs"]["source_store"],source_manifest=report["inputs"]["source_manifest"],plan03_report=report["inputs"]["plan03_report"],plan04_report=report["inputs"]["plan04_report"],plan05_report=report["inputs"]["plan05_report"],plan05_independent_report=report["inputs"]["plan05_independent_report"],sourceblock_policy=P/"policies/sourceblock_policy.v1.json",sentence_policy=P/"policies/sentence_atom_policy.v1.json",sidecar_policy=P/"policies/sidecar_policy.v1.json",policy_path=report["inputs"]["policy"],output_root=root,audit_path=root/"audit.html")
            self.assertEqual(cm.exception.code,"cache_validation_failed")
        finally: temp.cleanup()


if __name__=="__main__": unittest.main()
