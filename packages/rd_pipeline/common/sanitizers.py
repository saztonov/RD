"""Functions for cleaning Markdown from OCR artifacts."""

import re

# Pattern for markdown links to garbage images [img:hash_img]
DATALAB_MD_IMG_PATTERN = re.compile(r'\[img:[a-f0-9]{20,}_img\]')


def sanitize_markdown(md: str) -> str:
    """
    Clean Markdown from datalab OCR artifacts.

    Removes links like [img:hash_img].
    """
    if not md:
        return ""

    # Remove garbage markdown image links
    text = DATALAB_MD_IMG_PATTERN.sub("", md)

    # Remove empty lines after removal
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()
