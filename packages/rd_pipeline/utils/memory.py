"""Memory monitoring utilities."""
import gc
import logging
import os
import sys
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import psutil

    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


def get_memory_mb() -> float:
    """Get current process memory usage (MB)."""
    if HAS_PSUTIL:
        proc = psutil.Process(os.getpid())
        return proc.memory_info().rss / (1024 * 1024)
    return 0.0


def get_memory_details() -> dict:
    """Get detailed memory information."""
    if not HAS_PSUTIL:
        return {"rss_mb": 0, "vms_mb": 0, "shared_mb": 0}

    proc = psutil.Process(os.getpid())
    mem = proc.memory_info()
    return {
        "rss_mb": mem.rss / (1024 * 1024),
        "vms_mb": mem.vms / (1024 * 1024),
        "shared_mb": getattr(mem, "shared", 0) / (1024 * 1024),
    }


def log_memory(label: str, level: int = logging.INFO) -> float:
    """Log current memory state."""
    mem_mb = get_memory_mb()
    logger.log(level, f"[MEMORY] {label}: {mem_mb:.1f} MB")
    return mem_mb


def log_memory_delta(label: str, start_mb: float, level: int = logging.INFO) -> float:
    """Log memory delta from start."""
    current_mb = get_memory_mb()
    delta = current_mb - start_mb
    sign = "+" if delta >= 0 else ""
    logger.log(level, f"[MEMORY] {label}: {current_mb:.1f} MB ({sign}{delta:.1f} MB)")
    return current_mb


def force_gc(label: str = "") -> float:
    """Force garbage collection with logging."""
    before = get_memory_mb()
    gc.collect()
    after = get_memory_mb()
    freed = before - after
    if freed > 1:
        logger.info(
            f"[MEMORY] GC{' ' + label if label else ''}: freed {freed:.1f} MB"
        )
    return after


def get_object_size_mb(obj) -> float:
    """Get approximate object size in MB."""
    return sys.getsizeof(obj) / (1024 * 1024)


def get_pil_image_size_mb(img) -> float:
    """Get PIL Image memory size (MB)."""
    if img is None:
        return 0.0
    try:
        channels = len(img.getbands())
        return (img.width * img.height * channels) / (1024 * 1024)
    except:
        return 0.0


def log_pil_images_summary(images: dict, label: str = "") -> None:
    """Log summary of PIL images dictionary."""
    total_mb = sum(get_pil_image_size_mb(img) for img in images.values())
    count = len(images)
    logger.info(f"[MEMORY] {label}: {count} images, ~{total_mb:.1f} MB")
