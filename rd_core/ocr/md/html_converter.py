"""Конвертация HTML в Markdown."""
import re

from ..generator_common import DATALAB_MD_IMG_PATTERN, sanitize_html
from .table_converter import table_to_markdown


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
        return table_to_markdown(match.group(0))

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
