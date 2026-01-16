"""Annotation I/O module."""

from rd_domain.annotation.io import (
    ANNOTATION_FORMAT_VERSION,
    REQUIRED_BLOCK_FIELDS,
    V2_BLOCK_FIELDS,
    AnnotationIO,
    MigrationResult,
    detect_annotation_version,
    migrate_annotation_data,
    migrate_block_v1_to_v2,
    validate_annotation_structure,
)

__all__ = [
    "AnnotationIO",
    "MigrationResult",
    "ANNOTATION_FORMAT_VERSION",
    "REQUIRED_BLOCK_FIELDS",
    "V2_BLOCK_FIELDS",
    "validate_annotation_structure",
    "detect_annotation_version",
    "migrate_block_v1_to_v2",
    "migrate_annotation_data",
]
