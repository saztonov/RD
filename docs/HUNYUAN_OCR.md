# HunyuanOCR Integration

## Установка

1. **Клонируйте репозиторий HunyuanOCR:**
```bash
cd "Новая папка"
git clone https://github.com/Tencent-Hunyuan/HunyuanOCR.git
cd HunyuanOCR/Hunyuan-OCR-master
pip install -r requirements.txt
```

2. **Установите PyTorch с CUDA поддержкой (если еще не установлен):**
```bash
pip3 install torch torchvision --index-url https://download.pytorch.org/whl/cu128
```

3. **Модели загрузятся автоматически** при первом запуске.

### Альтернативная структура папок

Приложение ищет HunyuanOCR в следующих местах:
- `HunyuanOCR/Hunyuan-OCR-master/` (текущая директория)
- `Новая папка/HunyuanOCR/Hunyuan-OCR-master/`
- `../HunyuanOCR/Hunyuan-OCR-master/`

Вы можете указать путь вручную в коде.

## Использование

### В GUI приложении:

1. Откройте PDF документ
2. Нажмите кнопку **"Запустить OCR"** или `Ctrl+R`
3. В диалоге выберите:
   - **Tesseract** - постраничное распознавание с сохранением разметки блоков
   - **HunyuanOCR** - создание единого Markdown документа с высокой точностью

### HunyuanOCR особенности:

- ✅ Распознает **многоязычные документы** (русский, английский, китайский и др.)
- ✅ **Таблицы** конвертируются в HTML формат
- ✅ **Формулы** конвертируются в LaTeX формат  
- ✅ Сохраняет **порядок чтения** текста
- ✅ Игнорирует заголовки и колонтитулы
- ✅ Создает **единый Markdown файл** из всего документа

### Промпт HunyuanOCR:

```
Извлеките всю информацию из основного текста изображения документа 
и представьте ее в формате Markdown, игнорируя заголовки и колонтитулы. 
Таблицы должны быть выражены в формате HTML, формулы — в формате LaTeX, 
а разбор должен быть организован в соответствии с порядком чтения.
```

## Программное использование

```python
from app.ocr import HunyuanOCRBackend, run_hunyuan_ocr_full_document
from PIL import Image

# Распознавание одного изображения
ocr = HunyuanOCRBackend()  # Автопоиск в ./Новая папка/HunyuanOCR/
image = Image.open("page.png")
markdown_text = ocr.recognize(image)

# Или указать путь вручную
ocr = HunyuanOCRBackend(hunyuan_repo_path="path/to/HunyuanOCR/Hunyuan-OCR-master")

# Распознавание всего документа
page_images = {0: Image.open("page1.png"), 1: Image.open("page2.png")}
result_path = run_hunyuan_ocr_full_document(page_images, "output.md")
```

## Системные требования

- **GPU:** NVIDIA с CUDA поддержкой (рекомендуется, но необязательно)
- **RAM:** минимум 8GB, рекомендуется 16GB+
- **VRAM:** минимум 4GB для GPU режима
- **Место на диске:** ~3GB для модели

## Troubleshooting

### Ошибка "HunyuanOCR репозиторий не найден"
**Решение:**
```bash
cd "Новая папка"
git clone https://github.com/Tencent-Hunyuan/HunyuanOCR.git
cd HunyuanOCR/Hunyuan-OCR-master
pip install -r requirements.txt
```

### Ошибка импорта модулей HunyuanOCR
- Убедитесь, что установлены все зависимости из `requirements.txt` репозитория
- Проверьте, что путь к репозиторию правильный
- Попробуйте указать путь вручную: `HunyuanOCRBackend(hunyuan_repo_path="...")`

### Ошибка "CUDA out of memory"
- Модель автоматически переключится на CPU если CUDA недоступна
- Уменьшите размер изображения перед распознаванием

### Модели не загружаются при первом запуске
- Убедитесь, что есть доступ к интернету
- Модели загружаются автоматически при первом вызове `predict()`

## Ссылки

- [HunyuanOCR GitHub](https://github.com/Tencent-Hunyuan/HunyuanOCR)
- [Technical Report](https://arxiv.org/abs/2511.19575)

