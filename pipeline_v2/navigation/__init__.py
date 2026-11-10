"""M2 source navigation and exact previews; no embedding or agent inference."""
from .core import M2Error, build_case_navigation
from .store import NavigationReader, build_bundle, validate_bundle

__all__ = ["M2Error", "build_case_navigation", "NavigationReader", "build_bundle", "validate_bundle"]
