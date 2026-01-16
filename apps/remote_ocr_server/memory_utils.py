"""
DEPRECATED: Import from rd_pipeline.utils.memory instead.

This module is a backward compatibility shim.
"""
import warnings

warnings.warn(
    "apps.remote_ocr_server.memory_utils is deprecated. "
    "Use rd_pipeline.utils.memory instead.",
    DeprecationWarning,
    stacklevel=2,
)

from rd_pipeline.utils.memory import (
    get_memory_mb,
    get_memory_details,
    log_memory,
    log_memory_delta,
    force_gc,
    get_object_size_mb,
    get_pil_image_size_mb,
    log_pil_images_summary,
    HAS_PSUTIL,
)

__all__ = [
    "get_memory_mb",
    "get_memory_details",
    "log_memory",
    "log_memory_delta",
    "force_gc",
    "get_object_size_mb",
    "get_pil_image_size_mb",
    "log_pil_images_summary",
    "HAS_PSUTIL",
]
