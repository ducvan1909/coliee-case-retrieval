"""Source-grounded GPT-6.1 Sol decisions for the fixed first R3 batch.

Not an automatic semantic classifier. Decisions below were made by the model
after opening each exact source target and its neighboring raw context.
Run once, sequentially; any validation error stops the batch.
"""
import copy
from .au_gold.core import atomic_write, exact_span, load_json, model_review_trace
from .au_gold.remediation import ROOT, checkpoint_amendment, checkpoint_risk_review, dependencies, digest, registry, scan_attribution_risks, validate_risk_review

DECISIONS = [
 ('keep','Paragraph 10 expressly applies the reasonableness standard to this review using Thus; Board is the object of review, not the speaker. Claim and standard_of_review are supported.'),
 ('keep','Paragraph 16 says I remain of the view and in my opinion. The danger qualification is expressly adopted by the current court; Court of Appeal identifies the surrounding exceptional-circumstances doctrine, not a competing speaker.'),
 ('keep','Paragraph 34 expressly says I am of the view that the Board erred. Paragraphs 33 and 35 connect the documentary omission to allowing judicial review. Board is the criticized decision-maker, not the holding speaker.'),
 ('amendment','Paragraph 32 states an evidentiary/procedural duty, qualified by no obligation to defer to the Special Rapporteur general conclusions. Original holding kind and absent limit witness obscure that qualification. Preserve current-court voice, record procedural_rule and exact limit.'),
 ('keep','Paragraph 33 contrasts the Board view with its failure to mention the complaint and expressly says I note its paradoxical reliance on an ineffective commission. Paragraph 34 confirms the court finding of error; the submission cue describes a filed complaint, not party argument.'),
 ('keep','Paragraph 29 first states that the Board did not address contrary portions of a document. Following according-to passages illustrate the omitted evidence; the claim does not promote those statistics to independent court findings. Paragraphs 28 and 34 establish the court critique.'),
 ('amendment','Paragraph 28 formulates a general reasons-giving rule for contradictory evidence, not the present case disposition. Set procedural_rule and record its explicit triggering condition; current_court is supported by This Court has consistently held.'),
 ('keep','Paragraph 14 quotes the appellate rule then expressly draws the current court conclusion beginning Thus. The claim matches that conclusion and does not claim the court found actual protection effective. Preserve current_court attribution.'),
 ('amendment','Paragraph 15 expressly reports what the Court of Appeal expounded and cited cases teach. Unlike paragraph 14 it contains no separate Thus adoption sentence. Record cited_court attribution with exact reporting witness, developed-democracy condition, and exceptional-circumstances exception; retain procedural_rule.'),
 ('unresolved','Paragraph 27 contrasts the Board conclusion with abundant contrary evidence. It is the current court evidentiary appraisal, not Board speech; however the extracted claim is case-specific evidence description and does not clearly establish a reusable holding. Adjacent paragraphs 26 and 28 supply different rules. Abstain on AU eligibility rather than force holding or hard-negative.'),
]

def main():
    queue=scan_attribution_risks()
    items=queue['items'][:10]
    if len(items)!=10 or any(x['status']!='pending_model_review' for x in items):
        raise RuntimeError('Fixed first-ten batch is not entirely pending; inspect checkpoints before resuming')
    reviewer={'source_type':'model','reviewer_id':'p09-r3-first10-gpt-6.1-sol','model':'gpt-6.1-sol'}
    originals={str(p):digest(p) for p in (ROOT/'model_proposals').rglob('*.json')}
    results=[]
    for index,(item,(outcome,reason)) in enumerate(zip(items,DECISIONS),1):
        packet,source,_=dependencies(ROOT,item['case_id']) # open_source, preserving CRLF
        task=next(t for t in packet['tasks'] if t['target_id']==item['target_id'])
        a,b=task['target_span']['start_char'],task['target_span']['end_char']
        target=exact_span(source,item['case_id'],item['source_hash'],a,b)
        context=exact_span(source,item['case_id'],item['source_hash'],max(0,a-500),min(len(source),b+500))
        def witness(text):
            start=source.index(text,a,b)
            return exact_span(source,item['case_id'],item['source_hash'],start,start+len(text))
        aid=None
        if outcome!='keep':
            proposal=load_json(ROOT/'model_proposals'/item['case_id']/(item['proposal_id']+'.json'))
            replacement=copy.deepcopy(next(r for r in proposal['target_reviews'] if r['target_id']==item['target_id']))
            au=replacement['authority_units'][0]
            au['provenance']={'source_type':'model','producer_id':'model:gpt-6.1-sol','prompt_version':'p09-r3-source-review-v1'}
            if index==4:
                au['kind']='procedural_rule'
                au['claim_text']='The Board must address relevant contradictory evidence, but need not defer to the Special Rapporteur general conclusions.'
                au['limit_spans']=[witness("While the Board is not required to defer to the Special Rapporteur's general conclusions")]
            elif index==7:
                au['kind']='procedural_rule'
                au['condition_spans']=[witness('where there is contradictory evidence before the Board')]
            elif index==9:
                au['attributions']=[{'role':'proposition','speaker':'cited_court','evidence_span':witness('The Court of Appeal expounded upon the nature of the burden imposed upon claimants when attempting to rebut the presumption of state protection')}]
                au['condition_spans']=[witness('in the case of a developed democracy')]
                au['exception_spans']=[witness('will be exempted from his obligation to seek state protection only in the event of exceptional circumstances')]
            elif index==10:
                replacement.update(authority_units=[],hard_negative=None,model_outcome='unresolved',unresolved_reasons=[reason])
            replacement['notes']=replacement.get('notes',[])+[reason]
            old_trace=replacement['review_trace']
            replacement['review_trace']=model_review_trace(task,source,item['source_hash'],replacement)
            for k in ('region_id','region_fingerprint'):replacement['review_trace'][k]=old_trace[k]
            fid=f'P09-R3-{index:02d}'
            aid=f'p09-r3-first10-{index:02d}-gpt61sol-v1'
            finding={'finding_id':fid,'severity':'moderate','status':'amended_pending_independent_audit','case_id':item['case_id'],'target_id':item['target_id'],'source_hash':item['source_hash'],'proposal_id':item['proposal_id'],'proposal_sha256':item['proposal_sha256'],'error_types':['kind_or_field_witness' if index!=10 else 'au_eligibility_uncertain'],'evidence_span':target,'reason':reason}
            reg=registry()
            if any(x['finding_id']==fid for x in reg['findings']):raise RuntimeError('finding already exists')
            reg['findings'].append(finding);atomic_write(ROOT/'semantic_defect_registry.json',reg)
            amendment={'artifact_type':'AUModelAmendment','schema_version':'au-model-amendment-v1','amendment_id':aid,'finding_id':fid,'supersedes_proposal_id':item['proposal_id'],'supersedes_proposal_sha256':item['proposal_sha256'],'case_id':item['case_id'],'target_id':item['target_id'],'source_hash':item['source_hash'],'reviewer':reviewer,'reason':reason,'replacement_review':replacement,'context_spans':[context],'status':'model_reviewed_pending_independent_audit'}
            checkpoint_amendment(amendment)
        review={k:item[k] for k in ('proposal_id','proposal_sha256','case_id','source_hash','target_id','au_id')}
        review.update(artifact_type='Plan09AttributionRiskReview',review_id=f'p09-r3-first10-{index:02d}-gpt61sol-v1',reviewer=reviewer,outcome=outcome,reason=reason,target_span=target,context_spans=[context],amendment_id=aid,semantic_gold=False)
        checks=checkpoint_risk_review(review)
        validate_risk_review(load_json(ROOT/'risk_reviews'/(review['review_id']+'.json')))
        results.append({**checks,'outcome':outcome,'target_id':item['target_id'],'amendment_id':aid})
        print(f'PASS item={index:02d} outcome={outcome} target={item["target_id"]}',flush=True)
    if originals!={str(p):digest(p) for p in (ROOT/'model_proposals').rglob('*.json')}:raise RuntimeError('original proposal bytes changed')
    queue=scan_attribution_risks()
    report={'artifact_type':'Plan09R3FirstTenValidation','semantic_gold':False,'semantic_pass':False,'model':'gpt-6.1-sol','review_count':10,'original_proposals_unchanged':True,'pending_before':49,'pending_after':queue['pending_model_review_count'],'results':results}
    atomic_write(ROOT/'remediation_r3_first10_validation.json',report)
    print(f'PASS reviewed=10 pending={report["pending_after"]} report={ROOT / "remediation_r3_first10_validation.json"}')

if __name__=='__main__':main()
