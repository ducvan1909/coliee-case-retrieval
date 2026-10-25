from __future__ import annotations
import copy,hashlib,json,shutil,tempfile,unittest
from pathlib import Path
from jsonschema import Draft202012Validator

from knowledge_base.pipeline_v1.analysis_regions import AnalysisRegionError,RegionRenderError,build_analysis_regions,build_case_workload,load_and_validate_region_build,render_region,validate_analysis_workload
from knowledge_base.pipeline_v1.context_hints import run_context_hint_rules
from knowledge_base.pipeline_v1.sentence_atoms import segment_case
from knowledge_base.pipeline_v1.sentence_atoms.segmenter import canonical_hash
from knowledge_base.pipeline_v1.sidecars import run_sidecar_workers
from knowledge_base.pipeline_v1.structural_prepass import parse_source

P=Path(__file__).resolve().parents[1]
def load(name):return json.loads((P/"policies"/name).read_text(encoding="utf-8"))
SB,SA,SC,CH,AR=[load(x) for x in ("sourceblock_policy.v1.json","sentence_atom_policy.v1.json","sidecar_policy.v1.json","context_hint_policy.v1.json","analysis_region_policy.v1.json")]

class Plan07Tests(unittest.TestCase):
    def make(self,text,policy=None):
        sh=hashlib.sha256(text.encode()).hexdigest();blocks=parse_source(text=text,case_id="000001",source_hash=sh,policy=SB);atoms=segment_case(text,blocks,SA);sidecars=run_sidecar_workers(text,blocks,atoms,SC,canonical_hash(SC));hints=run_context_hint_rules(text,blocks,atoms,sidecars,CH,canonical_hash(CH));pol=policy or AR;value=build_case_workload(text,blocks,atoms,sidecars,hints,pol);return blocks,atoms,sidecars,hints,value,pol

    def fixture(self):
        report=json.loads((P/"reports/plan07_analysis_region_validation.latest.json").read_text(encoding="utf-8"));original=Path(report["outputs"]["output_root"]);temp=tempfile.TemporaryDirectory();root=Path(temp.name);manifest=json.loads(Path(report["outputs"]["build_manifest"]).read_text(encoding="utf-8"))
        for row in manifest["cases"]:
            dst=root/row["artifact_ref"];dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(original/row["artifact_ref"],dst)
        mp=root/"analysis_region_build_manifest.json";mp.write_text(json.dumps(manifest),encoding="utf-8")
        kwargs={"manifest_path":mp,"source_store":report["inputs"]["source_store"],"plan03_report":report["inputs"]["plan03_report"],"plan04_report":report["inputs"]["plan04_report"],"plan05_report":report["inputs"]["plan05_report"],"plan06_report":report["inputs"]["plan06_report"],"sourceblock_policy":P/"policies/sourceblock_policy.v1.json","sentence_policy":P/"policies/sentence_atom_policy.v1.json","sidecar_policy":P/"policies/sidecar_policy.v1.json","context_hint_policy":P/"policies/context_hint_policy.v1.json","region_policy":report["inputs"]["policy"]}
        return temp,root,manifest,kwargs

    def test_schema_and_checked_in_kos5_coverage(self):
        schema=json.loads((P/"contracts/analysis_region.v1.json").read_text(encoding="utf-8"));Draft202012Validator.check_schema(schema)
        report=json.loads((P/"reports/plan07_analysis_region_validation.latest.json").read_text(encoding="utf-8"));s=report["summary"]
        self.assertEqual((s["block_count"],s["content_block_count"],s["primary_target_count"]),(431,369,369));self.assertEqual(s["empty_content_structural_only_count"],1);self.assertEqual((s["slice_count"],s["work_item_count"]),(10,374));self.assertEqual(s["hint_disposition_count"],28);self.assertEqual(sum(s["hint_disposition_counts"].values()),28);self.assertEqual(sum(s["hint_target_eligibility_counts"].values()),28);self.assertTrue(all(report["gates"].values()))

    def test_every_content_block_targeted_and_structural_roles_audited(self):
        blocks,_,_,_,value,_=self.make("HEADING\n[1]\nContent.\n<FRAGMENT_SUPPRESSED>\n")
        eligible={x["block_id"] for x in value["block_roles"] if x["eligible"]};self.assertEqual(eligible,{x["parent_block_id"] for x in value["targets"]});self.assertTrue(all(x["reason"] for x in value["block_roles"] if not x["eligible"]))

    def test_long_block_slices_cover_content_and_oversized_atom_is_preserved(self):
        policy=copy.deepcopy(AR);policy["slice"]["max_chars"]=100
        text="[1]\n"+("a"*250)+"\n";blocks,atoms,sidecars,hints,value,pol=self.make(text,policy);target=value["targets"][0];self.assertEqual(target["mode"],"sliced");self.assertEqual(len(value["slices"]),1);self.assertTrue(value["slices"][0]["oversized_atom"]);self.assertIn("oversized_atom_preserved",value["slices"][0]["stop_reasons"]);validate_analysis_workload(value,text,blocks,atoms,sidecars,hints,pol)

    def test_slice_gap_overlap_duplicate_and_missing_target_rejected(self):
        policy=copy.deepcopy(AR);policy["slice"]["max_chars"]=80;text="[1]\n"+("First sentence. "*20)+"\n";blocks,atoms,sidecars,hints,value,pol=self.make(text,policy)
        self.assertGreater(len(value["slices"]),1)
        for mutation in ("gap","overlap","duplicate","missing"):
            bad=copy.deepcopy(value)
            if mutation=="gap":bad["slices"][1]["span"]["start_char"]+=1
            elif mutation=="overlap":bad["slices"][1]["span"]["start_char"]-=1
            elif mutation=="duplicate":bad["batches"][0]["work_items"].append(copy.deepcopy(bad["batches"][0]["work_items"][0]))
            else:bad["batches"][0]["work_items"].pop()
            with self.subTest(mutation=mutation),self.assertRaises(AnalysisRegionError):validate_analysis_workload(bad,text,blocks,atoms,sidecars,hints,pol)

    def test_sliced_target_is_not_split_across_a_batch_or_region_boundary(self):
        policy=copy.deepcopy(AR);policy["slice"]["max_chars"]=80;policy["batch"]["max_target_items"]=1
        text="[1]\n"+("First sentence. "*20)+"\n[2]\nSecond target.\n"
        blocks,atoms,sidecars,hints,value,pol=self.make(text,policy);target=value["targets"][0]
        self.assertGreater(len(target["slice_ids"]),1)
        batches=[b for b in value["batches"] if any(w["target_id"]==target["target_id"] for w in b["work_items"])]
        self.assertEqual(len(batches),1)
        self.assertEqual({w["target_id"] for w in batches[0]["work_items"]},{target["target_id"]})
        for arm in ("P2a","P2b"):
            regions=[r for r in value["regions"] if r["arm"]==arm and target["target_id"] in r["target_ids"]]
            self.assertEqual(len(regions),1)
        validate_analysis_workload(value,text,blocks,atoms,sidecars,hints,pol)

    def test_context_never_overlaps_target_and_duplicate_candidates_are_merged(self):
        text="[1]\nFirst.\n[2]\nAs noted above, second.\n[3]\nThird.\n";blocks,atoms,sidecars,hints,value,pol=self.make(text)
        for region in value["regions"]:
            for c in region["context_refs"]:
                self.assertFalse(any(c["span"]["start_char"]<t["end_char"] and c["span"]["end_char"]>t["start_char"] for t in region["primary_spans"]))
            spans=[(x["span"]["start_char"],x["span"]["end_char"]) for x in region["context_refs"]];self.assertEqual(len(spans),len(set(spans)))

    def test_paired_arms_share_exact_base_source_render_order(self):
        text="".join(f"[{i}]\nOrdinary paragraph {i}.\n" for i in range(1,5))+"[5]\nAs noted above, final paragraph.\n";_,_,_,_,value,_=self.make(text)
        a={r["batch_id"]:r for r in value["regions"] if r["arm"]=="P2a"};b={r["batch_id"]:r for r in value["regions"] if r["arm"]=="P2b"}
        self.assertEqual(set(a),set(b))
        for bid in a:
            self.assertEqual(a[bid]["render_items"],b[bid]["render_items"]);self.assertEqual(a[bid]["render_order"],b[bid]["render_order"]);self.assertEqual(a[bid]["included_hint_ids"],[])

    def test_candidate_structural_relation_is_not_accepted_context(self):
        text='[1]\nThe witness said "unfinished\n[2]\nContinuation.\n';_,_,sidecars,_,value,_=self.make(text);candidate={r["relation_id"] for r in sidecars["relations"] if r["status"]=="candidate"}
        used={rid for r in value["regions"] for c in r["context_refs"] for rid in c["source_relation_ids"]};self.assertFalse(candidate&used)

    def test_fixed_cap_exhaustion_keeps_targets_and_records_reason(self):
        policy=copy.deepcopy(AR);policy["region"]["max_context_chars"]=5;policy["region"]["max_context_spans"]=1
        text="".join(f"[{i}]\nParagraph number {i} has enough context.\n" for i in range(1,7));_,_,_,_,value,_=self.make(text,policy)
        self.assertTrue(any("context_cap_exhausted" in r["stop_reasons"] for r in value["regions"]));expected={w["work_item_id"] for b in value["batches"] for w in b["work_items"]}
        for arm in ("P2a","P2b"):
            actual={x.removeprefix("target:") for r in value["regions"] if r["arm"]==arm for x in r["render_order"] if x.startswith("target:")};self.assertEqual(actual,expected)

    def test_renderer_is_on_demand_marked_and_rejects_source_or_order_mutation(self):
        text="[1]\nFirst.\n[2]\nSecond.\n";_,_,_,_,value,_=self.make(text);region=value["regions"][0];rendered=render_region(text,region);self.assertIn("<TARGET",rendered);self.assertNotIn("source_text",json.dumps(value))
        with self.assertRaises(RegionRenderError):render_region(text+"x",region)
        bad=copy.deepcopy(region);bad["render_order"]=list(reversed(bad["render_order"]))
        with self.assertRaises(RegionRenderError):render_region(text,bad)

    def test_workload_mutations_source_dependency_metrics_fingerprint_and_order_rejected(self):
        text="[1]\nFirst.\n[2]\nSecond.\n";blocks,atoms,sidecars,hints,value,pol=self.make(text)
        mutations=[]
        b=copy.deepcopy(value);b["dependencies"]["context_hint_cache_key"]="0"*64;mutations.append(b)
        b=copy.deepcopy(value);b["regions"][0]["metrics"]["rendered_chars"]+=1;mutations.append(b)
        b=copy.deepcopy(value);b["regions"][0]["fingerprint"]="0"*64;mutations.append(b)
        b=copy.deepcopy(value);b["regions"][0]["render_order"].reverse();mutations.append(b)
        for bad in mutations:
            with self.assertRaises(AnalysisRegionError):validate_analysis_workload(bad,text,blocks,atoms,sidecars,hints,pol)
        with self.assertRaises(AnalysisRegionError):validate_analysis_workload(value,text+"x",blocks,atoms,sidecars,hints,pol)

    def test_missing_or_wrong_context_hint_reference_is_rejected(self):
        text="".join(f"[{i}]\nOrdinary paragraph {i}.\n" for i in range(1,5))+"[5]\nAs noted above, final paragraph.\n";blocks,atoms,sidecars,hints,value,pol=self.make(text)
        used=[h for r in value["regions"] if r["arm"]=="P2b" for h in r["included_hint_ids"]];self.assertTrue(used)
        missing=copy.deepcopy(hints);missing["hints"]=[h for h in missing["hints"] if h["hint_id"]!=used[0]]
        with self.assertRaises(AnalysisRegionError):validate_analysis_workload(value,text,blocks,atoms,sidecars,missing,pol)
        wrong=copy.deepcopy(hints);hint=next(h for h in wrong["hints"] if h["hint_id"]==used[0]);hint["related_spans"][0]["start_char"]+=1
        with self.assertRaises(AnalysisRegionError):validate_analysis_workload(value,text,blocks,atoms,sidecars,wrong,pol)

    def test_hint_disposition_ledger_is_exactly_once_and_mutation_rejected(self):
        text="".join(f"[{i}]\nOrdinary paragraph {i}.\n" for i in range(1,5))+"[5]\nAs noted above, final paragraph.\n";blocks,atoms,sidecars,hints,value,pol=self.make(text);ids=[x["hint_id"] for x in value["hint_dispositions"]]
        self.assertEqual(len(ids),len(set(ids)));self.assertEqual(set(ids),{x["hint_id"] for x in hints["hints"]})
        for mutation in ("missing","duplicate","wrong_disposition"):
            bad=copy.deepcopy(value)
            if mutation=="missing":bad["hint_dispositions"].pop()
            elif mutation=="duplicate":bad["hint_dispositions"].append(copy.deepcopy(bad["hint_dispositions"][0]))
            else:bad["hint_dispositions"][0]["disposition"]="cap_dropped"
            with self.subTest(mutation=mutation),self.assertRaises(AnalysisRegionError):validate_analysis_workload(bad,text,blocks,atoms,sidecars,hints,pol)

    def test_build_reader_recomputes_summary_and_rejects_unsafe_missing_or_corrupt_refs(self):
        temp,root,manifest,kwargs=self.fixture()
        try:
            _,checks=load_and_validate_region_build(**kwargs);self.assertEqual(checks["summary"]["primary_target_count"],369)
            bad=copy.deepcopy(manifest);bad["summary"]["primary_target_count"]+=1;kwargs["manifest_path"].write_text(json.dumps(bad),encoding="utf-8")
            with self.assertRaises(AnalysisRegionError):load_and_validate_region_build(**kwargs)
            bad=copy.deepcopy(manifest);bad["cases"][0]["artifact_ref"]="../escape.json";kwargs["manifest_path"].write_text(json.dumps(bad),encoding="utf-8")
            with self.assertRaises(AnalysisRegionError):load_and_validate_region_build(**kwargs)
            bad=copy.deepcopy(manifest);kwargs["manifest_path"].write_text(json.dumps(bad),encoding="utf-8");artifact=root/bad["cases"][0]["artifact_ref"];artifact.write_text('{"broken":',encoding="utf-8")
            with self.assertRaises(AnalysisRegionError):load_and_validate_region_build(**kwargs)
        finally:temp.cleanup()

    def test_build_refuses_corrupt_current_cache_instead_of_reusing(self):
        temp,root,manifest,kwargs=self.fixture()
        try:
            manifest["summary"]["primary_target_count"]+=1;kwargs["manifest_path"].write_text(json.dumps(manifest),encoding="utf-8");report=json.loads((P/"reports/plan07_analysis_region_validation.latest.json").read_text(encoding="utf-8"))
            with self.assertRaises(AnalysisRegionError) as cm:build_analysis_regions(source_store=report["inputs"]["source_store"],source_manifest=report["inputs"]["source_manifest"],plan03_report=report["inputs"]["plan03_report"],plan04_report=report["inputs"]["plan04_report"],plan05_report=report["inputs"]["plan05_report"],plan06_report=report["inputs"]["plan06_report"],plan06_independent_report=report["inputs"]["plan06_independent_report"],sourceblock_policy=P/"policies/sourceblock_policy.v1.json",sentence_policy=P/"policies/sentence_atom_policy.v1.json",sidecar_policy=P/"policies/sidecar_policy.v1.json",context_hint_policy=P/"policies/context_hint_policy.v1.json",region_policy=report["inputs"]["policy"],output_root=root,audit_path=root/"audit.html")
            self.assertEqual(cm.exception.code,"cache_validation_failed")
        finally:temp.cleanup()

if __name__=="__main__":unittest.main()
