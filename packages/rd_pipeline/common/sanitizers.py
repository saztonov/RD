"""Functions for cleaning Markdown from OCR artifacts and converting HTML to Markdown."""

import html as html_module
import re

# Pattern for markdown links to garbage images [img:hash_img]
DATALAB_MD_IMG_PATTERN = re.compile(r'\[img:[a-f0-9]{20,}_img\]')


def _convert_html_tables(text: str) -> str:
    """Конвертировать HTML таблицы в Markdown таблицы."""
    table_pattern = re.compile(r'<table[^>]*>(.*?)</table>', re.DOTALL | re.IGNORECASE)

    def convert_table(match: re.Match) -> str:
        table_html = match.group(1)
        rows: list[list[str]] = []

        row_pattern = re.compile(r'<tr[^>]*>(.*?)</tr>', re.DOTALL | re.IGNORECASE)
        cell_pattern = re.compile(r'<t[hd][^>]*>(.*?)</t[hd]>', re.DOTALL | re.IGNORECASE)

        for row_match in row_pattern.finditer(table_html):
            cells: list[str] = []
            for cell_match in cell_pattern.finditer(row_match.group(1)):
                cell_text = cell_match.group(1)
                # Очистить содержимое ячейки от HTML тегов
                cell_text = re.sub(r'<br\s*/?>', ' ', cell_text, flags=re.IGNORECASE)
                cell_text = re.sub(r'<[^>]+>', '', cell_text)
                cell_text = re.sub(r'\s+', ' ', cell_text).strip()
                # Экранировать pipe символы в ячейках
                cell_text = cell_text.replace('|', '\\|')
                cells.append(cell_text)
            if cells:
                rows.append(cells)

        if not rows:
            return ""

        # Построить markdown таблицу
        md_lines: list[str] = []
        max_cols = max(len(r) for r in rows)

        for i, row in enumerate(rows):
            # Дополнить строку до максимального числа колонок
            while len(row) < max_cols:
                row.append("")
            md_lines.append("| " + " | ".join(row) + " |")

            # Добавить разделитель после первой строки (заголовок)
            if i == 0:
                md_lines.append("| " + " | ".join(["---"] * max_cols) + " |")

        return "\n" + "\n".join(md_lines) + "\n"

    return table_pattern.sub(convert_table, text)


def html_to_markdown(text: str) -> str:
    """Конвертировать HTML контент в чистый Markdown."""
    if not text:
        return ""

    # 1. Декодировать HTML сущности (&amp; -> &, &nbsp; -> пробел)
    text = html_module.unescape(text)

    # 2. Извлечь MathML контент: <math>...</math> -> содержимое
    # Удаляем LaTeX-подобные команды внутри math тегов
    def clean_math(match: re.Match) -> str:
        content = match.group(1)
        # Убрать \text{}, оставить содержимое
        content = re.sub(r'\\text\{([^}]*)\}', r'\1', content)
        # Убрать ^{} для степеней, оставить содержимое
        content = re.sub(r'\^\{([^}]*)\}', r'\1', content)
        # Убрать \circ -> °
        content = content.replace(r'\circ', '°')
        return content

    text = re.sub(r'<math>(.*?)</math>', clean_math, text, flags=re.DOTALL)

    # 3. Удалить CSS и HTML атрибуты
    text = re.sub(r'\s+style="[^"]*"', '', text)
    text = re.sub(r'\s+border="[^"]*"', '', text)
    text = re.sub(r'\s+colspan="[^"]*"', '', text)
    text = re.sub(r'\s+rowspan="[^"]*"', '', text)

    # 4. Конвертировать таблицы (до удаления тегов)
    text = _convert_html_tables(text)

    # 5. Конвертировать HTML заголовки
    text = re.sub(r'<h1[^>]*>\s*(.*?)\s*</h1>', r'\n# \1\n', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<h2[^>]*>\s*(.*?)\s*</h2>', r'\n## \1\n', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<h3[^>]*>\s*(.*?)\s*</h3>', r'\n### \1\n', text, flags=re.DOTALL | re.IGNORECASE)

    # 6. Конвертировать inline форматирование
    text = re.sub(r'<b>(.*?)</b>', r'**\1**', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<strong>(.*?)</strong>', r'**\1**', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<i>(.*?)</i>', r'*\1*', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<em>(.*?)</em>', r'*\1*', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<u>(.*?)</u>', r'\1', text, flags=re.DOTALL | re.IGNORECASE)

    # 7. Конвертировать переносы строк и горизонтальные линии
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<hr\s*/?>', '\n---\n', text, flags=re.IGNORECASE)

    # 8. Конвертировать параграфы
    text = re.sub(r'<p[^>]*>\s*(.*?)\s*</p>', r'\1\n\n', text, flags=re.DOTALL | re.IGNORECASE)

    # 9. Конвертировать списки
    text = re.sub(r'<ul[^>]*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</ul>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<ol[^>]*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</ol>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<li[^>]*>\s*(.*?)\s*</li>', r'- \1\n', text, flags=re.DOTALL | re.IGNORECASE)

    # 10. Удалить оставшиеся HTML теги
    text = re.sub(r'<[^>]+>', '', text)

    # 11. Нормализовать пробелы
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]+\n', '\n', text)
    text = re.sub(r'\n[ \t]+', '\n', text)

    return text.strip()


def sanitize_markdown(md: str) -> str:
    """
    Clean Markdown from datalab OCR artifacts and convert HTML to Markdown.

    Removes links like [img:hash_img] and converts HTML tags to Markdown.
    """
    if not md:
        return ""

    text = md

    # Convert HTML to Markdown if HTML tags detected
    if '<' in text and '>' in text:
        text = html_to_markdown(text)

    # Remove garbage markdown image links
    text = DATALAB_MD_IMG_PATTERN.sub("", text)

    # Remove empty lines after removal
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()
