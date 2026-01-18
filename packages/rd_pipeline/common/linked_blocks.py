"""Functions for working with linked blocks (deduplication of IMAGE+TEXT pairs)."""

import logging
import re
from typing import Any, Dict, List, Set

logger = logging.getLogger(__name__)


def _extract_clean_text_from_html(ocr_text: str) -> str:
    """Extract clean text from ocr_text (may be HTML or plain text)."""
    if not ocr_text:
        return ""

    text = ocr_text.strip()
    if not text:
        return ""

    # If HTML - remove tags
    if text.startswith("<") or "<" in text[:100]:
        # Remove HTML tags
        text = re.sub(r"<[^>]+>", " ", text)
        # Decode HTML entities
        text = text.replace("&nbsp;", " ")
        text = text.replace("&amp;", "&")
        text = text.replace("&lt;", "<")
        text = text.replace("&gt;", ">")
        text = text.replace("&quot;", '"')
        text = text.replace("&#39;", "'")

    # Normalize spaces
    text = re.sub(r"\s+", " ", text).strip()
    return text


def build_linked_blocks_index(pages: List) -> Dict[str, Any]:
    """
    Build linked blocks index for deduplication (for Page objects).

    Returns:
        Dict with keys:
        - block_by_id: {block_id -> block}
        - derived_ids: Set[str] - ID of TEXT blocks marked as derived
        - linked_ocr_text: {image_block_id -> clean_ocr_text from linked TEXT block}
    """
    block_by_id: Dict[str, Any] = {}
    derived_ids: Set[str] = set()
    linked_ocr_text: Dict[str, str] = {}

    # Step 1: Build index of all blocks
    for page in pages:
        for block in page.blocks:
            block_by_id[block.id] = block

    # Step 2: Process linked pairs
    processed_pairs: Set[tuple] = set()

    for page in pages:
        for block in page.blocks:
            linked_id = getattr(block, "linked_block_id", None)
            if not linked_id or linked_id not in block_by_id:
                continue

            # Avoid double processing of pair
            pair_key = tuple(sorted([block.id, linked_id]))
            if pair_key in processed_pairs:
                continue
            processed_pairs.add(pair_key)

            linked_block = block_by_id[linked_id]
            block_type = (
                block.block_type.value
                if hasattr(block.block_type, "value")
                else block.block_type
            )
            linked_type = (
                linked_block.block_type.value
                if hasattr(linked_block.block_type, "value")
                else linked_block.block_type
            )

            # Determine IMAGE and TEXT blocks in pair
            if block_type == "image" and linked_type == "text":
                image_block, text_block = block, linked_block
            elif block_type == "text" and linked_type == "image":
                image_block, text_block = linked_block, block
            else:
                continue  # Not IMAGE+TEXT pair

            # Mark TEXT as derived
            derived_ids.add(text_block.id)

            # Extract clean_ocr_text from TEXT block
            text_ocr = getattr(text_block, "ocr_text", None)
            if text_ocr:
                clean_text = _extract_clean_text_from_html(text_ocr)
                if clean_text:
                    linked_ocr_text[image_block.id] = clean_text

    logger.debug(
        f"build_linked_blocks_index: {len(derived_ids)} derived, "
        f"{len(linked_ocr_text)} linked_ocr_text"
    )

    return {
        "block_by_id": block_by_id,
        "derived_ids": derived_ids,
        "linked_ocr_text": linked_ocr_text,
    }


def build_linked_blocks_index_dict(pages: List[Dict]) -> Dict[str, Any]:
    """
    Build linked blocks index for deduplication (for dict structure).

    Returns:
        Dict with keys:
        - block_by_id: {block_id -> block dict}
        - derived_ids: Set[str] - ID of TEXT blocks marked as derived
        - linked_ocr_text: {image_block_id -> clean_ocr_text from linked TEXT block}
    """
    block_by_id: Dict[str, Dict] = {}
    derived_ids: Set[str] = set()
    linked_ocr_text: Dict[str, str] = {}

    # Step 1: Build index of all blocks
    for page in pages:
        for block in page.get("blocks", []):
            block_by_id[block["id"]] = block

    # Step 2: Process linked pairs
    processed_pairs: Set[tuple] = set()

    for page in pages:
        for block in page.get("blocks", []):
            linked_id = block.get("linked_block_id")
            if not linked_id or linked_id not in block_by_id:
                continue

            pair_key = tuple(sorted([block["id"], linked_id]))
            if pair_key in processed_pairs:
                continue
            processed_pairs.add(pair_key)

            linked_block = block_by_id[linked_id]
            block_type = block.get("block_type", "text")
            linked_type = linked_block.get("block_type", "text")

            if block_type == "image" and linked_type == "text":
                image_block, text_block = block, linked_block
            elif block_type == "text" and linked_type == "image":
                image_block, text_block = linked_block, block
            else:
                continue

            derived_ids.add(text_block["id"])

            # Extract text from TEXT block
            text_ocr = text_block.get("ocr_text", "")
            if text_ocr:
                clean_text = _extract_clean_text_from_html(text_ocr)
                if clean_text:
                    linked_ocr_text[image_block["id"]] = clean_text

    logger.debug(
        f"build_linked_blocks_index_dict: {len(derived_ids)} derived, "
        f"{len(linked_ocr_text)} linked_ocr_text"
    )

    return {
        "block_by_id": block_by_id,
        "derived_ids": derived_ids,
        "linked_ocr_text": linked_ocr_text,
    }
