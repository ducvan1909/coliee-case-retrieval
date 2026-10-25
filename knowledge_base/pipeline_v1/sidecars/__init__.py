"""Plan 05 deterministic sidecar annotations and structural relations."""

from .api import SidecarAPI, SidecarQueryError
from .build import SidecarError, build_sidecars, load_and_validate_sidecar_map, validate_sidecar_map
from .workers import run_sidecar_workers

__all__ = ["SidecarAPI", "SidecarQueryError", "SidecarError", "build_sidecars", "load_and_validate_sidecar_map", "run_sidecar_workers", "validate_sidecar_map"]
