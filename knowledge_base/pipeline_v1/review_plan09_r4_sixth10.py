"""Sixth frozen R4 ten-target model review, executed 2026-10-06."""
from .au_gold.core import exact_span,model_review_trace
from .au_gold.r4_batch import run_batch
from .review_plan09_r4_first10 import PRODUCER,PROVENANCE
from .review_plan09_r4_second10 import RESERVATION

BATCH_ID='p09-r4-099980-sixth10-sol-v1'
DECISIONS=[
 ('positive','procedural_rule','The content of the duty of fairness varies with the context.','Court explicitly states contextual variation. Primary only the complete first clause; the list of Baker factors starts in a separate target, retained as context rather than duplicated as this claim.'),
 ('positive','holding','In this case, failure to submit the June 10, 2010 final investigation report containing the investigator analysis and findings to the applicant for comments before Commission approval was a fundamental procedural flaw.','Court explicitly calls the omission a fundamental problem/fatal flaw. Keep this report/applicant/pre-approval scope; no universal duty to circulate every investigative document. Later paragraphs 169/173-174 confirm the final-analysis issue, not merely comments on a factual report or proposed corrective actions.'),
 ('positive','procedural_rule','The fairness assessment considers the nature of the decision and process, the statutory scheme, the importance to affected individuals, their legitimate expectations, and respect for procedural choices.','Continuation of the Court expressly adopted Baker criteria in paragraph 97. Read the preceding introduction to establish speaker and referent; list is not a freestanding heading or party argument. Do not convert five contextual factors into five unconditional duties or say procedural choices determine fairness by themselves.'),
 ('unresolved',None,None,'Paragraph 25 mixes case-specific employer non-party history with an expressly assumed non-representation and a hypothetical conflict of interest. It does not establish actual concurrent representation or adjudicate a conflict. AU eligibility/kind for this hypothetical legal inference remains uncertain; no forced conflict holding or whole-span fact-only negative.'),
 ('positive','statutory_hook','Under paragraph 69(a) of the PSEA, in cases of fraud the Commission may revoke an appointment or not make an appointment, as the case may be.','Court paraphrases the explicit paragraph 69(a) remedy. First sentence only is primary. The following third-party corrective-action question is not answered here; paragraphs 93/183-184 reserve final jurisdiction/reasonableness. Do not extend this appointment power into a decided independent power to sanction third parties.'),
 ('positive','standard_of_review','The Court applies correctness to the alleged breach of procedural fairness.','Explicit current-court standard in paragraph 96, limited to procedural fairness. Later case-by-case observations concern distinct facts in Seck 1 and do not decide Commission jurisdiction/reasonableness. Suppressed citation does not supply an invented named authority.'),
 ('hard_negative','editorial',None,'Paragraph 181 reflects rhetorically on judicial dialogue, truth-telling and sharp arguments. It contains no operative remedy, costs entitlement or reusable legal test; do not import paragraph 180 powers or 183 reservation.'),
 ('positive','holding','In the exceptional circumstances of this case, the applicant was entitled to increased costs above ordinary Column III party-and-party costs, with harm, opposing-party conduct, public interest, administration of justice and public confidence determining the exercise of discretion.','Court costs holding and reasons, scoped to this exceptional case and discretionary costs. Not automatic solicitor-and-client costs or acceptance of the applicant requested amount. Retain exceptional circumstances and ordinary-default qualification; the preceding respondent minimum-cost position is not adopted.'),
 ('positive','statutory_hook','Section 69 permits investigation of an appointment process where there is reason to believe fraud may have occurred and, if satisfied fraud occurred, permits revocation or non-appointment and appropriate corrective action.','Primary is the English statutory text quoted by the Court, attributed to statute rather than current_court holding. Preserve both separate thresholds and permissive may. French parallel text remains reviewed context. Introductory supposed authority and paragraphs 93/183-184 do not decide this applicant/third-party jurisdiction issue or an independent corrective-action power.'),
 ('hard_negative','fact_only',None,'Paragraph 165 appraises factual incompleteness concerning the actual applicant tasks/supervision. No freestanding legal investigation test or universal duty to interview managers is stated; later prejudice reasoning and the applicant affidavit are not imported as court law.'),
]


def make_proposal(task,packet,source,position,batch):
    a,b=task['target_span']['start_char'],task['target_span']['end_char']
    def span(start,end):return exact_span(source,packet['case_id'],packet['source_hash'],start,end)
    def local(quote):
        c=source.index(quote,a,b);return span(c,c+len(quote))
    outcome,kind,claim,reason=DECISIONS[position-1]
    contexts=[span(max(0,a-1200),min(len(source),b+1200))]
    if position in (5,9):
        c=source.index(RESERVATION);contexts.append(span(source.rfind('[92]',0,c),source.index('[94]',c)))
        contexts.append(span(source.index('[183]'),source.index('[185]')))
    if position==2:contexts.append(span(source.index('[168]'),source.index('[175]')))
    review={'target_id':task['target_id'],'review_complete':True,'reviewed_span':span(a,b),'authority_units':[],'hard_negative':None,'notes':[reason],'model_outcome':outcome,'unresolved_reasons':[reason] if outcome=='unresolved' else [],'context_spans':contexts}
    if outcome=='hard_negative':review['hard_negative']={'reason':kind,'reviewed_span':span(a,b),'provenance':PROVENANCE,'notes':[reason]}
    elif outcome=='positive':
        if position==1:witness=local('The content of the duty of fairness varies depending on the context')
        elif position==2:witness=span(a,source.index(' More will',a,b))
        elif position==3:
            c=source.index('the nature of the decision',a,b);end=source.index('respect for the choices of procedure.',c,b)+len('respect for the choices of procedure.');witness=span(c,end)
        elif position==5:witness=span(a,source.index(' That is',a,b))
        elif position==6:witness=local('It is appropriate for the standard of correctness to guide the analysis of the Court with respect to the alleged breach of the rules of procedural fairness:')
        elif position==8:witness=span(a,b-len(source[a:b])+len(source[a:b].rstrip()))
        elif position==9:
            c=source.index('69. If',a,b);end=source.index('69. La',c,b);witness=span(c,c+len(source[c:end].rstrip()))
        au={'au_id':'r4-au-'+task['target_id'][3:],'owner_target_id':task['target_id'],'owner_block_id':task['owner_block_id'],'claim_text':claim,'kind':kind,'other_kind':None,'evidence_spans':[witness],'attributions':[{'role':'proposition','speaker':'statutory_text' if position==9 else 'current_court','evidence_span':witness}],'condition_spans':[],'exception_spans':[],'limit_spans':[],'cross_block_refs':[],'overlap_disposition':'none','duplicate_of':None,'status':'model_proposed','provenance':PROVENANCE,'notes':[reason],'uncertainty':'medium' if position in (2,3,8) else 'low','unresolved_reasons':[]}
        if position==1:au['limit_spans']=[local('depending on the context')]
        if position==2:
            au['limit_spans']=[local('the investigation report dated June 10, 2010'),local('before it was presented to the Commission for final approval')]
            c=source.index('[173]');au['cross_block_refs']=[span(c,source.index('[175]',c))]
        if position==3:
            c=source.rfind('The content of the duty of fairness',0,a);end=source.index('Baker',c);intro=span(c,end)
            au['cross_block_refs']=[intro];au['attributions']=[{'role':'proposition','speaker':'current_court','evidence_span':intro}]
        if position==5:
            au['condition_spans']=[local('in cases of fraud')];au['limit_spans']=[local('as the case may be')]
        if position==6:au['limit_spans']=[local('with respect to the alleged breach of the rules of procedural fairness')]
        if position==8:
            au['condition_spans']=[local('given the specific - and I would say, exceptional - circumstance of this case')]
            au['limit_spans']=[local('in the absence of an order to the contrary by the Court'),local('in this case'),local('with respect to costs')]
        if position==9:
            au['condition_spans']=[local('If it has reason to believe that fraud may have occurred in an appointment process'),local('if it is satisfied that fraud has occurred')]
            au['limit_spans']=[local('as the case may be'),local('that it considers appropriate')]
        review['authority_units']=[au]
    review['review_trace']=model_review_trace(task,source,packet['source_hash'],review)
    return {'artifact_type':'ModelAUProposal','schema_version':'model-au-proposal-v1','proposal_id':f'p09-r4-099980-sixth10-{position:02d}-gpt61sol-v1','packet_id':packet['packet_id'],'case_id':packet['case_id'],'source_hash':packet['source_hash'],'producer':PRODUCER,'prompt_version':'r4-au-annotation-prompt-v1','batch_id':batch['batch_id'],'status':'model_proposed','target_reviews':[review]}


if __name__=='__main__':run_batch('sixth10',make_proposal,PRODUCER,262,{'authority_units':7,'hard_negatives':2,'unresolved':1})
