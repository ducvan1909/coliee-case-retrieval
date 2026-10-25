"""Executed third ten-target R4 decisions; model proposals, not independent audit."""
from .au_gold.core import exact_span,model_review_trace
from .au_gold.r4_batch import run_batch
from .review_plan09_r4_first10 import PRODUCER,PROVENANCE

BATCH_ID='p09-r4-099980-third10-sol-v1'
DECISIONS=[
 ('hard_negative','editorial',None,None,'Paragraph 200 thanks counsel and asks the Commission to reflect on practices. This is a non-operative closing request, not an enforceable systemic reform order or general legal rule; the formal judgment follows under another target.'),
 ('positive','procedural_rule','People directly affected by this final Commission investigation report had to receive a draft and an opportunity to comment before it was submitted for approval.',"So how could one imagine for one moment that the people directly affected by it would not receive and be able to comment on a draft of the final investigation report before it was submitted for approval to the Commission?",'Current-court rhetorical conclusion, confirmed by paragraph 174. Keep scope to this final analysis/conclusions report affecting individuals, not all documents or a general right to comment after final approval. Exclude reported investigator fraud findings from primary attribution.'),
 ('hard_negative','editorial',None,None,'Paragraph 182 introduces the judge remedy reflection and metaphor repair/not excuse. It does not state an operative remedy or standalone rule; do not import the specific declarations and reservations from paragraphs 183-184.'),
 ('positive','holding','The Court found the applicant March 31, 2010 notice to appear insufficient because it did not disclose that the Commission suspected her of fraud.',"The notice to appear dated March 31, 2010, is clearly insufficient. It must be stated again that it in no way mentions that the Commission suspected the applicant of fraud at that time.",'Explicit current-court finding about this notice. Preserve date/applicant limitation and the non-disclosure reason; do not use quoted boilerplate notice in paragraph 149 as court law or make all Commission notices automatically invalid.'),
 ('hard_negative','fact_only',None,None,'Paragraph 141 introduces and quotes investigator description of investigation purpose and appointment/reference allegations. This is quoted agency factual scope, not adopted court interpretation or a legal finding that the applicant committed fraud.'),
 ('unresolved',None,None,None,'Paragraph 57 reports a cited court confirmation of a case-specific fraud finding, then expressly labels the quoted copying-for-advantage statement an investigator argument within that judgment. Separate adoption of a reusable legal proposition and its speaker cannot be established from this nested, suppressed-citation excerpt. Do not promote the investigator argument to current_court or cited_court; abstain with no AU label.'),
 ('positive','statutory_hook','The PSEA and PSLRA enacted by the PSMA provided for review of the legislation, its administration and application five years after entry into force.',"The PSEA and the PSLRA, both enacted by the PSMA, provide for a review of legislation, as well as its administration and application, five years after its entry into force.",'Opening sentence is court paraphrase of a statutory review hook. Keep the five-year temporal limitation. The later Review Team observations/recommendation 3.1 are non-statutory policy recommendations, not court orders or binding legislative discipline duties; they are excluded from primary evidence.'),
 ('hard_negative','fact_only',None,None,'Paragraph 66 describes this jurisdiction report dates and omission of the Policy. It is court case-record appraisal, not a final jurisdiction determination or standalone legal test.'),
 ('hard_negative','procedural_history_only',None,None,'Paragraph 68 expressly quotes the investigator report response to a jurisdiction objection. The section-69 interpretation is agency speech, not current-court adoption; later paragraphs reserve a final court jurisdiction ruling.'),
 ('positive','holding','For this impugned decision, the Court stated that it lacked authority to set it aside retroactively.',"The Court does not have the authority to retroactively set aside the impugned decision",'Current-court case-specific temporal-remedy observation in the costs/harm discussion. Do not turn it into a universal bar on retroactive judicial review relief or a rule validating the Commission permission condition. The remainder of the sentence explains continuing effects; retain this-decision scope.'),
]


def make_proposal(task,packet,source,position,batch):
    a,b=task['target_span']['start_char'],task['target_span']['end_char']
    def span(start,end):return exact_span(source,packet['case_id'],packet['source_hash'],start,end)
    outcome,kind,claim,quote,reason=DECISIONS[position-1]
    review={'target_id':task['target_id'],'review_complete':True,'reviewed_span':span(a,b),'authority_units':[],'hard_negative':None,'notes':[reason],'model_outcome':outcome,'unresolved_reasons':[reason] if outcome=='unresolved' else [],'context_spans':[span(max(0,a-1100),min(len(source),b+1100))]}
    if outcome=='hard_negative':review['hard_negative']={'reason':kind,'reviewed_span':span(a,b),'provenance':PROVENANCE,'notes':[reason]}
    elif outcome=='positive':
        c=source.index(quote,a,b);witness=span(c,c+len(quote))
        au={'au_id':'r4-au-'+task['target_id'][3:],'owner_target_id':task['target_id'],'owner_block_id':task['owner_block_id'],'claim_text':claim,'kind':kind,'other_kind':None,'evidence_spans':[witness],'attributions':[{'role':'proposition','speaker':'current_court','evidence_span':witness}],'condition_spans':[],'exception_spans':[],'limit_spans':[],'cross_block_refs':[],'overlap_disposition':'none','duplicate_of':None,'status':'model_proposed','provenance':PROVENANCE,'notes':[reason],'uncertainty':'medium' if position in (2,10) else 'low','unresolved_reasons':[]}
        if position==2:
            condition='the impugned investigation report was final'
            c=source.index(condition,a,b);au['condition_spans']=[span(c,c+len(condition))]
            confirmation='To ask the question is to answer it at the same time.'
            c=source.index(confirmation,b);au['cross_block_refs']=[span(c,c+len(confirmation))]
            limitation='before it was submitted for approval to the Commission'
            c=source.index(limitation,a,b);au['limit_spans']=[span(c,c+len(limitation))]
        if position==4:
            limitation='notice to appear dated March 31, 2010'
            c=source.index(limitation,a,b);au['limit_spans']=[span(c,c+len(limitation))]
            condition='it in no way mentions that the Commission suspected the applicant of fraud at that time'
            c=source.index(condition,a,b);au['condition_spans']=[span(c,c+len(condition))]
        if position==7:
            limitation='five years after its entry into force'
            c=source.index(limitation,a,b);au['limit_spans']=[span(c,c+len(limitation))]
        if position==10:
            limitation='the impugned decision'
            c=source.index(limitation,witness['start_char'],witness['end_char']);au['limit_spans']=[span(c,c+len(limitation))]
        review['authority_units']=[au]
    review['review_trace']=model_review_trace(task,source,packet['source_hash'],review)
    return {'artifact_type':'ModelAUProposal','schema_version':'model-au-proposal-v1','proposal_id':f'p09-r4-099980-third10-{position:02d}-gpt61sol-v1','packet_id':packet['packet_id'],'case_id':packet['case_id'],'source_hash':packet['source_hash'],'producer':PRODUCER,'prompt_version':'r4-au-annotation-prompt-v1','batch_id':batch['batch_id'],'status':'model_proposed','target_reviews':[review]}


if __name__=='__main__':run_batch('third10',make_proposal,PRODUCER,232,{'authority_units':4,'hard_negatives':5,'unresolved':1})
