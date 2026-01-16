"""
DEPRECATED: Import from rd_adapters.storage.caching instead.

This module is kept for backward compatibility.
"""
import warnings

from rd_adapters.storage.caching import (
    R2MetadataCache,
    get_metadata_cache,
)

__all__ = [
    "R2MetadataCache",
    "get_metadata_cache",
]


def __getattr__(name):
    warnings.warn(
        "rd_core.r2_metadata_cache is deprecated. Import from rd_adapters.storage.caching instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
