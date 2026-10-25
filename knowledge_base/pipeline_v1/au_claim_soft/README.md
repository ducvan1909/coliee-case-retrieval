# AU claim soft length policy

This package only validates responses and imports the original A checkpoint
offline. It does not extract, repair, shorten, run stage 2, or call a provider.

Public API:

```python
from knowledge_base.pipeline_v1.au_claim_soft import validate_response, import_run

normalized = validate_response(value, job)
report = import_run(parent_root, output_root)
```

Future active flows should use this exported `validate_response`. The validator
in `au_claim` retains its historical hard length checks solely for verifying
immutable old checkpoints; it is not the active soft length policy.

Claim 500, limits 250, and context question 200 characters are warning thresholds
only. Warnings contain `code`, `severity`, `path`, `threshold`, and `actual_length`
(measured before whitespace normalization). Wrong types, blank text, surrogates,
invalid kinds/evidence, context-only evidence, and other original hard gates
remain invalid. The original whitespace normalization, evidence ordering,
duplicate handling, and full normalized text AU identity mechanism are retained.
No text is truncated; the import report also retains original raw responses and
parsed model outputs.

```powershell
.venv/Scripts/python.exe -m knowledge_base.pipeline_v1.au_claim_soft import --parent-root ORIGINAL_A_ROOT --output-root NEWROOT
```

`NEWROOT` must not exist or overlap protected inputs/code. Import verifies the
original `_checkpoint`, revalidates all 16 original stage-1 responses, and writes
`NEWROOT/report.json` with input bindings, policy/code/report hashes, full outputs,
warnings, historical accounting, and zero new requests/tokens. A hard-invalid
response stays invalid; length alone never triggers repair. Context requests are
reported as `needs_context` with `context_status: pending`; continuation belongs
to a separate workflow. Protocol verification does not assess semantic AU quality.
