"""Конвертеры HTML в Markdown для OCR результатов."""
import re

from rd_pipeline.common import DATALAB_MD_IMG_PATTERN, sanitize_html


def _clean_cell_text(text: str) -> str:
    """Очистить текст ячейки таблицы - заменить переносы на пробелы."""
    text = re.sub(r'\s*\n\s*', ' ', text)
    text = re.sub(r' +', ' ', text)
    return text.strip()


def _parse_cell_span(cell_tag: str) -> tuple:
    """Извлечь colspan и rowspan из тега ячейки."""
    colspan_match = re.search(r'colspan\s*=\s*["\']?(\d+)', cell_tag, re.IGNORECASE)
    rowspan_match = re.search(r'rowspan\s*=\s*["\']?(\d+)', cell_tag, re.IGNORECASE)
    colspan = int(colspan_match.group(1)) if colspan_match else 1
    rowspan = int(rowspan_match.group(1)) if rowspan_match else 1
    return colspan, rowspan


def _table_to_markdown(table_html: str) -> str:
    """Конвертировать таблицу HTML в Markdown (включая сложные таблицы с colspan/rowspan)."""
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, flags=re.DOTALL)
    if not rows:
        return ""

    # Парсим все строки с учетом colspan/rowspan
    parsed_rows = []
    rowspan_tracker = {}  # {col_index: (remaining_rows, text)}

    for row_html in rows:
        # Находим все ячейки с их тегами
        cell_matches = re.findall(r"<(t[hd][^>]*)>(.*?)</t[hd]>", row_html, flags=re.DOTALL)
        if not cell_matches:
            continue

        row_cells = []
        col_idx = 0
        cell_iter = iter(cell_matches)

        while True:
            # Проверяем, есть ли активный rowspan для текущей колонки
            if col_idx in rowspan_tracker:
                remaining, text = rowspan_tracker[col_idx]
                row_cells.append("")  # Пустая ячейка для объединенной строки
                if remaining <= 1:
                    del rowspan_tracker[col_idx]
                else:
                    rowspan_tracker[col_idx] = (remaining - 1, text)
                col_idx += 1
                continue

            # Берем следующую ячейку из HTML
            try:
                cell_tag, cell_content = next(cell_iter)
            except StopIteration:
                break

            colspan, rowspan = _parse_cell_span(cell_tag)
            text = re.sub(r"<[^>]+>", "", cell_content)
            text = _clean_cell_text(text)

            # Добавляем ячейку
            row_cells.append(text)

            # Регистрируем rowspan для последующих строк
            if rowspan > 1:
                rowspan_tracker[col_idx] = (rowspan - 1, text)

            col_idx += 1

            # Добавляем пустые ячейки для colspan
            for _ in range(colspan - 1):
                row_cells.append("")
                col_idx += 1

        # Обрабатываем оставшиеся rowspan'ы в конце строки
        while col_idx in rowspan_tracker:
            remaining, text = rowspan_tracker[col_idx]
            row_cells.append("")
            if remaining <= 1:
                del rowspan_tracker[col_idx]
            else:
                rowspan_tracker[col_idx] = (remaining - 1, text)
            col_idx += 1

        if row_cells:
            parsed_rows.append(row_cells)

    if not parsed_rows:
        return ""

    # Определяем максимальное количество колонок
    max_cols = max(len(row) for row in parsed_rows)

    # Выравниваем все строки по максимальному количеству колонок
    for row in parsed_rows:
        while len(row) < max_cols:
            row.append("")

    # Формируем markdown таблицу
    md_rows = []
    for i, row in enumerate(parsed_rows):
        # Экранируем pipe в содержимом ячеек
        escaped_cells = [cell.replace("|", "\\|") for cell in row]
        md_rows.append("| " + " | ".join(escaped_cells) + " |")

        # Добавляем разделитель после первой строки (заголовок)
        if i == 0:
            md_rows.append("|" + "|".join(["---"] * max_cols) + "|")

    return "\n".join(md_rows)


def html_to_markdown(html: str) -> str:
    """Конвертировать HTML в компактный Markdown."""
    if not html:
        return ""

    # Сначала санитизируем HTML (удаляем мусорные img от datalab)
    text = sanitize_html(html)

    # Удаляем stamp-info блоки (уже в header)
    text = re.sub(r'<div class="stamp-info[^"]*">.*?</div>', "", text, flags=re.DOTALL)

    # Удаляем BLOCK маркеры (уже в header)
    text = re.sub(r"<p>BLOCK:\s*[A-Z0-9\-]+</p>", "", text)

    # Удаляем Created, Linked, Grouped (уже в header)
    text = re.sub(r"<p><b>Created:</b>[^<]*</p>", "", text)
    text = re.sub(r"<p><b>Linked block:</b>[^<]*</p>", "", text)
    text = re.sub(r"<p><b>Grouped blocks:</b>[^<]*</p>", "", text)

    # Удаляем ссылки на кроп изображения
    text = re.sub(r'<p><a[^>]*>.*?Открыть кроп изображения.*?</a></p>', "", text, flags=re.DOTALL)

    # Обрабатываем таблицы ПЕРЕД остальным HTML
    def process_table_match(match):
        return _table_to_markdown(match.group(0))

    text = re.sub(r"<table[^>]*>.*?</table>", process_table_match, text, flags=re.DOTALL)

    # Заголовки (сдвиг на 3 уровня вниз для вложенности в блок)
    text = re.sub(r"<h1[^>]*>\s*(.*?)\s*</h1>", r"#### \1\n", text, flags=re.DOTALL)
    text = re.sub(r"<h2[^>]*>\s*(.*?)\s*</h2>", r"##### \1\n", text, flags=re.DOTALL)
    text = re.sub(r"<h3[^>]*>\s*(.*?)\s*</h3>", r"###### \1\n", text, flags=re.DOTALL)
    text = re.sub(r"<h4[^>]*>\s*(.*?)\s*</h4>", r"###### \1\n", text, flags=re.DOTALL)

    # Жирный и курсив
    text = re.sub(r"<b>\s*(.*?)\s*</b>", r"**\1**", text, flags=re.DOTALL)
    text = re.sub(r"<strong>\s*(.*?)\s*</strong>", r"**\1**", text, flags=re.DOTALL)
    text = re.sub(r"<i>\s*(.*?)\s*</i>", r"*\1*", text, flags=re.DOTALL)
    text = re.sub(r"<em>\s*(.*?)\s*</em>", r"*\1*", text, flags=re.DOTALL)

    # Код
    text = re.sub(r"<code[^>]*>(.*?)</code>", r"`\1`", text, flags=re.DOTALL)
    text = re.sub(r"<pre[^>]*>(.*?)</pre>", r"```\n\1\n```", text, flags=re.DOTALL)

    # Списки
    text = re.sub(r"<li>\s*(.*?)\s*</li>", r"- \1\n", text, flags=re.DOTALL)
    text = re.sub(r"<[ou]l[^>]*>", "", text)
    text = re.sub(r"</[ou]l>", "", text)

    # Удаляем все img теги (уже обработаны в sanitize_html, но на всякий случай)
    text = re.sub(r'<img[^>]*/?>','', text)

    # Ссылки
    text = re.sub(r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', r"[\2](\1)", text, flags=re.DOTALL)

    # Переносы строк
    text = re.sub(r"<br\s*/?>", "\n", text)

    # Параграфы
    text = re.sub(r"<p[^>]*>\s*(.*?)\s*</p>", r"\1\n", text, flags=re.DOTALL)

    # Удаляем оставшиеся HTML теги
    text = re.sub(r"<[^>]+>", "", text)

    # Декодируем HTML entities
    text = text.replace("&nbsp;", " ")
    text = text.replace("&amp;", "&")
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
    text = text.replace("&quot;", '"')
    text = text.replace("&#39;", "'")

    # Удаляем остаточные markdown-ссылки на мусорные изображения
    text = DATALAB_MD_IMG_PATTERN.sub("", text)

    # Нормализуем пробелы и переносы
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()

    return text


# Алиас для обратной совместимости
_html_to_markdown = html_to_markdown
