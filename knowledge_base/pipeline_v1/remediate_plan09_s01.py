"""Record P09-S01 quarantine and conservative model review, preserving originals."""
import copy
from .au_gold.core import atomic_write, load_json, exact_span, model_review_trace
from .au_gold.remediation import ROOT, dependencies, digest, checkpoint_amendment, scan_attribution_risks
from .au_gold.progress import build_progress

def main():
    root = ROOT
    proposal_path = root/'model_proposals/013948/terra-013948-aafb64c3e03c512941a071a8.json'
    original = load_json(proposal_path)
    tid = 'at-3f8c7b00587a03395a1070fa'
    packet, source, policy = dependencies(root, '013948')
    task = next(x for x in packet['tasks'] if x['target_id']==tid)
    previous = next(x for x in original['target_reviews'] if x['target_id']==tid)
    registry_path = root/'semantic_defect_registry.json'
    if not registry_path.exists():
        atomic_write(registry_path, {'artifact_type':'Plan09SemanticDefectRegistry','registry_version':'plan09-semantic-defects-v1','semantic_gold':False,'findings':[{'finding_id':'P09-S01','severity':'severe','status':'quarantined_pending_review','case_id':'013948','target_id':tid,'source_hash':original['source_hash'],'proposal_id':original['proposal_id'],'proposal_sha256':digest(proposal_path),'error_types':['speaker_attribution','unsupported_holding'],'evidence_span':previous['reviewed_span'],'reason':'Express party submission merged with following court-response heading and labelled holding/current_court.'}]})
    z = task['target_span']
    context = exact_span(source,'013948',original['source_hash'],max(0,z['start_char']-1800),min(len(source),z['end_char']+2500))
    review = copy.deepcopy(previous)
    review.update({'authority_units':[],'hard_negative':None,'model_outcome':'unresolved','unresolved_reasons':['Target combines an express Bayavuge submission with a court-response heading. Independent model review must decide whether the heading warrants a separate AU; the party submission cannot remain a current-court holding.'],'notes':['Raw source and adjacent paragraphs 30-43 reviewed using open_source.']})
    review['review_trace'] = model_review_trace(task,source,original['source_hash'],review)
    amendment = {'artifact_type':'AUModelAmendment','schema_version':'au-model-amendment-v1','amendment_id':'p09-s01-gpt6-unresolved-v1','finding_id':'P09-S01','supersedes_proposal_id':original['proposal_id'],'supersedes_proposal_sha256':digest(proposal_path),'case_id':'013948','target_id':tid,'source_hash':original['source_hash'],'reviewer':{'source_type':'model','reviewer_id':'codex-gpt6-remediation','model':'gpt-6'},'reason':'Party submission cannot be attributed to current court; preserve heading interpretation uncertainty for independent review.','replacement_review':review,'context_spans':[context],'status':'model_reviewed_pending_independent_audit'}
    if not (root/'model_amendments'/(amendment['amendment_id']+'.json')).exists():
        checks = checkpoint_amendment(amendment,root)
        atomic_write(root/'remediation_s01_validation.json',checks)
    atomic_write(root/'attribution_risk_queue.json',scan_attribution_risks(root))
    progress_path = root.parents[1]/'reports/plan09_model_silver_progress.latest.json'
    prior = load_json(progress_path)
    progress = build_progress(root,prior['blocker'])
    atomic_write(progress_path,progress)
    readiness_path = root.parents[1]/'reports/plan09_au_gold_readiness.latest.json'
    readiness = load_json(readiness_path)
    readiness['semantic_remediation'] = progress['semantic_remediation']
    for key in ('authority_unit_count','hard_negative_count','unresolved_target_count'):
        readiness['silver_readiness'][key] = progress[key]
    readiness['silver_readiness']['count_basis'] = 'effective_model_amendment_view'
    readiness['gates']['silver_ready'] = False
    readiness['gates']['plan10_allowed'] = False
    atomic_write(readiness_path,readiness)
    print(progress['semantic_remediation'])

if __name__=='__main__':main()
