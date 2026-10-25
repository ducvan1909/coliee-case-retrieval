"""Versioned model contracts; offsets and source quotes are host-owned."""
VERSION = 'au-target-context-v2'
STAGE1 = 'au-target-only-v2'
STAGE1_EVIDENCE_FIRST = 'au-target-selection-v1'
STAGE1_PRIMARY_SUPPORT = 'au-target-primary-support-v1'
STAGE2 = 'au-context-supplement-v2'
KINDS = ('holding', 'standard_of_review', 'statutory_hook', 'procedural_rule',
         'fact_pattern_rule', 'foreign_law', 'other', 'unresolved_kind')
NEEDS = ('condition', 'exception', 'speaker', 'scope', 'cross_block_context')
SLOTS = ('condition', 'exception', 'speaker', 'scope')
STAGE1_DECISIONS = ('positive', 'negative', 'needs_context', 'unresolved')
STAGE2_DECISIONS = ('keep', 'reject', 'unresolved', 'revisit_target')
STAGE1_REASON_BY_DECISION = {
    'positive': ('none', 'unclear_attribution', 'missing_qualification',
                 'coverage_incomplete', 'uncertain_eligibility'),
    'negative': ('no_legal_proposition',),
    'needs_context': ('insufficient_target', 'unclear_attribution',
                     'missing_qualification', 'coverage_incomplete', 'uncertain_eligibility'),
    'unresolved': ('insufficient_target', 'unclear_attribution',
                   'missing_qualification', 'coverage_incomplete', 'uncertain_eligibility'),
}
STAGE2_REASON_BY_DECISION = {
    'complete': ('none',),
    'unresolved': ('context_insufficient', 'unclear_attribution', 'qualification_unresolved'),
    'revisit_target': ('revisit_target_required',),
}
STAGE2_ANCHOR_REASON_BY_DECISION = {
    'keep': ('none',),
    'reject': ('primary_not_supported',),
    'unresolved': ('context_insufficient', 'unclear_attribution', 'qualification_unresolved'),
}
REASON_TEXT_VI = {
    'none': 'Không có lý do bất định bổ sung.',
    'no_legal_proposition': 'TARGET không có proposition pháp lý đủ tư cách AU.',
    'insufficient_target': 'TARGET chưa đủ thông tin để xác định proposition chính.',
    'unclear_attribution': 'Chưa xác định rõ người nói hoặc nguồn của proposition.',
    'missing_qualification': 'Cần làm rõ điều kiện, ngoại lệ hoặc phạm vi áp dụng.',
    'coverage_incomplete': 'Chưa bao phủ hết các proposition cần xem xét trong TARGET.',
    'uncertain_eligibility': 'Chưa xác định nội dung có đủ tư cách AU hay không.',
    'context_insufficient': 'Context được cung cấp chưa đủ để giải quyết bất định.',
    'primary_not_supported': 'Evidence chính chưa hỗ trợ claim dự kiến đã khóa.',
    'qualification_unresolved': 'Điều kiện, ngoại lệ hoặc phạm vi vẫn chưa xác định.',
    'revisit_target_required': 'Cần xem lại TARGET; không tự phát sinh request mới.',
}
MAX_ANCHORS = 3
MAX_REFS = 8
OUTPUT_CAP = 800
BUDGET = {'max_requests': 64, 'max_provider_attempts': 100,
          'max_total_input_tokens': 800000, 'max_total_output_tokens': 80000}

# Exact keys/order also drive the rooted finite grammar. Host rejects extra keys.
STAGE1_KEYS = ('version', 'request_id', 'target_id', 'decision', 'anchors',
               'needs_context', 'reason')
ANCHOR_KEYS = ('anchor_id', 'kind', 'primary_claim', 'target_ref_ids', 'needs_context')
EVIDENCE_FIRST_ANCHOR_KEYS = ('anchor_id', 'kind', 'target_ref_ids', 'needs_context')
PRIMARY_SUPPORT_ANCHOR_KEYS = ('anchor_id', 'kind', 'primary_ref_id', 'supporting_ref_ids', 'needs_context')


def stage1_version(prompt_profile='baseline_v2'):
    if prompt_profile == 'primary_support_v1':
        return STAGE1_PRIMARY_SUPPORT
    return STAGE1_EVIDENCE_FIRST if prompt_profile == 'evidence_first_v1' else STAGE1


def stage1_anchor_keys(prompt_profile='baseline_v2'):
    if prompt_profile == 'primary_support_v1':
        return PRIMARY_SUPPORT_ANCHOR_KEYS
    return EVIDENCE_FIRST_ANCHOR_KEYS if prompt_profile == 'evidence_first_v1' else ANCHOR_KEYS
STAGE2_KEYS = ('version', 'request_id', 'target_id', 'decision', 'anchors', 'reason')
STAGE2_ANCHOR_KEYS = ('anchor_id', 'decision', 'supplements', 'reason')
SUPPLEMENT_KEYS = ('slot', 'text', 'context_ref_ids')
