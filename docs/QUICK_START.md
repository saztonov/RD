# 🚀 Быстрый старт - PDF Рендеринг

## Установка зависимостей

```bash
pip install -r requirements.txt
```

## Базовое использование

### Открыть и отрендерить одну страницу

```python
from app.pdf_utils import open_pdf, render_page_to_image

doc = open_pdf("document.pdf")
image = render_page_to_image(doc, 0, zoom=2.0)  # Первая страница
image.save("page_0.png")
doc.close()
```

### Отрендерить все страницы

```python
from app.pdf_utils import open_pdf, render_all_pages

doc = open_pdf("document.pdf")
images = render_all_pages(doc, zoom=2.0)

for idx, img in enumerate(images):
    img.save(f"page_{idx + 1}.png")

doc.close()
```

### Context Manager (рекомендуется)

```python
from app.pdf_utils import PDFDocument

with PDFDocument("document.pdf") as pdf:
    if pdf.doc:
        all_images = pdf.render_all(zoom=2.0)
        # Автоматически закроется
```

## Обработка ошибок

```python
from app.pdf_utils import open_pdf, render_page_to_image

try:
    doc = open_pdf("document.pdf")
    image = render_page_to_image(doc, 0)
    image.save("output.png")
    doc.close()
    
except FileNotFoundError:
    print("PDF файл не найден")
except ValueError:
    print("Файл повреждён или не является PDF")
except IndexError:
    print("Некорректный номер страницы")
```

## Настройка логирования

```python
import logging

# Включить подробное логирование
logging.basicConfig(level=logging.INFO)

# Или только для PDF модуля
logging.getLogger('app.pdf_utils').setLevel(logging.DEBUG)
```

## Запуск приложения

```bash
python app/main.py
```

Логи сохраняются в `logs/app.log`

## Zoom параметры

- `1.0` — 72 DPI (быстро, низкое качество)
- **`2.0`** — 144 DPI (рекомендуется) ⭐
- `3.0` — 216 DPI (высокое качество, медленнее)

## Полная документация

См. `docs/pdf_rendering.md`

