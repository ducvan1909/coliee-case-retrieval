# Plan 09 P09-R1–R3 remediation

P09-S01 is quarantined with severity `severe`. The original canonical proposal
is unchanged; its raw-byte SHA-256 is recorded in the defect registry and
amendment. Silver lock raises `silver_semantic_quarantine` while the finding is
open. Plan 10 remains locked.

The local reporting-cue scanner reads immutable raw source using `open_source`
and validates each canonical proposal. `attribution_risk_queue.json` records
exact cue spans and reason codes. It changes no labels. Cue coverage is a risk
heuristic, not a semantic precision/recall measurement or a complete detector
for unsupported claims, omissions, or distant attribution.

The model amendment for P09-S01 removes the erroneous AU from the effective
view and records `unresolved`. Raw paragraphs 30–43 show that the target merges
the party submission in paragraph 34 with a heading introducing the court's
response. Independent model review must decide whether the heading supports a
separate AU. The finding remains open and quarantined; R3's closure gate has
not been met. No independent tester or Terra execution is claimed: the review
record explicitly identifies the current GPT-6 reviewer.

Progress counts now describe the effective amendment view. Canonical proposal
bytes and ownership are retained. The 157 unreviewed targets have not been
processed. Human gold is absent; this is model-silver remediation.

Verification before independent-review fixes: 17/17 narrow Plan 09 tests,
110/110 pipeline regression tests, and 4/4 existing independent Plan 09
infrastructure tests passed. Scanner
reproduction found 49 risk items. Effective counts are 212 reviewed, 98 AU,
112 hard negatives and 2 unresolved. These checks do not establish semantic
PASS; P09-S01 remains open pending independent disposition.

Independent model review confirmed that unresolved quarantine is justified.
It also found outcome, provenance, unresolved-count and incomplete-lock defects;
these were repaired and covered by additional tests. See
`plan09_remediation_independent_review.md`. Final post-fix verification is
recorded here: 22/22 combined narrow and independent tests passed; 111/111
pipeline regression tests passed in 80.393 seconds. Original proposal SHA-256
and deterministic risk-queue reproduction were also rechecked successfully.

Commands:

```powershell
python -m knowledge_base.pipeline_v1.au_gold scan-attribution-risks --output risk.json
python -m knowledge_base.pipeline_v1.au_gold validate-amendment --amendment amendment.json --output validation.json
python -m knowledge_base.pipeline_v1.au_gold checkpoint-amendment --amendment amendment.json --output validation.json
python -m unittest knowledge_base.pipeline_v1.tests.test_plan09_remediation knowledge_base.pipeline_v1.tests.test_plan09
```

Checkpoint validates source, canonical owner, original-file digest, target,
reviewer, reason, review trace and field-level evidence before writing a new
amendment. Existing amendment IDs and repeated amendments to the same original
target are refused; further review requires an explicit chaining extension.
