"""Functions for working with image OCR data."""

import re
from typing import Any, Dict


def extract_image_ocr_data(data: dict) -> Dict[str, Any]:
    """
    Extract structured data from image block JSON.

    Supports two formats:
    1. Old format: content_summary, detailed_description, clean_ocr_text, key_entities
    2. New format: analysis (with raw_text, personnel, axes etc.), raw_pdfplumber_text

    Returns:
        dict with fields: location, zone_name, grid_lines, content_summary,
        detailed_description, clean_ocr_text, key_entities, raw_text, personnel, axes, etc.
    """
    result = {}

    # Extract analysis if present
    analysis = data.get("analysis", {})
    if isinstance(analysis, dict):
        # New format: raw_text contains ready markdown
        if analysis.get("raw_text"):
            result["raw_text"] = analysis["raw_text"]

        # Organization
        if analysis.get("organization"):
            result["organization"] = analysis["organization"]

        # Personnel
        if analysis.get("personnel"):
            result["personnel"] = analysis["personnel"]

        # Sheet info
        if analysis.get("sheet_info"):
            result["sheet_info"] = analysis["sheet_info"]

        # Project details
        if analysis.get("project_details"):
            result["project_details"] = analysis["project_details"]

        # Axes
        if analysis.get("axes"):
            result["axes"] = analysis["axes"]

        # Sections
        if analysis.get("sections"):
            result["sections"] = analysis["sections"]

        # Notes fragment
        if analysis.get("notes_fragment"):
            result["notes_fragment"] = analysis["notes_fragment"]

    # Raw text from pdfplumber (fallback)
    if data.get("raw_pdfplumber_text"):
        result["raw_pdfplumber_text"] = data["raw_pdfplumber_text"]

    # Old format: extract data from root or analysis
    source = analysis if analysis else data

    # Location
    location = source.get("location")
    if location:
        if isinstance(location, dict):
            result["zone_name"] = location.get("zone_name", "")
            result["grid_lines"] = location.get("grid_lines", "")
        else:
            result["location_text"] = str(location)

    # Descriptions (old format)
    if source.get("content_summary"):
        result["content_summary"] = source["content_summary"]
    if source.get("detailed_description"):
        result["detailed_description"] = source["detailed_description"]

    # Recognized text - normalize
    clean_ocr = source.get("clean_ocr_text", "")
    if clean_ocr:
        clean_ocr = re.sub(r"•\s*", "", clean_ocr)
        clean_ocr = re.sub(r"\s+", " ", clean_ocr).strip()
        result["clean_ocr_text"] = clean_ocr

    # Key entities
    key_entities = source.get("key_entities", [])
    if isinstance(key_entities, list):
        result["key_entities"] = key_entities[:20]  # Max 20

    return result


def is_image_ocr_json(data: dict) -> bool:
    """Check if JSON is image OCR data."""
    if not isinstance(data, dict):
        return False

    # Old fields (for compatibility)
    old_fields = ["content_summary", "detailed_description", "clean_ocr_text"]

    # New fields from new OCR format
    new_fields = ["analysis", "raw_pdfplumber_text", "doc_metadata"]

    # Check old format
    if any(key in data or (data.get("analysis") and key in data["analysis"]) for key in old_fields):
        return True

    # Check new format
    if any(key in data for key in new_fields):
        return True

    return False
