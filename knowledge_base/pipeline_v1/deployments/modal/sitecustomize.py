"""Mandatory EOS bootstrap in SGLang children; preserve inherited PYTHONPATH."""
try:
    from json_runtime_hook import install
    install()
except Exception:
    # Python ignores ordinary sitecustomize exceptions. SystemExit terminates
    # the child before it can serve the known inconsistent grammar EOS state.
    raise SystemExit("COLIEE mandatory EOS sync bootstrap failed") from None
