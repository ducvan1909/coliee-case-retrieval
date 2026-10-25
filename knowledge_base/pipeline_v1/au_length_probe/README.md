# Isolated AU length probe

Synthetic protocol benchmark only; semantic quality is not assessed. No KOS,
inference, model download, POST, warmup, deployment, or retry. Production AU code
is unchanged. This directory alone may be uploaded as top-level `au_length_probe`.
Only the runtime helper imports repository configuration, inside its function.

Stable API:

```python
offline(tokenizer_path, output_root, variants=None, repeats=1,
        *, max_seconds=120, max_cases=256, report_max_bytes=2_000_000)
prepare(output_root, *, report_max_bytes=2_000_000)
build_grammar(ids=('s1', 'c1'), variant='host_validated')
build_schema(ids=('s1', 'c1'))
build_cases()
```

Both commands create a **new** output directory and exclusive `report.json`.
Existing paths are rejected. Exit 2 means unavailable, failure or exceeded limit;
PREPARED is dry construction, never a matcher PASS. Backend dependencies are
optional, with missing packages reported UNAVAILABLE. Do not install locally just
to run prepare. Pinned dependency versions are supplied by Main's CPU wrapper.

```powershell
.venv/Scripts/python.exe -m knowledge_base.pipeline_v1.au_length_probe prepare --output-root NEW_DIR
.venv/Scripts/python.exe -m knowledge_base.pipeline_v1.au_length_probe offline --tokenizer-path PINNED_LOCAL_SNAPSHOT --output-root NEW_DIR --repeats 2
.venv/Scripts/python.exe -m knowledge_base.pipeline_v1.au_length_probe runtime --output-root NEW_DIR
```

For an isolated CPU image use `python -m au_length_probe` with the same arguments.
`--variants host_validated bounded max_chars` defaults to all three. Optional caps:
`--max-seconds` (1..600), `--max-cases` (1..256; rejects corpus truncation),
`--report-max-bytes` (4096..5000000), repeats (1..10). CLI uses a child-process
watchdog for blocking native calls; the direct Python API checks time between
operations and cannot interrupt a blocked native compiler. Use CLI for a hard
deadline. Output serialization is capped; errors never overwrite a previous file.

Optional `--variants json_schema` calls the native
`compiler.compile_json_schema(json.dumps(build_schema()))` path. This variant is
excluded from defaults and prepare's three EBNF grammars to preserve the baseline.
It uses exact object keys, the same kind/ID enums and AU cap, and native
minLength/maxLength for the three text fields. It runs all 113 fixtures against
the bounded expectations and the same token replay subset. A complete successful
run sets correctness_candidate only; recommendation stays null. Native schema
performance must be measured independently from EBNF repetition performance.

`host_validated` mirrors the current canonical AU grammar byte for byte for the
same ID order. `bounded` has separate 1..500 claim, 1..250 limits, 1..200 question
rules. Each json-char is one Unicode scalar, including an escaped surrogate pair;
combining marks count separately. Lone surrogates remain invalid. Null limits and
context remain valid. JSON whitespace-only text passes grammar length but fails
host validation; this is an intentional distinction. Target evidence ownership
and source entailment remain host responsibilities.

`max_chars` probes `rule-name[max_chars=N] ::= body`, with a raw quoted-string
budget cap+2. This is experimental: raw JSON prefix characters (including quotes
and escape syntax) are **not** decoded Unicode lengths. Compilation failures are
UNSUPPORTED; compiled runs are UNSAFE for default recommendation, with decoded
acceptance mismatches reported separately. No claim of equivalence is made.

All corpus strings use completion acceptance (`accept_string` AND `is_completed`).
A bounded subset of valid cases replays real tokenizer tokens, checks each mask,
blocks every EOS before the root completes, and allows every EOS after completion.
EOS is the union of 248044/248046, actual tokenizer EOS/additional stops and local
checkpoint generation/model EOS. Model text_config/root vocab_size supports padded
vocabulary; required EOS must exist in the tokenizer. Tokenizer hashes and local
directory revision evidence are reported, without claiming remote identity.

Compile latency and first/subsequent replay fill p50/p95 and mask bytes are CPU
diagnostics, not inference speed. Cold means first replay pass with a fresh
compiler per variant; it does not prove a cold OS/process cache. With repeats=1,
warm count is zero. Passing the full bounded corpus only sets correctness_candidate;
recommendation stays null pending timing review and endpoint EOS acceptance.

`runtime` loads existing settings via AU_COMPACT_ fallback, sends one authenticated
HTTPS GET to `/v1/diagnostics/json/info`, rejects redirects, and saves only typed
whitelisted versions/EOS information. Errors preserve a report and exit nonzero;
no URL, credential, response body or exception message is echoed. Run only when
network inspection is authorized. A GET observation does not prove live inference.
