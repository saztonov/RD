"""
Annotation save/load module.
Works with JSON files for saving/loading annotations.json
"""

import json
import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

from rd_domain.models import Document
from rd_domain.utils import get_moscow_time_str

logger = logging.getLogger(__name__)


# Current annotation format version
ANNOTATION_FORMAT_VERSION = 2

# Required block fields
REQUIRED_BLOCK_FIELDS = {"id", "page_index", "coords_px", "block_type"}
# Fields added in v2
V2_BLOCK_FIELDS = {"coords_norm", "source", "shape_type", "created_at"}


@dataclass
class MigrationResult:
    """Annotation migration result."""

    success: bool
    migrated: bool  # True if format was changed
    errors: List[str]  # Critical errors
    warnings: List[str]  # Warnings about restored fields

    @property
    def needs_save(self) -> bool:
        """Whether file needs to be re-saved."""
        return self.success and self.migrated


def validate_annotation_structure(data: dict) -> Tuple[bool, List[str]]:
    """
    Validate basic annotation structure.

    Returns:
        (is_valid, errors)
    """
    errors = []

    if not isinstance(data, dict):
        return False, ["Annotation must be a JSON object"]

    if "pdf_path" not in data:
        errors.append("Missing field 'pdf_path'")

    if "pages" not in data:
        errors.append("Missing field 'pages'")
    elif not isinstance(data["pages"], list):
        errors.append("Field 'pages' must be an array")
    else:
        for i, page in enumerate(data["pages"]):
            if not isinstance(page, dict):
                errors.append(f"Page {i} must be an object")
                continue
            if "blocks" in page and not isinstance(page["blocks"], list):
                errors.append(f"Blocks of page {i} must be an array")

    return len(errors) == 0, errors


def detect_annotation_version(data: dict) -> int:
    """
    Detect annotation format version.

    v1: Old format (no coords_norm, source)
    v2: Current format (all required fields)
    """
    if "format_version" in data:
        return data["format_version"]

    # Check first block to determine version
    for page in data.get("pages", []):
        for block in page.get("blocks", []):
            # v2 has coords_norm and source
            if "coords_norm" in block and "source" in block:
                return 2
            # If blocks without these fields exist - it's v1
            return 1

    # Empty document - consider current
    return ANNOTATION_FORMAT_VERSION


def migrate_block_v1_to_v2(
    block: dict, page_width: int, page_height: int
) -> Tuple[dict, List[str]]:
    """
    Migrate block from v1 to v2.

    Returns:
        (migrated_block, warnings)
    """
    warnings = []
    migrated = block.copy()

    # Add source if missing
    if "source" not in migrated:
        migrated["source"] = "user"
        warnings.append(f"Block {block.get('id', '?')}: added source='user'")

    # Add shape_type if missing
    if "shape_type" not in migrated:
        migrated["shape_type"] = "rectangle"

    # Add created_at if missing
    if "created_at" not in migrated:
        migrated["created_at"] = get_moscow_time_str()

    # Calculate coords_norm if missing
    if "coords_norm" not in migrated:
        coords_px = migrated.get("coords_px", [0, 0, 100, 100])
        if page_width > 0 and page_height > 0:
            migrated["coords_norm"] = [
                coords_px[0] / page_width,
                coords_px[1] / page_height,
                coords_px[2] / page_width,
                coords_px[3] / page_height,
            ]
            warnings.append(f"Block {block.get('id', '?')}: calculated coords_norm")
        else:
            # Fallback - normalized coordinates 0..1
            migrated["coords_norm"] = [0.0, 0.0, 0.1, 0.1]
            warnings.append(
                f"Block {block.get('id', '?')}: coords_norm set to default (no page dimensions)"
            )

    return migrated, warnings


def migrate_annotation_data(data: dict) -> Tuple[dict, MigrationResult]:
    """
    Migrate annotation to current format.

    Returns:
        (migrated_data, result)
    """
    # Validate basic structure
    is_valid, errors = validate_annotation_structure(data)
    if not is_valid:
        return data, MigrationResult(
            success=False, migrated=False, errors=errors, warnings=[]
        )

    version = detect_annotation_version(data)

    # Already current version
    if version >= ANNOTATION_FORMAT_VERSION:
        return data, MigrationResult(
            success=True, migrated=False, errors=[], warnings=[]
        )

    # Migration v1 -> v2
    all_warnings = []
    migrated_data = data.copy()
    migrated_data["format_version"] = ANNOTATION_FORMAT_VERSION
    migrated_pages = []

    for page in data.get("pages", []):
        page_width = page.get("width", 0)
        page_height = page.get("height", 0)

        migrated_page = page.copy()
        migrated_blocks = []

        for block in page.get("blocks", []):
            # Check required fields
            missing = REQUIRED_BLOCK_FIELDS - set(block.keys())
            if missing:
                all_warnings.append(f"Block skipped - missing fields: {missing}")
                continue

            migrated_block, warnings = migrate_block_v1_to_v2(
                block, page_width, page_height
            )
            migrated_blocks.append(migrated_block)
            all_warnings.extend(warnings)

        migrated_page["blocks"] = migrated_blocks
        migrated_pages.append(migrated_page)

    migrated_data["pages"] = migrated_pages

    logger.info(f"Annotation migrated v{version} -> v{ANNOTATION_FORMAT_VERSION}")

    return migrated_data, MigrationResult(
        success=True, migrated=True, errors=[], warnings=all_warnings
    )


class AnnotationIO:
    """Class for working with annotations (load, save, migrate)."""

    @staticmethod
    def save_annotation(document: Document, file_path: str) -> None:
        """
        Save Document annotation to JSON.

        Args:
            document: Document instance
            file_path: path to output JSON file
        """
        try:
            data = document.to_dict()
            data["format_version"] = ANNOTATION_FORMAT_VERSION
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"Annotation saved: {file_path}")
        except Exception as e:
            logger.error(f"Error saving annotation: {e}")
            raise

    @staticmethod
    def load_annotation(
        file_path: str, migrate_ids: bool = True
    ) -> tuple[Optional[Document], bool]:
        """
        Load Document annotation from JSON.

        Args:
            file_path: path to JSON file
            migrate_ids: migrate legacy UUID to armor ID format

        Returns:
            (Document, was_migrated) - document and ID migration flag
        """
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            doc, was_migrated = Document.from_dict(data, migrate_ids)
            logger.info(
                f"Annotation loaded: {file_path}"
                + (" (IDs migrated)" if was_migrated else "")
            )
            return doc, was_migrated
        except Exception as e:
            logger.error(f"Error loading annotation: {e}")
            return None, False

    @staticmethod
    def load_and_migrate(file_path: str) -> Tuple[Optional[Document], MigrationResult]:
        """
        Load annotation with automatic format migration.

        Args:
            file_path: path to JSON file

        Returns:
            (Document, MigrationResult)
        """
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            return None, MigrationResult(
                success=False,
                migrated=False,
                errors=[f"JSON parse error: {e}"],
                warnings=[],
            )
        except Exception as e:
            return None, MigrationResult(
                success=False,
                migrated=False,
                errors=[f"File read error: {e}"],
                warnings=[],
            )

        # Migrate data
        migrated_data, result = migrate_annotation_data(data)

        if not result.success:
            return None, result

        # Convert to Document (with ID migration)
        try:
            doc, ids_migrated = Document.from_dict(migrated_data, migrate_ids=True)

            # If IDs were migrated - this is also migration
            if ids_migrated and not result.migrated:
                result = MigrationResult(
                    success=True,
                    migrated=True,
                    errors=[],
                    warnings=result.warnings + ["Block IDs migrated to armor format"],
                )

            return doc, result
        except Exception as e:
            return None, MigrationResult(
                success=False,
                migrated=False,
                errors=[f"Error converting to Document: {e}"],
                warnings=result.warnings,
            )
