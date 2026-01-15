"""Функции очистки HTML и Markdown от артефактов OCR."""
import re

# Паттерн для мусорных img тегов от datalab (хеш_img.ext)
DATALAB_IMG_PATTERN = re.compile(
    r'<img[^>]*src=["\']?[a-f0-9]{20,}_img(?:\.[a-z]{3,4})?["\']?[^>]*/?>',
    re.IGNORECASE
)

# Паттерн для markdown-ссылок на мусорные изображения [img:hash_img]
DATALAB_MD_IMG_PATTERN = re.compile(r'\[img:[a-f0-9]{20,}_img\]')


def sanitize_html(html: str) -> str:
    """
    Очистить HTML от артефактов datalab OCR.

    1. Удаляет мусорные img теги (хеш_img.jpg)
    2. Удаляет осиротевшие закрывающие теги в начале
    3. Удаляет незакрытые открывающие теги в конце
    4. Удаляет вложенные DOCTYPE/html/body артефакты
    5. Удаляет закрывающие </p> без соответствующего открывающего <p>
    """
    if not html:
        return ""

    text = html

    # 1. Удаляем мусорные img теги от datalab
    text = DATALAB_IMG_PATTERN.sub("", text)

    # 2. Удаляем вложенные DOCTYPE/html/head/body артефакты (бывает внутри блоков)
    text = re.sub(r'<!DOCTYPE\s+html[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<html[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</html\s*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<head[^>]*>.*?</head\s*>', '', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<body[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</body\s*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<div\s+class="page"[^>]*>', '', text, flags=re.IGNORECASE)

    # 3. Удаляем осиротевшие закрывающие теги в начале (могут повторяться)
    while True:
        new_text = re.sub(r'^\s*</[a-z]+>\s*', '', text, flags=re.IGNORECASE)
        if new_text == text:
            break
        text = new_text

    # 4. Удаляем незакрытые открывающие теги в конце
    text = re.sub(r'\s*<p>\s*$', '', text)
    text = re.sub(r'\s*<div[^>]*>\s*$', '', text)

    # 5. Удаляем "висячие" </p> теги - те, которым не предшествует <p>
    def remove_orphan_closing_p(html_text: str) -> str:
        """Удалить </p> теги без соответствующего <p>."""
        result = []
        parts = re.split(r'(</p>)', html_text, flags=re.IGNORECASE)
        open_count = 0

        for part in parts:
            if re.match(r'</p>', part, re.IGNORECASE):
                if open_count > 0:
                    result.append(part)
                    open_count -= 1
                # else: пропускаем "висячий" </p>
            else:
                # Считаем открывающие <p> в этой части
                open_count += len(re.findall(r'<p\b[^>]*>', part, re.IGNORECASE))
                result.append(part)

        return ''.join(result)

    text = remove_orphan_closing_p(text)

    # 6. Удаляем незакрытые <p> в конце
    while True:
        open_p = len(re.findall(r'<p\b[^>]*>', text, re.IGNORECASE))
        close_p = len(re.findall(r'</p>', text, re.IGNORECASE))
        if open_p <= close_p:
            break
        # Удаляем последний незакрытый <p>
        text = re.sub(r'<p\b[^>]*>(?!.*<p\b)', '', text, flags=re.DOTALL | re.IGNORECASE)

    # 7. Удаляем пустые теги
    text = re.sub(r'<p>\s*</p>', '', text, flags=re.IGNORECASE)

    # 8. Нормализуем множественные пустые строки
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()


def sanitize_markdown(md: str) -> str:
    """
    Очистить Markdown от артефактов datalab OCR.

    Удаляет ссылки вида [img:hash_img].
    """
    if not md:
        return ""

    # Удаляем мусорные markdown-ссылки на изображения
    text = DATALAB_MD_IMG_PATTERN.sub("", md)

    # Удаляем пустые строки после удаления
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()
