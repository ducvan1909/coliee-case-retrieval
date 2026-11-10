# Modal deployment environment helper: independent tests

Date: 2026-11-06  
Checkout: `E:/Git/coliee-case-retrieval`  
Test scope: new `pipeline_v2/deploy_modal.py`; no production M3 files were edited.

## Result

**12/12 tests passed** in 0.591 seconds. Exact command:

```powershell
.venv/Scripts/python.exe -m unittest pipeline_v2.tests.test_modal_deploy_env -v
```

Coverage:

- `.env` BOM, quote handling, `#` inside values, comments, and literal `$` text without shell expansion.
- Duplicate, unknown, malformed, unclosed-quote, and trailing-text errors; error strings and captured output do not reveal fixture credentials.
- Nonblank file values override inherited environment values; blank file values preserve process values or leave the Modal SDK profile fallback available.
- Both-token pair validation at the file and effective-environment layers.
- Read-only `check` output, safe labels when a token is accidentally used as a profile/environment value, and no modification of the synthetic `.env` fixture.
- Frozen M3 plan manifest checksum/profile/code validation and rejection of a resealed manifest with stale code fingerprint.
- Local `--help` exits without calling subprocess.
- Deployment uses argument-list invocation of `sys.executable -m modal deploy pipeline_v2/deployments/modal/qwen3_embed.py`, repository cwd, passed environment, and `shell=False`; token values are absent from argv.
- `m3` forwards the remainder and environment to `sys.executable -m pipeline_v2.m3` without a real child process.

I inspected the installed Modal 1.5.3 SDK source (`modal/config.py`), not its credential file. The SDK chooses `MODAL_PROFILE` when nonempty and otherwise falls back to its active/default profile; its token documentation states environment token variables take precedence over `.modal.toml`. The helper's `check` reported `authentication_verified=false` and `network_requests=0` in tests.

The real `pipeline_v2/.env` is owned by Main and was not opened or modified. All tests use a temporary fixture file. Subprocess calls were mocked; no Modal command, deployment, inference, or network request ran.

M3 production fingerprint remained unchanged at `ade771e2d328b974d12421b5fa48b2b90632b10eb8422166f82b9f960d9add63`.
