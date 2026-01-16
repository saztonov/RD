"""Functions for working with document stamps."""

import json as json_module
import re
from collections import Counter
from typing import Dict, List, Optional

# Stamp fields inherited to pages without stamp
INHERITABLE_STAMP_FIELDS = ("document_code", "project_name", "stage", "organization")


def parse_stamp_json(ocr_text: Optional[str]) -> Optional[Dict]:
    """Extract stamp JSON from ocr_text."""
    if not ocr_text:
        return None

    text = ocr_text.strip()
    if not text:
        return None

    # Direct JSON
    if text.startswith("{"):
        try:
            return json_module.loads(text)
        except json_module.JSONDecodeError:
            pass

    # JSON inside ```json ... ```
    json_match = re.search(r"```json\s*([\s\S]*?)\s*```", text)
    if json_match:
        try:
            return json_module.loads(json_match.group(1))
        except json_module.JSONDecodeError:
            pass

    return None


def find_page_stamp(blocks: List) -> Optional[Dict]:
    """Find stamp data on page (from block with category_code='stamp')."""
    for block in blocks:
        if getattr(block, "category_code", None) == "stamp":
            stamp_data = parse_stamp_json(block.ocr_text)
            if stamp_data:
                return stamp_data
    return None


def collect_inheritable_stamp_data(pages: List) -> Optional[Dict]:
    """
    Collect common stamp fields from all pages.
    For each field, the most frequent value is selected (mode).
    """
    field_values: Dict[str, List] = {field: [] for field in INHERITABLE_STAMP_FIELDS}

    for page in pages:
        stamp_data = find_page_stamp(page.blocks)
        if stamp_data:
            for field in INHERITABLE_STAMP_FIELDS:
                val = stamp_data.get(field)
                if val:
                    field_values[field].append(val)

    inherited = {}
    for field in INHERITABLE_STAMP_FIELDS:
        values = field_values[field]
        if values:
            counter = Counter(values)
            most_common = counter.most_common(1)[0][0]
            inherited[field] = most_common

    return inherited if inherited else None


def format_stamp_parts(stamp_data: Dict) -> List[tuple]:
    """
    Extract stamp parts for formatting.

    Returns:
        List of tuples (key, value) for formatting.
    """
    parts = []

    if stamp_data.get("document_code"):
        parts.append(("Code", stamp_data["document_code"]))
    if stamp_data.get("stage"):
        parts.append(("Stage", stamp_data["stage"]))

    # Sheet
    sheet_num = stamp_data.get("sheet_number", "")
    total = stamp_data.get("total_sheets", "")
    if sheet_num or total:
        sheet_str = f"{sheet_num} (of {total})" if total else str(sheet_num)
        parts.append(("Sheet", sheet_str))

    if stamp_data.get("project_name"):
        parts.append(("Project", stamp_data["project_name"]))
    if stamp_data.get("sheet_name"):
        parts.append(("Name", stamp_data["sheet_name"]))
    if stamp_data.get("organization"):
        parts.append(("Organization", stamp_data["organization"]))

    # Revisions/changes
    revisions = stamp_data.get("revisions")
    if revisions:
        if isinstance(revisions, list) and revisions:
            last_rev = revisions[-1] if revisions else {}
            rev_num = last_rev.get("revision_number", "")
            doc_num = last_rev.get("document_number", "")
            rev_date = last_rev.get("date", "")
            if rev_num or doc_num:
                rev_str = f"Rev. {rev_num}"
                if doc_num:
                    rev_str += f" (Doc. # {doc_num}"
                    if rev_date:
                        rev_str += f" dated {rev_date}"
                    rev_str += ")"
                parts.append(("Status", rev_str))
        elif isinstance(revisions, str):
            parts.append(("Status", revisions))

    # Signatures
    signatures = stamp_data.get("signatures")
    if signatures:
        if isinstance(signatures, list):
            sig_parts = []
            for sig in signatures:
                if isinstance(sig, dict):
                    role = sig.get("role", "")
                    name = sig.get("name", "")
                    if role and name:
                        sig_parts.append(f"{role}: {name}")
                elif isinstance(sig, str):
                    sig_parts.append(sig)
            if sig_parts:
                parts.append(("Responsible", "; ".join(sig_parts)))
        elif isinstance(signatures, str):
            parts.append(("Responsible", signatures))

    return parts


# =============================================================================
# Functions for working with dict (used in result.json / ocr_result_merger)
# =============================================================================


def find_page_stamp_dict(page: Dict) -> Optional[Dict]:
    """Find stamp JSON on page (for dict structure)."""
    for blk in page.get("blocks", []):
        if blk.get("block_type") == "image" and blk.get("category_code") == "stamp":
            return blk.get("ocr_json")
    return None


def collect_inheritable_stamp_data_dict(pages: List[Dict]) -> Optional[Dict]:
    """
    Collect common stamp fields from all pages (for dict structure).
    For each field, the most frequent value is selected (mode).
    """
    field_values: Dict[str, List] = {field: [] for field in INHERITABLE_STAMP_FIELDS}

    for page in pages:
        stamp_json = find_page_stamp_dict(page)
        if stamp_json:
            for field in INHERITABLE_STAMP_FIELDS:
                val = stamp_json.get(field)
                if val:
                    field_values[field].append(val)

    inherited = {}
    for field in INHERITABLE_STAMP_FIELDS:
        values = field_values[field]
        if values:
            counter = Counter(values)
            most_common = counter.most_common(1)[0][0]
            inherited[field] = most_common

    return inherited if inherited else None


def propagate_stamp_data(page: Dict, inherited_data: Optional[Dict] = None) -> None:
    """
    Propagate stamp data to all blocks on page.
    If page has stamp - merge it with inherited_data.
    If no stamp - use inherited_data.
    """
    blocks = page.get("blocks", [])
    stamp_json = find_page_stamp_dict(page)

    if stamp_json:
        merged = dict(stamp_json)
        if inherited_data:
            for field in INHERITABLE_STAMP_FIELDS:
                if not merged.get(field):
                    if inherited_data.get(field):
                        merged[field] = inherited_data[field]
        for blk in blocks:
            blk["stamp_data"] = merged
    elif inherited_data:
        for blk in blocks:
            blk["stamp_data"] = inherited_data
