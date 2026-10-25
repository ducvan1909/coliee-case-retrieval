"""Shared, secret-safe configuration for the independent AU runners.

Canonical ``AU_*`` names apply to both runners.  The runner-specific names are
temporary compatibility fallbacks and must not be used in new configuration.
"""
from __future__ import annotations


class AURuntimeConfigError(ValueError):
    """Raised for an invalid non-secret AU runtime setting."""


_DEFAULTS = {
    "TIMEOUT": 60,
    "MAX_REQUESTS": 20,
    "MAX_PROVIDER_ATTEMPTS": 20,
    "MAX_TOTAL_INPUT_TOKENS": 120000,
    "MAX_TOTAL_OUTPUT_TOKENS": 32000,
    "WARMUP_MAX_ATTEMPTS": 10,
    "WARMUP_MAX_WAIT_SECONDS": 600,
    "WARMUP_INITIAL_BACKOFF_SECONDS": 1,
    "WARMUP_MAX_BACKOFF_SECONDS": 30,
    "JOB_WAIT_SECONDS": 1800,
    "JOB_POLL_SECONDS": 2,
}


def _raw(env, suffix, legacy_prefix, default=""):
    """Return canonical AU_* first, then this runner's deprecated fallback."""
    canonical = env.get(f"AU_{suffix}")
    if canonical not in (None, ""):
        return canonical
    legacy = env.get(f"{legacy_prefix}{suffix}")
    if legacy not in (None, ""):
        return legacy
    return default


def _integer(env, suffix, legacy_prefix):
    value = _raw(env, suffix, legacy_prefix, _DEFAULTS[suffix])
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise AURuntimeConfigError(f"AU_{suffix} must be an integer") from None
    if result <= 0:
        raise AURuntimeConfigError(f"AU_{suffix} must be positive")
    return result


def _boolean(env, suffix, legacy_prefix):
    value = str(_raw(env, suffix, legacy_prefix, "false")).strip().lower()
    if value == "true":
        return True
    if value == "false":
        return False
    raise AURuntimeConfigError(f"AU_{suffix} must be true or false")


def load_au_runtime_config(env, legacy_prefix):
    """Build runner config, safety caps, and warmup policy without logging secrets."""
    if legacy_prefix not in {"AU_ONLY_", "AU_COMPACT_"}:
        raise ValueError("legacy_prefix must identify an AU runner")
    cfg = {
        "url": _raw(env, "URL", legacy_prefix),
        "token": _raw(env, "TOKEN", legacy_prefix),
        "model": _raw(env, "MODEL", legacy_prefix),
        "timeout": _integer(env, "TIMEOUT", legacy_prefix),
        "enable_thinking": _boolean(env, "ENABLE_THINKING", legacy_prefix),
    }
    transport = str(_raw(env, "TRANSPORT", legacy_prefix, "direct")).strip().lower()
    string_decoder = str(_raw(env, "STRING_DECODER", legacy_prefix, "bounded")).strip().lower()
    if transport not in {"direct", "jobs"}:
        raise AURuntimeConfigError("AU_TRANSPORT must be direct or jobs")
    if string_decoder not in {"bounded", "host_validated"}:
        raise AURuntimeConfigError("AU_STRING_DECODER must be bounded or host_validated")
    cfg.update(transport=transport, string_decoder=string_decoder,
               jobs_url=_raw(env, "JOBS_URL", legacy_prefix),
               job_wait_seconds=_integer(env, "JOB_WAIT_SECONDS", legacy_prefix),
               job_poll_seconds=_integer(env, "JOB_POLL_SECONDS", legacy_prefix))
    if transport == "jobs" and not cfg["jobs_url"]:
        url = str(cfg["url"])
        if not url.endswith("/v1/chat/completions"):
            raise AURuntimeConfigError("AU_JOBS_URL required for a nonstandard AU_URL")
        cfg["jobs_url"] = url[:-len("/chat/completions")] + "/jobs"
    budget = {
        "max_requests": _integer(env, "MAX_REQUESTS", legacy_prefix),
        "max_provider_attempts": _integer(env, "MAX_PROVIDER_ATTEMPTS", legacy_prefix),
        "max_total_input_tokens": _integer(env, "MAX_TOTAL_INPUT_TOKENS", legacy_prefix),
        "max_total_output_tokens": _integer(env, "MAX_TOTAL_OUTPUT_TOKENS", legacy_prefix),
    }
    warmup_policy = {
        "max_attempts": _integer(env, "WARMUP_MAX_ATTEMPTS", legacy_prefix),
        "max_wait_seconds": _integer(env, "WARMUP_MAX_WAIT_SECONDS", legacy_prefix),
        "initial_backoff_seconds": _integer(env, "WARMUP_INITIAL_BACKOFF_SECONDS", legacy_prefix),
        "max_backoff_seconds": _integer(env, "WARMUP_MAX_BACKOFF_SECONDS", legacy_prefix),
    }
    return cfg, budget, warmup_policy
