"""Utilities for working with blocks."""

from typing import Dict, List

from rd_domain.ids import is_armor_id, uuid_to_armor_id


def get_block_armor_id(block_id: str) -> str:
    """
    Get armor ID for block.

    New blocks already have ID in format XXXX-XXXX-XXX.
    For legacy UUID blocks - convert to armor format.
    """
    if is_armor_id(block_id):
        return block_id
    return uuid_to_armor_id(block_id)


def collect_block_groups(pages: List) -> Dict[str, List]:
    """Collect blocks by groups."""
    groups: Dict[str, List] = {}
    for page in pages:
        for block in page.blocks:
            group_id = getattr(block, "group_id", None)
            if group_id:
                if group_id not in groups:
                    groups[group_id] = []
                groups[group_id].append(block)
    return groups
