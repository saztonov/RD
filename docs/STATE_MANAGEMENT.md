# Управление состоянием документа

## Структура хранения состояния

### MainWindow - центральный контроллер

Состояние текущего документа хранится в **`MainWindow`** в следующих полях:

```python
class MainWindow(QMainWindow):
    def __init__(self):
        # PDF документ
        self.pdf_document: Optional[PDFDocument] = None
        
        # Документ с разметкой (legacy структура для совместимости)
        self.annotation_document: Optional[Document] = None
        
        # Кеш отрендеренных страниц: {page_num: PIL.Image}
        self.page_images: dict = {}
        
        # Текущая активная страница
        self.current_page: int = 0
```

### Структура данных

#### Document (legacy, app/models.py)
```python
@dataclass
class Document:
    pdf_path: str
    pages: List[Page]  # список всех страниц с блоками
```

#### Page (legacy, app/models.py)
```python
@dataclass
class Page:
    page_number: int
    width: int         # размеры отрендеренной страницы
    height: int
    blocks: List[Block]  # все блоки разметки на этой странице
```

#### Block (новая версия, app/models.py)
```python
@dataclass
class Block:
    id: str                                      # UUID
    page_index: int                              # индекс страницы
    coords_px: Tuple[int, int, int, int]        # (x1, y1, x2, y2) в пикселях
    coords_norm: Tuple[float, float, float, float]  # (x1, y1, x2, y2) нормализованные
    category: str                                # описание блока
    block_type: BlockType                        # TEXT/TABLE/IMAGE
    source: BlockSource                          # USER/AUTO
    image_file: Optional[str] = None            # путь к кропу
    ocr_text: Optional[str] = None              # результат OCR
```

## Жизненный цикл состояния

### 1. Открытие PDF

```python
def _open_pdf(self):
    # Открываем PDF через PyMuPDF
    self.pdf_document = PDFDocument(file_path)
    self.pdf_document.open()
    
    # Создаём пустой Document с Page для каждой страницы
    self.annotation_document = Document(pdf_path=file_path)
    for page_num in range(self.pdf_document.page_count):
        dims = self.pdf_document.get_page_dimensions(page_num)
        page = Page(page_number=page_num, width=dims[0], height=dims[1])
        self.annotation_document.pages.append(page)
    
    # Рендерим и показываем первую страницу
    self.current_page = 0
    self._render_current_page()
```

### 2. Переключение страниц

```python
def _render_current_page(self):
    # Рендерим страницу если её нет в кеше
    if self.current_page not in self.page_images:
        img = self.pdf_document.render_page(self.current_page)
        self.page_images[self.current_page] = img
    
    # Отображаем страницу и её блоки
    self.page_viewer.set_page_image(
        self.page_images[self.current_page], 
        self.current_page
    )
    
    current_page_data = self.annotation_document.pages[self.current_page]
    self.page_viewer.set_blocks(current_page_data.blocks)
```

### 3. Добавление блока

```python
def _on_block_drawn(self, x1: int, y1: int, x2: int, y2: int):
    # Получаем параметры блока через диалог
    dialog = BlockPropertiesDialog(self)
    if dialog.exec() == QDialog.Accepted:
        category, block_type = dialog.get_values()
        
        # Создаём Block
        current_page_data = self.annotation_document.pages[self.current_page]
        block = Block.create(
            page_index=self.current_page,
            coords_px=(x1, y1, x2, y2),
            page_width=current_page_data.width,
            page_height=current_page_data.height,
            category=category,
            block_type=block_type,
            source=BlockSource.USER
        )
        
        # Добавляем в текущую страницу
        current_page_data.blocks.append(block)
        
        # Обновляем отображение
        self.page_viewer.set_blocks(current_page_data.blocks)
```

### 4. Выбор блока

```python
def _on_block_selected(self, block_idx: int):
    current_page_data = self.annotation_document.pages[self.current_page]
    if 0 <= block_idx < len(current_page_data.blocks):
        block = current_page_data.blocks[block_idx]
        
        # Обновляем UI правой панели
        self.block_type_combo.setCurrentText(block.block_type.value)
        self.block_description.setText(block.category)
        self.block_ocr_text.setText(block.ocr_text or "")
```

### 5. Сохранение/загрузка

```python
def _save_annotation(self):
    # Сохраняем через AnnotationIO
    AnnotationIO.save_annotation(self.annotation_document, file_path)

def _load_annotation(self):
    # Загружаем
    doc = AnnotationIO.load_annotation(file_path)
    if doc:
        self.annotation_document = doc
        self._render_current_page()
```

## Важные моменты

### Координаты
- **coords_px**: абсолютные координаты на отрендеренном изображении (зависят от zoom при рендеринге)
- **coords_norm**: нормализованные 0..1 (независимы от zoom, используются для переноса разметки)

### Кеш изображений
- `page_images` хранит PIL.Image для уже отрендеренных страниц
- Рендеринг выполняется лениво (только при первом просмотре страницы)
- При переносе разметки кеш очищается

### PageViewer
- **Не хранит** состояние документа
- Получает данные через `set_page_image()` и `set_blocks()`
- Испускает сигналы о действиях пользователя: `blockDrawn`, `block_selected`

### Централизация
Все операции с данными проходят через MainWindow:
- Создание блоков
- Изменение блоков
- Удаление блоков
- Переключение страниц
- Сохранение/загрузка

PageViewer - только отображение и ввод пользователя.

## Альтернатива: DocumentManager

Для более сложных приложений можно вынести состояние в отдельный класс:

```python
class DocumentManager:
    def __init__(self):
        self.pdf_document: Optional[PDFDocument] = None
        self.annotation_document: Optional[Document] = None
        self.page_images: dict = {}
        self.current_page: int = 0
    
    def open_pdf(self, path: str): ...
    def add_block(self, page_idx: int, block: Block): ...
    def get_page_blocks(self, page_idx: int) -> List[Block]: ...
    def save(self, path: str): ...
    def load(self, path: str): ...
```

Но для текущего приложения достаточно хранения в MainWindow.

