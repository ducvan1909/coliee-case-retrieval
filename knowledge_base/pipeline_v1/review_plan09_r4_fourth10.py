"""Fourth frozen ten-target R4 batch; no independent semantic acceptance."""
from .au_gold.core import exact_span,model_review_trace
from .au_gold.r4_batch import run_batch
from .review_plan09_r4_first10 import PRODUCER,PROVENANCE
from .review_plan09_r4_second10 import RESERVATION

BATCH_ID='p09-r4-099980-fourth10-sol-v1'
DECISIONS=[
 ('hard_negative','procedural_history_only',None,None,'Paragraph 36 announces the application result and outlines the next analytical sections. It is a forward roadmap, not a separate reasoned authority proposition; do not import later grounds or formal judgment terms into this owner.'),
 ('hard_negative','procedural_history_only',None,None,'Paragraph 21 reports Commission transmittal letters telling affected servants about judicial review under FCA section 18.1. This is agency notification in procedural history, not a separate current-court interpretation of that statute; do not convert reported agency speech into current_court authority.'),
 ('positive','procedural_rule','Respect for a decision-maker choice of procedure is not a determinative criterion in assessing procedural fairness.',None,'Court directly states the Baker paragraph-27 criterion. Preserve not determinative: procedural choice remains a factor, not irrelevant. The nearby master-of-procedure discussion does not dispense with fair procedures.'),
 ('hard_negative','fact_only',None,None,'Paragraph 10 narrates DNR administrative investigation, intercepted emails and transmittal triggering this investigation. No adopted rule on interception legality or a legal duty to investigate is stated.'),
 ('hard_negative','fact_only',None,None,'Paragraph 115 describes possible employment/disciplinary consequences of sending this report to employers. This impact observation does not itself prescribe disciplinary action or endorse a legal power to discipline.'),
 ('positive','procedural_rule','In this investigation, if the new evidence was not provided to the applicant, the investigator should at least have sent another revised factual report incorporating Ms. Cousineau May 17, 2010 information.',"At the very least, in the absence of giving that new evidence to the applicant, the investigator should have, once again, sent a revised factual report that incorporated the new information provided by Ms. Cousineau on May 17, 2010.",'Current-court minimum fairness requirement. Retain the non-disclosure condition and date/new-information scope; direct provision of evidence is an alternative, so no unconditional revised-report duty. Exclude following Prejudice heading.'),
 ('unresolved',None,None,None,'Paragraph 35 starts with applicant requested jurisdiction issue and then court in my view characterization that it merits correct interpretation. Paragraph 93 expressly reserves a definitive jurisdiction/reasonableness opinion. Eligibility/kind of this non-final standard-of-review observation is uncertain; do not force it into a settled correctness standard or treat the entire mixed span as only party argument.'),
 ('hard_negative','fact_only',None,None,'Paragraph 135 describes employer notice and participation in this investigation. Procedural facts about another recipient are not a court rule giving all employers a universal right to reports or proposed remedies.'),
 ('positive','procedural_rule','In this case, because the PSEA did not define fraud, the Court stated that it must rely on the Commission interpretation of that concept.',None,'Two sentences are current-court analytical statements, not the prior Rousseau quotation or next investigator dictionary quotation. Keep in-this-case and absent-definition conditions. Do not infer a universal deference rule, non-reviewability or a final jurisdiction/standard-of-review determination.'),
 ('unresolved',None,None,None,'Paragraph 62 begins applicant argues, then shifts into factual contrasts and an unclear-intent inference without an explicit speaker/adoption marker. Whether the latter reasoning is a separate court proposition or continuing applicant advocacy cannot be established sufficiently from this span; the court later reserves final reasonableness review. Do not invent a court rule that personal gain is always required for fraud; abstain with no AU label.'),
]


def make_proposal(task,packet,source,position,batch):
    a,b=task['target_span']['start_char'],task['target_span']['end_char']
    def span(start,end):return exact_span(source,packet['case_id'],packet['source_hash'],start,end)
    outcome,kind,claim,quote,reason=DECISIONS[position-1]
    contexts=[span(max(0,a-1200),min(len(source),b+1200))]
    if position in (7,10):
        c=source.index(RESERVATION);contexts.append(span(source.rfind('[92]',0,c),source.index('[94]',c)))
    review={'target_id':task['target_id'],'review_complete':True,'reviewed_span':span(a,b),'authority_units':[],'hard_negative':None,'notes':[reason],'model_outcome':outcome,'unresolved_reasons':[reason] if outcome=='unresolved' else [],'context_spans':contexts}
    if outcome=='hard_negative':review['hard_negative']={'reason':kind,'reviewed_span':span(a,b),'provenance':PROVENANCE,'notes':[reason]}
    elif outcome=='positive':
        if quote is None:witness=span(a,b)
        else:
            c=source.index(quote,a,b);witness=span(c,c+len(quote))
        au={'au_id':'r4-au-'+task['target_id'][3:],'owner_target_id':task['target_id'],'owner_block_id':task['owner_block_id'],'claim_text':claim,'kind':kind,'other_kind':None,'evidence_spans':[witness],'attributions':[{'role':'proposition','speaker':'current_court','evidence_span':witness}],'condition_spans':[],'exception_spans':[],'limit_spans':[],'cross_block_refs':[],'overlap_disposition':'none','duplicate_of':None,'status':'model_proposed','provenance':PROVENANCE,'notes':[reason],'uncertainty':'low','unresolved_reasons':[]}
        if position==3:
            limitation='not determinative';c=source.index(limitation,a,b);au['limit_spans']=[span(c,c+len(limitation))]
        if position==6:
            condition='in the absence of giving that new evidence to the applicant'
            c=source.index(condition,a,b);au['condition_spans']=[span(c,c+len(condition))]
            limitation='the new information provided by Ms. Cousineau on May 17, 2010'
            c=source.index(limitation,a,b);au['limit_spans']=[span(c,c+len(limitation))]
        if position==9:
            condition='the PSEA does not define what constitutes "fraud"'
            c=source.index(condition,a,b);au['condition_spans']=[span(c,c+len(condition))]
            limitation='In this case';c=source.index(limitation,a,b);au['limit_spans']=[span(c,c+len(limitation))]
        review['authority_units']=[au]
    review['review_trace']=model_review_trace(task,source,packet['source_hash'],review)
    return {'artifact_type':'ModelAUProposal','schema_version':'model-au-proposal-v1','proposal_id':f'p09-r4-099980-fourth10-{position:02d}-gpt61sol-v1','packet_id':packet['packet_id'],'case_id':packet['case_id'],'source_hash':packet['source_hash'],'producer':PRODUCER,'prompt_version':'r4-au-annotation-prompt-v1','batch_id':batch['batch_id'],'status':'model_proposed','target_reviews':[review]}


if __name__=='__main__':run_batch('fourth10',make_proposal,PRODUCER,242,{'authority_units':3,'hard_negatives':5,'unresolved':2})
