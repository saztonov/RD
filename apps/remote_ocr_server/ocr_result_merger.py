"""
DEPRECATED: Import from rd_pipeline.processing.merge instead.

This module is a backward compatibility shim that uses server-specific
HTML parsing.
"""
from __future__ import annotations

import warnings
from pathlib import Path
from typing import Dict, List, Optional, Tuple

warnings.warn(
    "apps.remote_ocr_server.ocr_result_merger is deprecated. "
    "Use rd_pipeline.processing.merge instead.",
    DeprecationWarning,
    stacklevel=2,
)

from rd_pipeline.processing.merge import (
    merge_ocr_results as _merge_ocr_results,
    regenerate_html_from_result,
    regenerate_md_from_result,
    HTMLSegmentParser,
)


class ServerHTMLSegmentParser:
    """Server-specific HTML parser using ocr_html_parser."""

    def build_segments_from_html(
        self,
        html_text: str,
        expected_ids: List[str],
        score_cutoff: int = 90,
    ) -> Tuple[Dict[str, str], Dict[str, dict]]:
        from .ocr_html_parser import build_segments_from_html
        return build_segments_from_html(html_text, expected_ids, score_cutoff=score_cutoff)


# Default server parser
_server_html_parser = ServerHTMLSegmentParser()


def merge_ocr_results(
    annotation_path: Path,
    ocr_html_path: Path,
    output_path: Path,
    r2_prefix: Optional[str] = None,
    r2_public_url: Optional[str] = None,
    score_cutoff: int = 90,
    doc_name: Optional[str] = None,
    job_id: Optional[str] = None,
) -> bool:
    """Server-configured merge_ocr_results."""
    return _merge_ocr_results(
        annotation_path=annotation_path,
        ocr_html_path=ocr_html_path,
        output_path=output_path,
        r2_prefix=r2_prefix,
        r2_public_url=r2_public_url,
        score_cutoff=score_cutoff,
        doc_name=doc_name,
        job_id=job_id,
        html_parser=_server_html_parser,
    )


__all__ = [
    "merge_ocr_results",
    "regenerate_html_from_result",
    "regenerate_md_from_result",
    "ServerHTMLSegmentParser",
]
