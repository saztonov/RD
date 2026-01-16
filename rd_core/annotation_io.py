"""
Backward compatibility shim for annotation_io.

DEPRECATED: Import from rd_domain.annotation instead.
"""

# Re-export everything from rd_domain.annotation
from rd_domain.annotation import (
    AnnotationIO,
    MigrationResult,
    CURRENT_ANNOTATION_VERSION,
)

# Backward compat alias
ANNOTATION_FORMAT_VERSION = CURRENT_ANNOTATION_VERSION

__all__ = [
    "AnnotationIO",
    "MigrationResult",
    "CURRENT_ANNOTATION_VERSION",
    "ANNOTATION_FORMAT_VERSION",
]
