"""OCR result merging: annotation.json + ocr_result.html -> result.json

Server-specific HTML parsing is passed via callbacks.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from copy import deepcopy
from pathlib import Path
from typing import Callable, Dict, List, Optional, Protocol, Tuple

from rd_pipeline.common import (
    HTML_FOOTER,
    INHERITABLE_STAMP_FIELDS,
    build_linked_blocks_index_dict,
    collect_inheritable_stamp_data_dict,
    format_stamp_parts,
    get_block_armor_id,
    get_html_header,
    parse_stamp_json,
    propagate_stamp_data,
    sanitize_html,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Protocol for HTML parsing (server-specific)
# ============================================================================

class HTMLSegmentParser(Protocol):
    """Protocol for parsing HTML into segments per block."""

    def build_segments_from_html(
        self,
        html_text: str,
        expected_ids: List[str],
        score_cutoff: int = 90,
    ) -> Tuple[Dict[str, str], Dict[str, dict]]:
        """
        Parse HTML into segments per block.

        Returns:
            segments: dict[block_id -> html_fragment]
            meta: dict[block_id -> {method, match_score, marker_text_sample}]
        """
        ...


class DefaultHTMLSegmentParser:
    """Default parser that returns empty results."""

    def build_segments_from_html(
        self,
        html_text: str,
        expected_ids: List[str],
        score_cutoff: int = 90,
    ) -> Tuple[Dict[str, str], Dict[str, dict]]:
        return {}, {}


# ============================================================================
# Main merge function
# ============================================================================

def _build_crop_url(block_id: str, r2_public_url: str, r2_prefix: str) -> str:
    """Build crop URL for block using actual r2_prefix."""
    return f"{r2_public_url}/{r2_prefix}/crops/{block_id}.pdf"


def merge_ocr_results(
    annotation_path: Path,
    ocr_html_path: Path,
    output_path: Path,
    r2_prefix: Optional[str] = None,
    r2_public_url: Optional[str] = None,
    score_cutoff: int = 90,
    doc_name: Optional[str] = None,
    job_id: Optional[str] = None,
    html_parser: Optional[HTMLSegmentParser] = None,
) -> bool:
    """
    Merge annotation.json and ocr_result.html into result.json.

    Adds to each block:
    - ocr_html: HTML fragment of block
    - ocr_json: parsed JSON from ocr_text (for IMAGE blocks)
    - crop_url: link to crop (for IMAGE blocks)
    - ocr_meta: {method, match_score, marker_text_sample}

    Adds OCR run metadata:
    - ocr_run_id: Job ID
    - annotation_sha256: hash of source annotation
    - schema_version: result schema version

    Returns:
        True if successful, False on error
    """
    parser = html_parser or DefaultHTMLSegmentParser()

    if not r2_public_url:
        r2_public_url = os.getenv("R2_PUBLIC_URL", "https://rd1.svarovsky.ru")

    try:
        if not annotation_path.exists():
            logger.warning(f"annotation.json not found: {annotation_path}")
            return False

        if not ocr_html_path.exists():
            logger.warning(f"ocr_result.html not found: {ocr_html_path}")
            return False

        with open(annotation_path, "r", encoding="utf-8") as f:
            ann = json.load(f)

        expected_ids = [
            b["id"] for p in ann.get("pages", []) for b in p.get("blocks", [])
        ]

        if not expected_ids:
            logger.info("No blocks to process")
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(ann, f, ensure_ascii=False, indent=2)
            return True

        with open(ocr_html_path, "r", encoding="utf-8") as f:
            html_text = f.read()

        segments, meta = parser.build_segments_from_html(
            html_text, expected_ids, score_cutoff=score_cutoff
        )

        result = deepcopy(ann)

        # Add OCR run metadata
        if job_id:
            result["ocr_run_id"] = job_id
        result["schema_version"] = "1.0"
        with open(annotation_path, "rb") as f:
            result["annotation_sha256"] = hashlib.sha256(f.read()).hexdigest()

        missing = []
        matched = 0

        for page in result.get("pages", []):
            # Convert page_number to 1-based for external format
            if "page_number" in page:
                page["page_number"] = page["page_number"] + 1
            for blk in page.get("blocks", []):
                bid = blk["id"]
                block_type = blk.get("block_type", "text")

                # Convert page_index to 1-based for external format
                if "page_index" in blk:
                    blk["page_index"] = blk["page_index"] + 1

                # HTML fragment (sanitize from datalab artifacts)
                raw_html = segments.get(bid, "")
                blk["ocr_html"] = sanitize_html(raw_html) if raw_html else ""
                blk["ocr_meta"] = meta.get(
                    bid, {"method": [], "match_score": 0.0, "marker_text_sample": ""}
                )

                # For IMAGE blocks: parse JSON from ocr_text and add crop_url
                if block_type == "image":
                    ocr_text = blk.get("ocr_text", "")
                    parsed_json = parse_stamp_json(ocr_text)
                    if parsed_json:
                        blk["ocr_json"] = parsed_json

                    # Add link to crop (except stamps)
                    if blk.get("category_code") != "stamp":
                        if r2_prefix:
                            blk["crop_url"] = _build_crop_url(
                                bid, r2_public_url, r2_prefix
                            )
                        elif blk.get("image_file"):
                            crop_name = Path(blk["image_file"]).name
                            blk["crop_url"] = f"{r2_public_url}/crops/{crop_name}"

                if blk["ocr_html"]:
                    matched += 1
                else:
                    missing.append(bid)

        # Mark linked blocks for deduplication (export_mode="qa")
        linked_index = build_linked_blocks_index_dict(result.get("pages", []))
        for page in result.get("pages", []):
            for blk in page.get("blocks", []):
                bid = blk["id"]
                if bid in linked_index["derived_ids"]:
                    blk["derived"] = True
                linked_text = linked_index["linked_ocr_text"].get(bid)
                if linked_text:
                    blk["linked_block_clean_ocr_text"] = linked_text

        if linked_index["derived_ids"]:
            logger.info(
                f"Linked blocks: {len(linked_index['derived_ids'])} derived, "
                f"{len(linked_index['linked_ocr_text'])} with linked_ocr_text"
            )

        # Collect common stamp data
        inherited_stamp = collect_inheritable_stamp_data_dict(result.get("pages", []))

        # Propagate stamp data
        for page in result.get("pages", []):
            propagate_stamp_data(page, inherited_stamp)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        if missing:
            logger.warning(
                f"HTML not found for {len(missing)} blocks. Examples: {missing[:3]}"
            )

        logger.info(
            f"result.json saved: {output_path} ({matched}/{len(expected_ids)} blocks matched)"
        )

        # Regenerate HTML from split ocr_html
        regenerate_html_from_result(result, ocr_html_path, doc_name=doc_name)

        # Regenerate MD from split ocr_html (with linked blocks deduplication)
        md_path = output_path.parent / "document.md"
        regenerate_md_from_result(result, md_path, doc_name=doc_name)

        return True

    except Exception as e:
        logger.error(f"Error merging OCR results: {e}", exc_info=True)
        return False


def regenerate_md_from_result(
    result: dict,
    output_path: Path,
    doc_name: Optional[str] = None,
) -> None:
    """Regenerate Markdown file from result.json."""
    from rd_pipeline.output.md_generator import generate_md_from_result

    try:
        generate_md_from_result(result, output_path, doc_name=doc_name)
    except Exception as e:
        logger.warning(f"Error regenerating MD: {e}")


def regenerate_html_from_result(
    result: dict, output_path: Path, doc_name: Optional[str] = None
) -> None:
    """
    Regenerate HTML file from result.json with properly split blocks.
    Uses ocr_html (already split by markers) instead of ocr_text.
    Linked TEXT blocks (derived) are skipped, their text is added to IMAGE blocks.
    """
    if not doc_name:
        doc_name = result.get("pdf_path", "OCR Result")

    # Build linked blocks index for deduplication
    linked_index = build_linked_blocks_index_dict(result.get("pages", []))

    # Use common HTML template
    html_parts = [get_html_header(doc_name)]

    block_count = 0
    for page in result.get("pages", []):
        page_num = page.get("page_number", "")

        for idx, blk in enumerate(page.get("blocks", [])):
            # Skip stamp blocks
            if blk.get("category_code") == "stamp":
                continue

            block_id = blk.get("id", "")

            # Skip derived blocks (linked TEXT blocks)
            if block_id in linked_index["derived_ids"]:
                continue

            block_type = blk.get("block_type", "text")
            ocr_html = blk.get("ocr_html", "")
            stamp_data = blk.get("stamp_data")
            created_at = blk.get("created_at")

            # Block is displayed if there's content OR metadata
            if not ocr_html and not stamp_data and not created_at:
                continue

            block_count += 1

            html_parts.append(f'<div class="block block-type-{block_type}">')
            html_parts.append(
                f'<div class="block-header">Block #{idx + 1} (page {page_num}) | Type: {block_type}</div>'
            )
            html_parts.append('<div class="block-content">')
            html_parts.append(f"<p>BLOCK: {block_id}</p>")

            # Linked block - to header
            linked_id = blk.get("linked_block_id")
            if linked_id:
                linked_armor = get_block_armor_id(linked_id)
                html_parts.append(f"<p><b>Linked block:</b> {linked_armor}</p>")

            # Created - to header
            if created_at:
                html_parts.append(f"<p><b>Created:</b> {created_at}</p>")

            # Stamp info - to header
            if stamp_data:
                parts = format_stamp_parts(stamp_data)
                if parts:
                    stamp_html_parts = [f"<b>{key}:</b> {value}" for key, value in parts]
                    html_parts.append(
                        '<div class="stamp-info">' + " | ".join(stamp_html_parts) + "</div>"
                    )

            # For IMAGE blocks add link to crop
            if block_type == "image" and blk.get("crop_url"):
                if "Open image crop" not in ocr_html:
                    crop_url = blk["crop_url"]
                    html_parts.append(
                        f'<p><a href="{crop_url}" target="_blank"><b>Open image crop</b></a></p>'
                    )

            # Sanitize HTML from datalab garbage artifacts
            if ocr_html:
                html_parts.append(sanitize_html(ocr_html))

            # Add linked_block_clean_ocr_text for IMAGE blocks
            linked_text = linked_index["linked_ocr_text"].get(block_id)
            if linked_text:
                html_parts.append(
                    f"<p><b>Text from linked block:</b> {linked_text}</p>"
                )

            html_parts.append("</div></div>")

    html_parts.append(HTML_FOOTER)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(html_parts))

    logger.info(
        f"HTML regenerated from result.json: {output_path} ({block_count} blocks)"
    )
