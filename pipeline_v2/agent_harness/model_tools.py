"""Model-facing tool descriptions for the fixed M4 corpus acceptance route."""


CORPUS_MODEL_TOOLS = {
    "search_corpus": {
        "name": "search_cases_by_issue",
        "description": "Find a candidate case by a legal issue raised in A.",
        "when": "A has been read and the run has not searched yet.",
        "parameters": {"issue": "Short search phrase grounded in A's text. Omit case IDs."},
        "result": "A candidate lead and a passage preview. A preview is not evidence.",
    },
    "open_source": {
        "name": "read_case_passages",
        "description": "Read the passages identified by the current candidate lead.",
        "when": "The lead has a source reference ready to open.",
        "parameters": {},
        "result": "Raw excerpts and refs for B, with source coverage and provenance.",
    },
    "reload_source": {
        "name": "reload_delivered_passages",
        "description": "Bring previously delivered A and current B excerpts into the same turn.",
        "when": "B has just been read and A is absent from this payload.",
        "parameters": {},
        "result": "The selected raw A and B excerpts in the next payload.",
    },
    "assess_links": {
        "name": "assess_case_link",
        "description": "Assess one A-to-B link using current raw excerpts.",
        "when": "One raw excerpt per side is present in this payload.",
        "parameters": {
            "case_relation": "How A uses or relates to B. Choose unknown if evidence is insufficient.",
            "passage_location": "How precisely the relevant passage in B can be located.",
            "reason": "One short sentence grounded in the excerpts, at most 120 characters.",
        },
        "result": "An assessment checked against the source refs and provenance in this payload.",
    },
    "stop": {
        "name": "finish_case_review",
        "description": "End this bounded evidence review.",
        "when": "An assessment has been accepted or the run lacks a usable next step.",
        "parameters": {},
        "result": "A recorded stop with its reason.",
    },
}
