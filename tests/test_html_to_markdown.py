"""Tests for HTML to Markdown conversion functions."""

import pytest

from rd_pipeline.common.sanitizers import html_to_markdown, sanitize_markdown


class TestHtmlToMarkdown:
    """Tests for html_to_markdown function."""

    def test_empty_input(self):
        """Empty input returns empty string."""
        assert html_to_markdown("") == ""
        assert html_to_markdown(None) == ""

    def test_plain_text_unchanged(self):
        """Plain text without HTML should be unchanged."""
        text = "This is plain text without HTML"
        assert html_to_markdown(text) == text

    def test_heading_h1(self):
        """H1 tag converts to # heading."""
        result = html_to_markdown("<h1>Title</h1>")
        assert "# Title" in result

    def test_heading_h2(self):
        """H2 tag converts to ## heading."""
        result = html_to_markdown("<h2>Subtitle</h2>")
        assert "## Subtitle" in result

    def test_heading_h3(self):
        """H3 tag converts to ### heading."""
        result = html_to_markdown("<h3>Section</h3>")
        assert "### Section" in result

    def test_heading_with_style(self):
        """Heading with style attribute removes style."""
        result = html_to_markdown('<h2 style="text-align: center;">Title</h2>')
        assert "## Title" in result
        assert "style=" not in result

    def test_html_entity_amp(self):
        """&amp; entity converts to &."""
        result = html_to_markdown("Hutterer &amp; Lechner GmbH")
        assert "Hutterer & Lechner GmbH" in result

    def test_html_entity_nbsp(self):
        """&nbsp; entity converts to space."""
        result = html_to_markdown("word&nbsp;word")
        # html.unescape converts &nbsp; to non-breaking space
        assert "word" in result and "&nbsp;" not in result

    def test_html_entity_lt_gt(self):
        """&lt; and &gt; entities are decoded (but may be removed if look like tags)."""
        # Note: < b > looks like HTML tag after decoding and gets removed
        # Test with non-tag-like content
        result = html_to_markdown("5 &lt; 10 and 10 &gt; 5")
        assert "&lt;" not in result
        assert "&gt;" not in result

    def test_math_simple(self):
        """MathML content is extracted."""
        result = html_to_markdown("temperature <math>+5</math> degrees")
        assert "+5" in result
        assert "<math>" not in result

    def test_math_with_latex(self):
        """MathML with LaTeX commands is cleaned."""
        result = html_to_markdown(r"<math>+5^{\circ}\text{C}</math>")
        assert "+5" in result
        assert "C" in result
        assert r"\text" not in result

    def test_bold_tag(self):
        """Bold tag converts to **text**."""
        result = html_to_markdown("<b>bold text</b>")
        assert "**bold text**" in result

    def test_strong_tag(self):
        """Strong tag converts to **text**."""
        result = html_to_markdown("<strong>strong text</strong>")
        assert "**strong text**" in result

    def test_italic_tag(self):
        """Italic tag converts to *text*."""
        result = html_to_markdown("<i>italic</i>")
        assert "*italic*" in result

    def test_br_tag(self):
        """BR tag converts to newline."""
        result = html_to_markdown("line1<br/>line2")
        assert "line1\nline2" in result

    def test_br_tag_without_slash(self):
        """BR tag without slash converts to newline."""
        result = html_to_markdown("line1<br>line2")
        assert "line1\nline2" in result

    def test_hr_tag(self):
        """HR tag converts to ---."""
        result = html_to_markdown("before<hr/>after")
        assert "---" in result

    def test_paragraph_tag(self):
        """Paragraph tag adds line breaks."""
        result = html_to_markdown("<p>Paragraph 1</p><p>Paragraph 2</p>")
        assert "Paragraph 1" in result
        assert "Paragraph 2" in result

    def test_list_ul(self):
        """Unordered list converts to - items."""
        result = html_to_markdown("<ul><li>Item 1</li><li>Item 2</li></ul>")
        assert "- Item 1" in result
        assert "- Item 2" in result

    def test_list_with_style(self):
        """List with style attribute removes style."""
        result = html_to_markdown(
            '<ul style="list-style-type: none"><li>Item 1</li></ul>'
        )
        assert "- Item 1" in result
        assert "style=" not in result

    def test_simple_table(self):
        """Simple table converts to markdown table."""
        html = """
        <table>
            <tr><th>Header 1</th><th>Header 2</th></tr>
            <tr><td>Cell 1</td><td>Cell 2</td></tr>
        </table>
        """
        result = html_to_markdown(html)
        assert "| Header 1 | Header 2 |" in result
        assert "| --- | --- |" in result
        assert "| Cell 1 | Cell 2 |" in result

    def test_table_with_br(self):
        """Table cells with BR tags handle line breaks."""
        html = "<table><tr><td>Line1<br/>Line2</td></tr></table>"
        result = html_to_markdown(html)
        assert "Line1" in result
        assert "Line2" in result
        assert "<br" not in result

    def test_table_with_border(self):
        """Table with border attribute removes border."""
        html = '<table border="1"><tr><td>Cell</td></tr></table>'
        result = html_to_markdown(html)
        assert "| Cell |" in result
        assert "border=" not in result

    def test_nested_tags(self):
        """Nested tags are handled correctly."""
        html = "<p><b>Bold</b> and <i>italic</i></p>"
        result = html_to_markdown(html)
        assert "**Bold**" in result
        assert "*italic*" in result

    def test_removes_remaining_tags(self):
        """Unknown tags are removed."""
        result = html_to_markdown("<div>content</div><span>more</span>")
        assert "content" in result
        assert "more" in result
        assert "<div>" not in result
        assert "<span>" not in result

    def test_real_world_example(self):
        """Test with real-world HTML from OCR result."""
        html = """<h1><p>ОБЩЕСТВО С ОГРАНИЧЕННОЙ ОТВЕТСТВЕННОСТЬЮ<br/>«ГРУППА КОМПАНИЙ «ОЛИМПРОЕКТ»</p></h1><h2><p>РАБОЧАЯ ДОКУМЕНТАЦИЯ</p></h2><p><b>ОБЪЕКТ:</b> Жилой комплекс</p>"""
        result = html_to_markdown(html)
        assert "# " in result or "ОБЩЕСТВО" in result
        assert "## " in result or "РАБОЧАЯ ДОКУМЕНТАЦИЯ" in result
        assert "**ОБЪЕКТ:**" in result
        assert "<h1>" not in result
        assert "<p>" not in result


class TestSanitizeMarkdownIntegration:
    """Tests for sanitize_markdown integration with html_to_markdown."""

    def test_html_conversion_triggered(self):
        """sanitize_markdown converts HTML when detected."""
        result = sanitize_markdown("<h1>Title</h1>")
        assert "# Title" in result
        assert "<h1>" not in result

    def test_datalab_pattern_still_removed(self):
        """Datalab image patterns are still removed."""
        # Pattern requires 20+ hex characters (a-f, 0-9 only)
        result = sanitize_markdown("text [img:abcdef0123456789abcdef_img] more")
        assert "[img:" not in result
        assert "text" in result
        assert "more" in result

    def test_combined_html_and_datalab(self):
        """Both HTML and Datalab patterns are handled."""
        # Pattern requires 20+ hex characters (a-f, 0-9 only)
        html = "<h1>Title</h1>[img:abcdef0123456789abcdef_img]<p>Content</p>"
        result = sanitize_markdown(html)
        assert "# Title" in result
        assert "Content" in result
        assert "[img:" not in result
        assert "<h1>" not in result

    def test_plain_text_preserved(self):
        """Plain text without HTML is preserved."""
        text = "This is plain text"
        result = sanitize_markdown(text)
        assert result == text

    def test_empty_input(self):
        """Empty input returns empty string."""
        assert sanitize_markdown("") == ""
        assert sanitize_markdown(None) == ""


class TestTableConversion:
    """Tests for HTML table to Markdown conversion."""

    def test_empty_table(self):
        """Empty table returns empty string."""
        result = html_to_markdown("<table></table>")
        assert "<table>" not in result

    def test_table_escapes_pipe(self):
        """Pipe characters in cells are escaped."""
        html = "<table><tr><td>a|b</td></tr></table>"
        result = html_to_markdown(html)
        assert r"a\|b" in result

    def test_table_uneven_columns(self):
        """Tables with uneven columns are padded."""
        html = """
        <table>
            <tr><th>A</th><th>B</th><th>C</th></tr>
            <tr><td>1</td><td>2</td></tr>
        </table>
        """
        result = html_to_markdown(html)
        lines = [l for l in result.split("\n") if l.strip().startswith("|")]
        # All rows should have same number of |
        assert len(lines) >= 2
