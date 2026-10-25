from __future__ import annotations
import argparse,json,sys
from pathlib import Path
from .build import build_context_hints
P=Path(__file__).resolve().parents[1]
def main():
    a=argparse.ArgumentParser(description="Build deterministic KOS-5 ContextHints")
    a.add_argument("--source-store",type=Path,default=P/"outputs/source_store_v1");a.add_argument("--source-manifest",type=Path,default=P/"manifests/calibration_manifest.v1.json");a.add_argument("--plan03-report",type=Path,default=P/"reports/plan03_structural_validation.latest.json");a.add_argument("--plan04-report",type=Path,default=P/"reports/plan04_sentence_atom_validation.latest.json");a.add_argument("--plan05-report",type=Path,default=P/"reports/plan05_sidecar_validation.latest.json");a.add_argument("--plan05-independent-report",type=Path,default=P/"evaluation/plan05_independent_evaluation.md")
    a.add_argument("--sourceblock-policy",type=Path,default=P/"policies/sourceblock_policy.v1.json");a.add_argument("--sentence-policy",type=Path,default=P/"policies/sentence_atom_policy.v1.json");a.add_argument("--sidecar-policy",type=Path,default=P/"policies/sidecar_policy.v1.json");a.add_argument("--policy",type=Path,default=P/"policies/context_hint_policy.v1.json");a.add_argument("--output",type=Path,default=P/"outputs/plan06_context_hints_v1");a.add_argument("--report",type=Path,default=P/"reports/plan06_context_hint_validation.latest.json");a.add_argument("--audit",type=Path,default=P/"reports/plan06_context_hint_audit.html");args=a.parse_args()
    report=build_context_hints(source_store=args.source_store,source_manifest=args.source_manifest,plan03_report=args.plan03_report,plan04_report=args.plan04_report,plan05_report=args.plan05_report,plan05_independent_report=args.plan05_independent_report,sourceblock_policy=args.sourceblock_policy,sentence_policy=args.sentence_policy,sidecar_policy=args.sidecar_policy,policy_path=args.policy,output_root=args.output,audit_path=args.audit)
    args.report.parent.mkdir(parents=True,exist_ok=True);temp=args.report.with_suffix(args.report.suffix+".tmp");temp.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8");temp.replace(args.report);print(f"PLAN06 {report['status'].upper()} - report: {args.report.resolve()}");return 0 if report["status"]=="pass" else 1
if __name__=="__main__":sys.exit(main())
