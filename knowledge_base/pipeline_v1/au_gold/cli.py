from __future__ import annotations
import argparse,html,json
from pathlib import Path
from ..source_contract import open_source
from .build import build_plan09,checkpoint_model_proposal
from .core import atomic_write,compare_submissions,create_adjudication_template,load_json,lock_gold,lock_silver,select_few_shot,validate_adjudication,validate_model_proposal,validate_submission
from .scoring import score_predictions

P=Path(__file__).resolve().parents[1]
DEFAULT_OUT=P/"outputs/plan09_au_gold_v1"

def defaults():
    p7=load_json(P/"reports/plan07_analysis_region_validation.latest.json")
    return {"plan07_report":P/"reports/plan07_analysis_region_validation.latest.json","plan08_independent_report":P/"evaluation/plan08_independent_evaluation.md","source_store":p7["inputs"]["source_store"],"policy_path":P/"policies/au_annotation_policy.v1.json","split_registry":P/"manifests/split_registry.v1.json","hard_cases_path":P/"hard_cases.v1.json","output_root":DEFAULT_OUT,"report_path":P/"reports/plan09_au_gold_readiness.latest.json","repo_root":P.parents[1]}

def _packet(case_id,root=DEFAULT_OUT):
    manifest=load_json(Path(root)/"au_annotation_build_manifest.json");row=next(x for x in manifest["cases"] if x["case_id"]==case_id);return load_json(Path(root)/row["packet_ref"]),manifest

def main(argv=None):
    parser=argparse.ArgumentParser(prog="python -m knowledge_base.pipeline_v1.au_gold");sub=parser.add_subparsers(dest="command")
    sub.add_parser("build",help="create blank packets and readiness artifacts")
    r=sub.add_parser("render-task");r.add_argument("--case-id",required=True);r.add_argument("--target-id",required=True);r.add_argument("--output",required=True)
    v=sub.add_parser("validate-submission");v.add_argument("--submission",required=True);v.add_argument("--output",required=True)
    c=sub.add_parser("compare-submissions");c.add_argument("--submission-a",required=True);c.add_argument("--submission-b",required=True);c.add_argument("--output",required=True)
    a=sub.add_parser("create-adjudication");a.add_argument("--submission-a",required=True);a.add_argument("--submission-b",required=True);a.add_argument("--adjudicator-id",required=True);a.add_argument("--display-name",required=True);a.add_argument("--output",required=True)
    av=sub.add_parser("apply-adjudication");av.add_argument("--adjudication",required=True);av.add_argument("--submission-a",required=True);av.add_argument("--submission-b",required=True);av.add_argument("--output",required=True)
    mg=sub.add_parser("lock-gold");mg.add_argument("--packets",nargs="+",required=True);mg.add_argument("--submissions",nargs="+",required=True);mg.add_argument("--adjudications",nargs="+",required=True);mg.add_argument("--output",required=True)
    vm=sub.add_parser("validate-model-proposal");vm.add_argument("--proposal",required=True);vm.add_argument("--output",required=True)
    risk=sub.add_parser('scan-attribution-risks');risk.add_argument('--output',required=True)
    for name in ('validate-risk-review','checkpoint-risk-review','checkpoint-risk-review-revision'):
        risk_review=sub.add_parser(name);risk_review.add_argument('--review',required=True);risk_review.add_argument('--output',required=True)
    for name in ('validate-amendment','checkpoint-amendment'):
        amendment=sub.add_parser(name);amendment.add_argument('--amendment',required=True);amendment.add_argument('--output',required=True)
    cm=sub.add_parser("checkpoint-model-proposal",help="validate and atomically checkpoint one traced Terra batch");cm.add_argument("--proposal",required=True)
    ls=sub.add_parser("lock-silver");ls.add_argument("--packets",nargs="+",required=True);ls.add_argument("--proposals",nargs="+",required=True);ls.add_argument("--output",required=True)
    s=sub.add_parser("score");s.add_argument("--gold",required=True);s.add_argument("--predictions",required=True);s.add_argument("--output",required=True)
    fs=sub.add_parser("select-few-shot");fs.add_argument("--gold");fs.add_argument("--output",required=True)
    args=parser.parse_args(argv);command=args.command or "build";d=defaults();policy=load_json(d["policy_path"])
    if command in {'scan-attribution-risks','validate-amendment','checkpoint-amendment','validate-risk-review','checkpoint-risk-review','checkpoint-risk-review-revision'}:
        from .remediation import scan_attribution_risks,validate_amendment,checkpoint_amendment,validate_risk_review,checkpoint_risk_review,checkpoint_risk_review_revision
        if command=='scan-attribution-risks':value=scan_attribution_risks(DEFAULT_OUT)
        elif command=='validate-risk-review':value=validate_risk_review(load_json(args.review),DEFAULT_OUT)
        elif command=='checkpoint-risk-review':value=checkpoint_risk_review(load_json(args.review),DEFAULT_OUT)
        elif command=='checkpoint-risk-review-revision':value=checkpoint_risk_review_revision(load_json(args.review),DEFAULT_OUT)
        elif command=='validate-amendment':value=validate_amendment(load_json(args.amendment),DEFAULT_OUT)
        else:value=checkpoint_amendment(load_json(args.amendment),DEFAULT_OUT)
        atomic_write(args.output,value);print(f'written={args.output}');return 0
    if command=="build":report=build_plan09(**d);print(f"Plan 09 {report['overall_status']}: report={d['report_path']}");return 0
    if command=="checkpoint-model-proposal":
        value=checkpoint_model_proposal(proposal=load_json(args.proposal),output_root=d["output_root"],source_store=d["source_store"],policy=policy)
        print(f"checkpointed={value['proposal_ref']} reviewed_targets={value['reviewed_target_count']}");return 0
    if command=="render-task":
        packet,manifest=_packet(args.case_id);task=next(x for x in packet["tasks"] if x["target_id"]==args.target_id);text=open_source(manifest["source_store"],packet["case_id"],packet["source_hash"]);span=task["target_span"];a=max(0,span["start_char"]-1000);b=min(len(text),span["end_char"]+1000);Path(args.output).write_text("<!doctype html><meta charset='utf-8'><h1>"+html.escape(task["target_id"])+"</h1><h2>Exact target</h2><pre>"+html.escape(text[span["start_char"]:span["end_char"]])+"</pre><h2>Expanded source</h2><pre>"+html.escape(text[a:b])+"</pre>",encoding="utf-8");print(f"rendered={Path(args.output).resolve()}");return 0
    if command in {"validate-submission","compare-submissions","create-adjudication","apply-adjudication","validate-model-proposal"}:
        first=load_json(getattr(args,"submission",getattr(args,"submission_a",getattr(args,"proposal",None))));packet,manifest=_packet(first["case_id"]);text=open_source(manifest["source_store"],packet["case_id"],packet["source_hash"])
        if command=="validate-submission":value=validate_submission(first,packet,text,policy)
        elif command=="validate-model-proposal":value=validate_model_proposal(first,packet,text,policy)
        else:
            second=load_json(args.submission_b);disagreement=compare_submissions(first,second,packet,text,policy)
            if command=="compare-submissions":value=disagreement
            elif command=="create-adjudication":value=create_adjudication_template(packet,first,second,disagreement,args.adjudicator_id,args.display_name)
            else:value=load_json(args.adjudication);validate_adjudication(value,packet,first,second,disagreement,text,policy)
        atomic_write(args.output,value);print(f"written={Path(args.output).resolve()}");return 0
    if command in {"lock-gold","lock-silver"}:
        packets=[load_json(x) for x in args.packets];manifest=load_json(DEFAULT_OUT/"au_annotation_build_manifest.json");texts={p["case_id"]:open_source(manifest["source_store"],p["case_id"],p["source_hash"]) for p in packets}
        if command=="lock-gold":value=lock_gold(packets,[load_json(x) for x in args.submissions],[load_json(x) for x in args.adjudications],policy,texts)
        else:
            from .remediation import effective_proposals,registry,assert_lockable
            assert_lockable(registry(DEFAULT_OUT))
            effective={x['proposal_id']:x for x in effective_proposals(DEFAULT_OUT)}
            supplied=[load_json(x) for x in args.proposals]
            if any(x['proposal_id'] not in effective for x in supplied):raise ValueError('silver lock requires canonical proposals')
            value=lock_silver(packets,[effective[x['proposal_id']] for x in supplied],policy,texts)
    elif command=="score":
        gold=load_json(args.gold);pred=load_json(args.predictions);value=score_predictions(gold.get("authority_units",gold),pred.get("authority_units",pred),gold.get("hard_negatives",[]));value["evaluation_against"]="model_silver" if gold.get("artifact_type")=="LockedAUSilverSnapshot" else "human_gold"
    else:value=select_few_shot(load_json(args.gold) if args.gold else None)
    atomic_write(args.output,value);print(f"written={Path(args.output).resolve()}");return 0
