"""Functions for cleaning HTML and Markdown from OCR artifacts."""

import re

# Pattern for garbage img tags from datalab (hash_img.ext)
DATALAB_IMG_PATTERN = re.compile(
    r'<img[^>]*src=["\']?[a-f0-9]{20,}_img(?:\.[a-z]{3,4})?["\']?[^>]*/?>',
    re.IGNORECASE
)

# Pattern for markdown links to garbage images [img:hash_img]
DATALAB_MD_IMG_PATTERN = re.compile(r'\[img:[a-f0-9]{20,}_img\]')


def sanitize_html(html: str) -> str:
    """
    Clean HTML from datalab OCR artifacts.

    1. Remove garbage img tags (hash_img.jpg)
    2. Remove orphan closing tags at start
    3. Remove unclosed opening tags at end
    4. Remove nested DOCTYPE/html/body artifacts
    5. Remove closing </p> without corresponding opening <p>
    """
    if not html:
        return ""

    text = html

    # 1. Remove garbage img tags from datalab
    text = DATALAB_IMG_PATTERN.sub("", text)

    # 2. Remove nested DOCTYPE/html/head/body artifacts (sometimes inside blocks)
    text = re.sub(r'<!DOCTYPE\s+html[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<html[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</html\s*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<head[^>]*>.*?</head\s*>', '', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<body[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</body\s*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<div\s+class="page"[^>]*>', '', text, flags=re.IGNORECASE)

    # 3. Remove orphan closing tags at start (may repeat)
    while True:
        new_text = re.sub(r'^\s*</[a-z]+>\s*', '', text, flags=re.IGNORECASE)
        if new_text == text:
            break
        text = new_text

    # 4. Remove unclosed opening tags at end
    text = re.sub(r'\s*<p>\s*$', '', text)
    text = re.sub(r'\s*<div[^>]*>\s*$', '', text)

    # 5. Remove "hanging" </p> tags - those without preceding <p>
    def remove_orphan_closing_p(html_text: str) -> str:
        """Remove </p> tags without corresponding <p>."""
        result = []
        parts = re.split(r'(</p>)', html_text, flags=re.IGNORECASE)
        open_count = 0

        for part in parts:
            if re.match(r'</p>', part, re.IGNORECASE):
                if open_count > 0:
                    result.append(part)
                    open_count -= 1
                # else: skip "hanging" </p>
            else:
                # Count opening <p> in this part
                open_count += len(re.findall(r'<p\b[^>]*>', part, re.IGNORECASE))
                result.append(part)

        return ''.join(result)

    text = remove_orphan_closing_p(text)

    # 6. Remove unclosed <p> at end
    while True:
        open_p = len(re.findall(r'<p\b[^>]*>', text, re.IGNORECASE))
        close_p = len(re.findall(r'</p>', text, re.IGNORECASE))
        if open_p <= close_p:
            break
        # Remove last unclosed <p>
        text = re.sub(r'<p\b[^>]*>(?!.*<p\b)', '', text, flags=re.DOTALL | re.IGNORECASE)

    # 7. Remove empty tags
    text = re.sub(r'<p>\s*</p>', '', text, flags=re.IGNORECASE)

    # 8. Normalize multiple empty lines
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()


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
