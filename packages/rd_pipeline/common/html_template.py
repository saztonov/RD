"""HTML templates for OCR result generators."""

from datetime import datetime

# HTML template (common for all generators)
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - OCR</title>
    <style>
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 2rem; line-height: 1.6; }}
        .block {{ margin: 1.5rem 0; padding: 1rem; border-left: 3px solid #3498db; background: #f8f9fa; }}
        .block-header {{ font-size: 0.8rem; color: #666; margin-bottom: 0.5rem; }}
        .block-content {{ }}
        .block-type-text {{ border-left-color: #2ecc71; }}
        .block-type-table {{ border-left-color: #e74c3c; }}
        .block-type-image {{ border-left-color: #9b59b6; }}
        .block-content h3 {{ color: #555; font-size: 1rem; margin: 1rem 0 0.5rem 0; padding-bottom: 0.3rem; border-bottom: 1px solid #ddd; }}
        .block-content p {{ margin: 0.5rem 0; }}
        .block-content code {{ background: #e8f4f8; padding: 0.2rem 0.4rem; margin: 0.2rem; border-radius: 3px; display: inline-block; font-family: 'Consolas', 'Courier New', monospace; font-size: 0.9em; }}
        .stamp-info {{ font-size: 0.75rem; color: #2980b9; background: #eef6fc; padding: 0.4rem 0.6rem; margin-top: 0.5rem; border-radius: 3px; border: 1px solid #bde0f7; }}
        .stamp-inherited {{ color: #7f8c8d; background: #f5f5f5; border-color: #ddd; font-style: italic; }}
        table {{ border-collapse: collapse; width: 100%; margin: 0.5rem 0; }}
        th, td {{ border: 1px solid #ddd; padding: 0.5rem; text-align: left; }}
        th {{ background: #f0f0f0; }}
        img {{ max-width: 100%; height: auto; }}
        h1 {{ color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 0.5rem; }}
        pre {{ white-space: pre-wrap; word-wrap: break-word; background: #fff; padding: 0.5rem; }}
    </style>
</head>
<body>
<h1>{title}</h1>
<p>Generated: {timestamp} UTC</p>
"""

HTML_FOOTER = "</body></html>"


def get_html_header(title: str) -> str:
    """Get HTML header with template."""
    return HTML_TEMPLATE.format(
        title=title,
        timestamp=datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    )
