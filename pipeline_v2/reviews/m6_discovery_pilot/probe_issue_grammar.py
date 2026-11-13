"""Run inside the serving image to compare XGrammar acceptance without inference."""

import json
from importlib.metadata import version

import xgrammar as xgr


def main():
    # This is the search branch from the 017984 v11 payload, isolated from other actions.
    def obj(properties):
        return {"type": "object", "properties": properties,
                "required": list(properties), "additionalProperties": False}

    issue = {"type": "string", "minLength": 4, "maxLength": 160}
    compiler = xgr.GrammarCompiler(xgr.TokenizerInfo([]))
    results = {}
    for name, spec in (("old", {**issue, "pattern": r"\S"}), ("without_pattern", issue)):
        branch = obj({"action": {"const": "search_cases_by_issue"}, "args": obj({
            "issue": spec, "a_paragraph_ref": {"enum": ["p000002", "p000003"], "type": "string"},
        })})
        schema = {"type": "object", "anyOf": [branch]}
        compiled = compiler.compile_json_schema(json.dumps(schema), any_whitespace=True)
        results[name] = {}
        for value in ("w", "standard of review"):
            reply = json.dumps({"action": "search_cases_by_issue", "args": {
                "issue": value, "a_paragraph_ref": "p000002",
            }})
            matcher = xgr.GrammarMatcher(compiled, terminate_without_stop_token=True)
            results[name][value] = matcher.accept_string(reply) and matcher.is_terminated()

    print(json.dumps({"vllm_version": version("vllm"), "xgrammar_version": version("xgrammar"),
                      "acceptance": results, "model_requests": 0}, indent=2))


if __name__ == "__main__":
    main()
