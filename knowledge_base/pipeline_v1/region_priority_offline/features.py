"""Source-only saturated rule cues; no learned or entity-name features."""
import re

PATTERNS = {
    'rights': r'\b(?:rights?|entitled|entitlement|liberty)\b',
    'duty': r'\b(?:dut(?:y|ies)|obligation|must|shall|required)\b',
    'standard': r'\b(?:test|standard|principle|reasonable|reasonableness|burden|threshold)\b',
    'rebuttal': r'\b(?:rebut|rebuttal|presumption|contrary|unless|except|however)\b',
    'fact': r'\b(?:evidence|facts?|found|finding|applicant|respondent|conduct|record)\b',
    'consequence': r'\b(?:therefore|accordingly|liable|liability|dismiss|dismissed|breach|entitled|satisfied|not met|conclude|concluded)\b',
    'citation': r'\b(?:\d{4}\s+(?:SCC|FCA|FC|CanLII)|\d+\s+(?:S\.C\.R\.|F\.C\.|D\.L\.R\.))|\[\d{4}\]|(?:FRAGMENT|REFERENCE|CITATION)_SUPPRESSED',
    'quote': r'["“”]|\b(?:quoted|quotation|as follows)\b',
    'reporting': r'\b(?:held|stated|observed|said|according to|the court in|wrote)\b',
    'qualification': r'\b(?:if|where|unless|provided that|subject to|except|although|however|only where|not sufficient|does not)\b',
    'paragraph_reference': r'\b(?:paras?\.?|paragraphs?)\s+(\d+)\b',
    'negation': r'\b(?:not|no|never|neither|without|cannot)\b',
    'review': r'\b(?:standard of review|correctness|deference|reasonableness)\b',
    'statute': r'\b(?:section|subsection|statute|Act|regulation)\b',
    'rationale': r'\b(?:because|policy reasons|for that reason|unlike|distinguish)\b',
    'speaker_voice': r'\b(?:(?:applicant|respondent)\s+(?:submits|argues)|officer\s+(?:concludes|concluded)|(?:I|we)\s+(?:agree|disagree))\b',
}


def extract_features(text):
    """Offsets relative to complete input; occurrence count saturates at three."""
    anchors = {key: sorted({(m.start(), m.end()) for m in re.finditer(pattern, text, re.I)})
               for key, pattern in PATTERNS.items()}
    counts = {key: min(3, len(spans)) for key, spans in anchors.items()}
    doctrine = sum(bool(counts[k]) for k in ('rights', 'duty', 'standard', 'rebuttal'))
    application = bool(counts['fact'] and counts['consequence'])
    reported = bool(counts['citation'] and (counts['quote'] or counts['reporting']))
    context = sum(bool(counts[k]) for k in ('qualification', 'quote', 'reporting', 'paragraph_reference', 'speaker_voice'))
    return {'counts': counts, 'anchors': {k: [{'start_char': a, 'end_char': b} for a, b in v] for k, v in anchors.items()},
            'lane_scores': {'doctrine': doctrine + bool(counts['standard'] and counts['duty']) + bool(counts['review']) + bool(counts['statute'] and (counts['duty'] or counts['rights'])),
                            'application': int(application) * (2 + counts['consequence'] + bool(counts['rationale'])),
                            'reported_authority': int(reported) * (2 + bool(counts['quote'])),
                            'context_need': context},
            'open_quote': text.count('"') % 2 == 1 or text.count('“') != text.count('”'),
            'polarity_status': 'not_semantically_resolved; negation anchors retained',
            'missing_learned_features': ['semantic_doctrine', 'semantic_application', 'NER', 'embeddings', 'qualified_evidence']}
