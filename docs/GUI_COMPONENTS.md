# GUI компоненты

## Общая структура

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Menu Bar                                                                │
├──────────────┬──────────────────────────────────────┬───────────────────┤
│              │                                      │                   │
│  Project     │                                      │   Remote OCR      │
│  Tree        │         Page Viewer                  │   Panel           │
│  (Dock)      │         (Central)                    │   (Dock)          │
│              │                                      │                   │
│              │                                      │                   │
│              │                                      │                   │
├──────────────┤                                      ├───────────────────┤
│              │                                      │                   │
│  Blocks      │                                      │   Tools           │
│  Tree        │                                      │   (Dock)          │
│  (Dock)      │                                      │                   │
│              │                                      │                   │
└──────────────┴──────────────────────────────────────┴───────────────────┘
│  Status Bar / Navigation                                                 │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## MainWindow

**Файл:** `app/gui/main_window.py`

Главное окно приложения, собранное из миксинов:

```python
class MainWindow(MenuSetupMixin, PanelsSetupMixin, 
                 FileOperationsMixin, BlockHandlersMixin, QMainWindow):
```

### Основные атрибуты

| Атрибут | Тип | Описание |
|---------|-----|----------|
| `pdf_document` | `PDFDocument` | Открытый PDF документ |
| `annotation_document` | `Document` | Модель разметки |
| `current_page` | `int` | Текущая страница (0-based) |
| `page_images` | `dict` | Кеш отрендеренных страниц |
| `page_zoom_states` | `dict` | Сохранённые состояния зума |
| `undo_stack` | `list` | Стек отмены |
| `redo_stack` | `list` | Стек повтора |

### Менеджеры

| Менеджер | Класс | Описание |
|----------|-------|----------|
| `prompt_manager` | `PromptManager` | Загрузка промптов из R2 |
| `blocks_tree_manager` | `BlocksTreeManager` | Дерево блоков страницы |
| `navigation_manager` | `NavigationManager` | Навигация и зум |

### Ключевые методы

```python
def _render_current_page(self, update_tree=True):
    """Отрендерить текущую страницу"""
    
def _update_ui(self):
    """Обновить UI элементы (лейблы, спинбоксы)"""
    
def _save_undo_state(self):
    """Сохранить состояние для отмены"""
    
def _undo(self):
    """Отменить последнее действие"""
    
def _redo(self):
    """Повторить отменённое действие"""
```

---

## PageViewer

**Файл:** `app/gui/page_viewer.py`

Виджет просмотра страницы PDF на базе `QGraphicsView`.

### Миксины

```python
class PageViewer(ContextMenuMixin, MouseEventsMixin, 
                 BlockRenderingMixin, PolygonMixin, 
                 ResizeHandlesMixin, QGraphicsView):
```

| Миксин | Файл | Функционал |
|--------|------|------------|
| `BlockRenderingMixin` | `page_viewer_blocks.py` | Отрисовка блоков |
| `MouseEventsMixin` | `page_viewer_mouse.py` | Обработка мыши |
| `PolygonMixin` | `page_viewer_polygon.py` | Рисование полигонов |
| `ResizeHandlesMixin` | `page_viewer_resize.py` | Ресайз блоков |
| `ContextMenuMixin` | `page_viewer_context_menu.py` | Контекстное меню |

### Сигналы

| Сигнал | Параметры | Когда эмитируется |
|--------|-----------|-------------------|
| `blockDrawn` | `(x1, y1, x2, y2)` | Нарисован прямоугольник |
| `polygonDrawn` | `list[points]` | Нарисован полигон |
| `block_selected` | `int (index)` | Выбран один блок |
| `blocks_selected` | `list[indices]` | Множественный выбор |
| `blockEditing` | `int (index)` | Начато редактирование |
| `blockDeleted` | `int (index)` | Удалён блок |
| `blocks_deleted` | `list[indices]` | Удалены блоки |
| `blockMoved` | `(idx, x1, y1, x2, y2)` | Блок перемещён |
| `page_changed` | `int (page)` | Изменена страница |

### Состояния

```python
# Режимы рисования
self.drawing = False           # Рисование прямоугольника
self.drawing_polygon = False   # Рисование полигона
self.selecting = False         # Выделение области

# Режимы редактирования
self.moving_block = False      # Перемещение блока
self.resizing_block = False    # Изменение размера
self.panning = False           # Панорамирование (средняя кнопка)

# Редактирование полигонов
self.dragging_polygon_vertex = None  # Индекс вершины
self.dragging_polygon_edge = None    # Индекс ребра
```

### Основные методы

```python
def set_page_image(self, pil_image, page_number, reset_zoom=True):
    """Установить изображение страницы"""
    
def set_blocks(self, blocks: List[Block]):
    """Отобразить блоки на странице"""
    
def fit_to_view(self):
    """Подогнать под размер окна"""
    
def reset_zoom(self):
    """Сбросить масштаб к 100%"""
    
def get_current_shape_type(self) -> ShapeType:
    """Получить текущий тип формы (RECTANGLE/POLYGON)"""
```

### Горячие клавиши

| Клавиша | Действие |
|---------|----------|
| `Delete` | Удалить выделенный блок |
| `Ctrl+A` | Выделить все блоки |
| `Escape` | Отменить рисование |
| `Колёсико` | Зум |
| `Ctrl+Колёсико` | Быстрый зум |
| `Средняя кнопка` | Панорамирование |

---

## RemoteOCRPanel

**Файл:** `app/gui/remote_ocr_panel.py`

Dock-панель управления OCR-задачами.

### Миксины

```python
class RemoteOCRPanel(EditorMixin, DraftMixin, 
                     JobOperationsMixin, DownloadMixin, QDockWidget):
```

| Миксин | Файл | Функционал |
|--------|------|------------|
| `DownloadMixin` | `remote_ocr_download.py` | Скачивание результатов |
| `JobOperationsMixin` | `remote_ocr_job_operations.py` | Pause/Resume/Delete |
| `DraftMixin` | `remote_ocr_draft.py` | Сохранение черновиков |
| `EditorMixin` | `remote_ocr_editor.py` | Открытие в редакторе |

### Интервалы polling

```python
POLL_INTERVAL_PROCESSING = 5000   # 5 сек при активных задачах
POLL_INTERVAL_IDLE = 30000        # 30 сек в режиме ожидания
POLL_INTERVAL_ERROR = 60000       # 1 мин при ошибках (+ exponential backoff)
```

### Сигналы (WorkerSignals)

```python
class WorkerSignals(QObject):
    jobs_loaded = Signal(list)           # Список задач загружен
    jobs_error = Signal(str)             # Ошибка загрузки
    job_created = Signal(object)         # Задача создана
    job_create_error = Signal(str, str)  # Ошибка создания
    download_started = Signal(str, int)  # Начато скачивание
    download_progress = Signal(str, int, str)
    download_finished = Signal(str, str)
    download_error = Signal(str, str)
    draft_created = Signal(object)
    draft_create_error = Signal(str)
    rerun_created = Signal(str, object)
    rerun_error = Signal(str, str)
```

### UI компоненты

```
┌──────────────────────────────────────┐
│ Задачи:          🟢 Подключено  [🔄] │
├──────────────────────────────────────┤
│ № │ Наименование │ Время │ Статус   │
├───┼──────────────┼───────┼──────────┤
│ 1 │ Task 1       │ 12:30 │ ✅ Готово│
│ 2 │ Task 2       │ 12:35 │ 🔄 50%   │
│   │              │       │ [✏️][🔁] │
└──────────────────────────────────────┘
```

### Кнопки действий

| Кнопка | Tooltip | Действие |
|--------|---------|----------|
| ✏️ | Открыть в редакторе | Загрузить результат и открыть PDF |
| 🔁 | Повторное распознавание | Перезапустить OCR |
| ⏸️ | Поставить на паузу | Остановить обработку |
| ▶️ | Возобновить | Продолжить с паузы |
| ℹ️ | Информация | Показать детали задачи |
| 🗑️ | Удалить | Удалить задачу |

---

## ProjectTreeWidget

**Файл:** `app/gui/project_tree_widget.py`

Виджет дерева проектов с поддержкой Supabase.

### Сигналы

```python
document_selected = Signal(str, str)  # node_id, r2_key
file_uploaded = Signal(str)           # local_path
refresh_requested = Signal()
```

### Иконки узлов

```python
NODE_ICONS = {
    NodeType.PROJECT: "📦",
    NodeType.STAGE: "📋",
    NodeType.SECTION: "📁",
    NodeType.TASK_FOLDER: "📂",
    NodeType.DOCUMENT: "📄",
}

STATUS_COLORS = {
    NodeStatus.ACTIVE: "#e0e0e0",
    NodeStatus.COMPLETED: "#4caf50",
    NodeStatus.ARCHIVED: "#9e9e9e",
}
```

### Lazy Loading

При раскрытии узла:
1. Если есть placeholder ("...") — загружаются дочерние
2. `client.get_children(parent_id)` → Supabase
3. Создаются `QTreeWidgetItem` с `TreeNode` в `UserRole`

### Контекстное меню

| Пункт | Доступен для | Действие |
|-------|--------------|----------|
| + Стадия | PROJECT | Создать дочернюю стадию |
| + Раздел | STAGE | Создать дочерний раздел |
| + Папка заданий | SECTION | Создать папку |
| 📄 Добавить файл | TASK_FOLDER | Загрузить PDF |
| 🗑️ Удалить рамки/QR | DOCUMENT (.pdf) | Удалить штампы |
| ✏️ Переименовать | Любой | Переименовать узел |
| 🗑️ Удалить | Любой | Удалить (каскадно) |

### Поиск

```python
def _filter_tree(self, text: str):
    """Фильтровать дерево по тексту"""
    # Скрывает несоответствующие узлы
    # Показывает родителей соответствующих узлов
    # Автораскрытие при поиске
```

---

## BlocksTreeManager

**Файл:** `app/gui/blocks_tree_manager.py`

Управление деревом блоков текущей страницы.

### Структура дерева

```
Страница 1
├── TEXT #1 (100, 200)
├── TABLE #2 (300, 400)
└── IMAGE #3 (500, 600)
```

### Методы

```python
def update_blocks_tree(self):
    """Обновить дерево блоков из annotation_document"""
    
def select_block_in_tree(self, block_index: int):
    """Выделить блок в дереве"""
    
def _on_tree_selection_changed(self):
    """Синхронизация с PageViewer"""
```

### Синхронизация

- Выбор блока в PageViewer → выделение в дереве
- Выбор в дереве → выделение в PageViewer
- Двойной клик в дереве → прокрутка к блоку

---

## NavigationManager

**Файл:** `app/gui/navigation_manager.py`

Управление навигацией по страницам и зумом.

### Методы

```python
def go_to_page(self, page_index: int):
    """Перейти на страницу"""
    
def prev_page(self):
    """Предыдущая страница"""
    
def next_page(self):
    """Следующая страница"""
    
def zoom_in(self):
    """Увеличить масштаб"""
    
def zoom_out(self):
    """Уменьшить масштаб"""
    
def zoom_reset(self):
    """Сбросить масштаб к 100%"""
    
def fit_to_view(self):
    """Подогнать к размеру окна"""
    
def save_current_zoom(self):
    """Сохранить состояние зума для страницы"""
    
def restore_zoom(self):
    """Восстановить сохранённый зум"""
    
def load_page_image(self, page_index: int):
    """Загрузить изображение страницы (с кешированием)"""
```

---

## PromptManager

**Файл:** `app/gui/prompt_manager.py`

Управление промптами OCR из R2 Storage.

### Структура промптов

```json
// prompts/text.json
{
  "system": "You are an OCR expert...",
  "user": "Extract text from this image..."
}
```

### Методы

```python
def ensure_default_prompts(self):
    """Проверить/создать дефолтные промпты в R2"""
    
def load_prompt(self, prompt_type: str) -> Optional[dict]:
    """Загрузить промпт по типу (text/table/image)"""
    
def save_prompt(self, prompt_type: str, prompt_data: dict):
    """Сохранить промпт в R2"""
    
def list_prompts(self) -> List[str]:
    """Список доступных промптов"""
```

### Placeholder переменные

В промптах IMAGE можно использовать:

| Переменная | Значение |
|------------|----------|
| `{{doc_name}}` | Имя PDF файла |
| `{{page_index}}` | Номер страницы |
| `{{block_id}}` | ID блока |
| `{{hint}}` | Подсказка пользователя |
| `{{pdfplumber_text}}` | Извлечённый текст |

---

## Диалоги

### CreateNodeDialog

**Файл:** `app/gui/create_node_dialog.py`

Диалог создания узла дерева проектов.

```python
dialog = CreateNodeDialog(
    parent=self,
    node_type=NodeType.SECTION,
    stage_types=stage_types,
    section_types=section_types
)
if dialog.exec() == QDialog.Accepted:
    name = dialog.get_name()
    code = dialog.get_code()
```

### PromptEditorDialog

**Файл:** `app/gui/prompt_editor_dialog.py`

Редактор промптов OCR.

```
┌────────────────────────────────────┐
│ Редактор промптов                  │
├────────────────────────────────────┤
│ Тип: [text ▼]                      │
├────────────────────────────────────┤
│ System:                            │
│ ┌────────────────────────────────┐ │
│ │ You are an OCR expert...       │ │
│ └────────────────────────────────┘ │
│ User:                              │
│ ┌────────────────────────────────┐ │
│ │ Extract text from this image..│ │
│ └────────────────────────────────┘ │
├────────────────────────────────────┤
│        [Сохранить] [Отмена]        │
└────────────────────────────────────┘
```

### JobDetailsDialog

**Файл:** `app/gui/job_details_dialog.py`

Детальная информация о задаче OCR.

### FolderSettingsDialog

**Файл:** `app/gui/folder_settings_dialog.py`

Настройки папок (output, temp).

### OCRDialog

**Файл:** `app/gui/ocr_dialog.py`

Диалог выбора движка и модели OCR.

---

## Toast уведомления

**Файл:** `app/gui/toast.py`

Всплывающие уведомления.

```python
from app.gui.toast import show_toast

show_toast(parent_widget, "Файл сохранён!", duration=2500)
```

Параметры:
- `parent` — родительский виджет
- `message` — текст сообщения
- `duration` — время показа (мс), по умолчанию 3000

---

## Стилизация

### Тёмная тема (по умолчанию)

```python
# Основные цвета
BACKGROUND = "#1e1e1e"
SURFACE = "#252526"
BORDER = "#3e3e42"
TEXT = "#e0e0e0"
TEXT_SECONDARY = "#bbbbbb"
ACCENT = "#0e639c"
ACCENT_HOVER = "#1177bb"
SUCCESS = "#4caf50"
ERROR = "#f44336"
WARNING = "#e67e22"
```

### Пример стилизации

```python
widget.setStyleSheet("""
    QWidget {
        background-color: #1e1e1e;
        color: #e0e0e0;
    }
    QPushButton {
        background-color: #0e639c;
        border: none;
        padding: 6px 16px;
        border-radius: 4px;
    }
    QPushButton:hover {
        background-color: #1177bb;
    }
    QTreeWidget::item:selected {
        background-color: #094771;
    }
""")
```

---

## Горячие клавиши (полный список)

| Клавиша | Действие | Контекст |
|---------|----------|----------|
| `Ctrl+O` | Открыть PDF | Глобально |
| `Ctrl+S` | Сохранить разметку | Глобально |
| `Ctrl+Shift+S` | Сохранить как | Глобально |
| `Ctrl+Z` | Отмена | Глобально |
| `Ctrl+Y` | Повтор | Глобально |
| `Ctrl+Shift+Z` | Повтор | Глобально |
| `Page Up` | Предыдущая страница | Глобально |
| `Page Down` | Следующая страница | Глобально |
| `Ctrl++` | Увеличить зум | PageViewer |
| `Ctrl+-` | Уменьшить зум | PageViewer |
| `Ctrl+0` | Сбросить зум | PageViewer |
| `Ctrl+F` | Подогнать к окну | PageViewer |
| `Delete` | Удалить блок | PageViewer |
| `Ctrl+A` | Выделить все блоки | PageViewer |
| `Escape` | Отменить рисование | PageViewer |
| `F5` | Обновить список задач | RemoteOCRPanel |

