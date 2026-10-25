# Portable K0 v2 research handoff

This package derives a versioned portable basis for exactly 3 cases, 16 historical
scopes and 58 delivered parts. It does not migrate the whole corpus. Frozen code,
source bytes, old manifests, payloads, job IDs, receipts and reports are immutable.

All active references use repository-relative POSIX paths. The repository base is
discovered from `__file__`, or passed with `--repo-root`. Absolute paths, drive/UNC
paths, backslashes, traversal and symlink/junction redirects are rejected. Old
absolute paths inside the raw archive and `origin_verification` are provenance,
not portable lookup keys or platform/Python gates.

Use the wrapper from the repository root:

```powershell
$wrapper = './knowledge_base/pipeline_v1/experiments/run_k0_portable.ps1'
& $wrapper -Command inspect
& $wrapper                          # prepares if needed, preflights, then dry run
& $wrapper -Mock -MaxNewRequests 1  # incomplete checkpoint: exit 3
& $wrapper -Mock                    # resumes same portable checkpoint
```

Python equivalent (Windows local environment):

```powershell
.venv/Scripts/python.exe -m knowledge_base.pipeline_v1.k0_portable inspect
.venv/Scripts/python.exe -m knowledge_base.pipeline_v1.k0_portable prepare
.venv/Scripts/python.exe -m knowledge_base.pipeline_v1.k0_portable preflight
.venv/Scripts/python.exe -m knowledge_base.pipeline_v1.k0_portable run --mock --max-new-requests 1
.venv/Scripts/python.exe -m knowledge_base.pipeline_v1.k0_portable run --mock
```

Default basis: `knowledge_base/pipeline_v1/research_snapshots/k0_portable_20261025`.
Default new run: `research_bundle/k0_portable_runs/current`.
Override `--bundle` / `-Bundle` and `--output-root` / `-OutputRoot` with relative
paths. Keep the relative layout when moving the repository. No original `outputs`
directory is needed for portable inspect/prepare/preflight/run. Do not run the old
legacy commands on another machine and expect their absolute bindings to work.

`export` is an origin-only command. It verifies original K0 preflight/CPU gate,
the recovered nine-control report and historical ledger/receipt replay; then it
copies the bounded transitive binding closure byte-for-byte under `archive/`.
It never calls transport. An interrupted export can continue only when existing
copied bytes match. A completed export requires explicit `--refresh-derived` to
refresh the derived manifest after implementation changes; previous derived
manifest bytes are retained in `derived_history/`. Historical archive files are
never rewritten or re-sealed.

`inspect` verifies archived bytes, source hash/length/offsets and stored control
seals plus v2 row validation without requiring the origin platform or Python.
`inspect --check-runtime` and `preflight` additionally gate production code,
contracts, tokenizer files/revision and counter library versions. Model/revision,
prompt/schema/content and bounded accounting remain gates. Runtime packages and
credentials are not bundled; install the matching tokenizer counter dependencies
(`tokenizers`, `jinja2`) locally. An offline report is not evidence of a fresh
provider call or semantic AU quality.

Historical execution is archive-only. The current completed historical run has
3 verified responses, 0 AUs and unresolved context; it is not imported into a new
run, and `work_scope_complete` remains false. New portable runs have a distinct
workload digest and request IDs. Only a portable checkpoint resumes as itself:
copy the bundle, bound repository files and run directory to a new repository
base, then use the same relative `--output-root`. Receipt reconciliation and
state replay happen before dispatch; valid receipts are reused without POST.
Mock and live checkpoints are separate. No historical receipt becomes a newly
generated receipt. Stop an active invocation before copying its checkpoint.

Paid execution requires separate user authorization and explicit `--execute` /
`-Execute`; implementation validation does not call it. The live gate also needs
a CPU grammar report bound to the newly generated bundle. When the new grammar
bundle is byte-identical to the verified historical CPU input, prepare copies
that historical CPU report without changing any bytes and records its provenance
in `input/cpu_provenance.json`; this is reused evidence, not a new CPU execution.
Otherwise supply `-NativePython`
or `K0_NATIVE_PYTHON` with installed `xgrammar==0.2.1`, `numpy`, `transformers`
and compatible `tokenizers`. The standalone private CPU adapter uses the pinned
repository tokenizer asset, with no legacy `outputs/grammar_diagnostic_deps`
dependency. `-Python` / `K0_PYTHON` overrides the main environment interpreter;
otherwise the wrapper chooses `.venv/Scripts/python.exe` or `.venv/bin/python`.
The NumPy CPU-mask probe disables the unrelated optional Torch DLPack C++ JIT
by default, avoiding compiler startup on a fresh environment.
CPU protocol success does not establish legal semantics or retrieval quality.

Python API: `core.export(bundle, repo_root, history_root=None, controls_root=None,
refresh_derived=False)`, `core.inspect(bundle, repo_root, check_runtime=False)`,
`core.prepare(output_root, bundle, repo_root)`, `core.preflight(output_root,
repo_root, cfg=None)`, `runner.run(output_root, repo_root=None, cfg=None,
execute=False, mock=False, max_new_requests=None, opener=..., clock=..., sleep=...)`.
CLI exit codes: 0 successful local operation/completed execution, 3 incomplete
checkpoint, 1 blocked. Default dry runs perform no network requests.
