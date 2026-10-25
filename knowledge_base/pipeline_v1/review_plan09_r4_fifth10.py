"""Fifth frozen R4 ten-target model review, executed 2026-10-06."""
from .au_gold.core import exact_span,model_review_trace
from .au_gold.r4_batch import run_batch
from .review_plan09_r4_first10 import PRODUCER,PROVENANCE
from .review_plan09_r4_second10 import RESERVATION

BATCH_ID='p09-r4-099980-fifth10-sol-v1'
DECISIONS=[
 ('positive','procedural_rule','In this case, the respondent acting for the Commission was not authorized to argue that natural justice or procedural fairness had been respected.',"Nevertheless, in my opinion, nothing authorizes the respondent to argue, on behalf of the Commission, that the rules of natural justice or procedural fairness were respected in this case.",'Explicit court view, limited to this respondent/Commission case. The earlier reasonableness-support observation is borderline, not an unrestricted ban on respondent advocacy. Paragraph 46 separately records that, absent applicant objection, the Court nevertheless considered the arguments with potential remedies/costs consequences; preserve that practical qualification without saying respondent became authorized.'),
 ('hard_negative','party_argument_only',None,None,'Paragraph 94 expressly reports applicant claims of inadequate notice/disclosure, unfair investigation and credibility issues. Court agreement elsewhere does not change this target speaker into current_court; do not promote all party allegations as holdings.'),
 ('hard_negative','fact_only',None,None,'Paragraph 172 describes the final report structure, changed allegations and agency finding of guilt. The guilt-is-now-established phrase is report appraisal of what the agency decided, not a court conviction or a freestanding legal test. The draft-comment fairness requirement belongs to paragraph 173 and is not imported.'),
 ('hard_negative','party_argument_only',None,None,'Paragraph 91 is framed as the applicant jurisdiction/and-conjunction argument. Paragraph 92 court tentative assent and paragraph 93 reservation do not supply a final court ruling in this target. Do not label the ancillary-power interpretation as adopted current-court law.'),
 ('positive','holding','In this investigation, the Court rejected the respondent suggestion that the investigator procedure respected the legitimate expectations of a person suspected of fraud.',"At the outset, it is important to reject any suggestion by the respondent that the procedure put in place by the investigator was consistent with the legitimate expectations of a person suspected of fraud.",'Court response is explicit rejection, not adoption of respondent position. Primary only the first court sentence; do not promote the subsequent evidentiary narrative into a general rule about investigators motive or all fraud investigations.'),
 ('hard_negative','fact_only',None,None,'Paragraph 131 accepts applicant factual account of supervision and notes failure to contact managers who might corroborate her tasks. No universal legal obligation to interview managers is formulated; do not turn this evidence appraisal into an unconditional procedural rule.'),
 ('positive','holding','For this applicant notice, the Court rejected the respondent no-prejudice argument based on the interview and subsequent opportunity to comment as failing to reflect reality.',"Once again, this is a truncated argument that does not take the reality into consideration and unfortunately does not hold water.",'First three sentences are expressly respondent advocacy. Only the final sentence is court response; narrow primary attribution to it and read the entire target as its referent. Paragraphs 150/152 confirm the actual case-specific notice/fairness finding. Do not claim all post-interview comment opportunities are necessarily incapable of curing every notice defect.'),
 ('hard_negative','fact_only',None,None,'Paragraph 4 introduces the applicant and identifies the impugned Commission fraud decision. That decision finding guilt is agency history, not a current-court guilty finding or statutory authority proposition.'),
 ('hard_negative','fact_only',None,None,'Paragraph 88 narrates source information and appointment facts, then asks why referral to a deputy head did not occur. A rhetorical criticism does not adopt Review Team recommendation 3.1 as a binding mandatory-referral rule.'),
 ('unresolved',None,None,None,'Paragraph 76 distances the Court from Seck 1 and raises a serious question about a reasonableness presumption for a truly jurisdictional issue, but does not decide the legal question. Paragraph 93 reserves a definitive jurisdiction/reasonableness ruling. AU eligibility/kind of this non-final standard observation is uncertain; do not force a settled correctness rule or party-only negative.'),
]


def make_proposal(task,packet,source,position,batch):
    a,b=task['target_span']['start_char'],task['target_span']['end_char']
    def span(start,end):return exact_span(source,packet['case_id'],packet['source_hash'],start,end)
    outcome,kind,claim,quote,reason=DECISIONS[position-1]
    contexts=[span(max(0,a-1200),min(len(source),b+1200))]
    if position==10:
        c=source.index(RESERVATION);contexts.append(span(source.rfind('[92]',0,c),source.index('[94]',c)))
    review={'target_id':task['target_id'],'review_complete':True,'reviewed_span':span(a,b),'authority_units':[],'hard_negative':None,'notes':[reason],'model_outcome':outcome,'unresolved_reasons':[reason] if outcome=='unresolved' else [],'context_spans':contexts}
    if outcome=='hard_negative':review['hard_negative']={'reason':kind,'reviewed_span':span(a,b),'provenance':PROVENANCE,'notes':[reason]}
    elif outcome=='positive':
        c=source.index(quote,a,b);witness=span(c,c+len(quote))
        au={'au_id':'r4-au-'+task['target_id'][3:],'owner_target_id':task['target_id'],'owner_block_id':task['owner_block_id'],'claim_text':claim,'kind':kind,'other_kind':None,'evidence_spans':[witness],'attributions':[{'role':'proposition','speaker':'current_court','evidence_span':witness}],'condition_spans':[],'exception_spans':[],'limit_spans':[],'cross_block_refs':[],'overlap_disposition':'none','duplicate_of':None,'status':'model_proposed','provenance':PROVENANCE,'notes':[reason],'uncertainty':'medium' if position==7 else 'low','unresolved_reasons':[]}
        if position==1:
            limitation='in this case';c=source.index(limitation,witness['start_char'],witness['end_char']);au['limit_spans']=[span(c,c+len(limitation))]
            c=source.index('[46]',b)+len('[46]');end=source.index('[47]',c)
            au['cross_block_refs']=[span(c,end)]
        if position==5:
            limitation='the procedure put in place by the investigator'
            c=source.index(limitation,a,b);au['limit_spans']=[span(c,c+len(limitation))]
        if position==7:
            confirmation='At the outset, it is important to reject any suggestion by the respondent that the procedure put in place by the investigator was consistent with the legitimate expectations of a person suspected of fraud.'
            c=source.index(confirmation,b);au['cross_block_refs']=[span(c,c+len(confirmation))]
        review['authority_units']=[au]
    review['review_trace']=model_review_trace(task,source,packet['source_hash'],review)
    return {'artifact_type':'ModelAUProposal','schema_version':'model-au-proposal-v1','proposal_id':f'p09-r4-099980-fifth10-{position:02d}-gpt61sol-v1','packet_id':packet['packet_id'],'case_id':packet['case_id'],'source_hash':packet['source_hash'],'producer':PRODUCER,'prompt_version':'r4-au-annotation-prompt-v1','batch_id':batch['batch_id'],'status':'model_proposed','target_reviews':[review]}


if __name__=='__main__':run_batch('fifth10',make_proposal,PRODUCER,252,{'authority_units':3,'hard_negatives':6,'unresolved':1})
