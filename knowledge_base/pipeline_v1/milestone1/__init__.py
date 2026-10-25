"""Source-complete KOS-5 baseline orchestration; no inference at import/build."""
from .core import build_manifest, preflight

__all__ = ["build_manifest", "preflight"]
