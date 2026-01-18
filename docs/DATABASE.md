# Схема базы данных

## Обзор

Приложение использует **Supabase** (PostgreSQL) для хранения:
- Задач OCR и их файлов
- Иерархии проектов (Tree)
- Справочников (типы стадий и разделов)

## ER-диаграмма

```
┌─────────────────────────────────────────────────────────────────┐
│                         JOBS CLUSTER                            │
├─────────────────────────────────────────────────────────────────┤

┌─────────────────────┐     ┌─────────────────────┐
│       jobs          │     │    job_settings     │
├─────────────────────┤     ├─────────────────────┤
│ id           uuid PK│◄────│ job_id    uuid PK FK│
│ client_id    text   │     │ text_model    text  │
│ document_id  text   │     │ table_model   text  │
│ document_name text  │     │ image_model   text  │
│ task_name    text   │     │ stamp_model   text  │
│ status       text   │     │ created_at timestamptz
│ progress     real   │     │ updated_at timestamptz
│ engine       text   │     └─────────────────────┘
│ r2_prefix    text   │
│ node_id      uuid FK├─────┐
│ error_message text  │     │
│ created_at timestamptz    │     ┌─────────────────────┐
│ updated_at timestamptz    │     │     job_files       │
└─────────────────────┘◄────┼─────├─────────────────────┤
                            │     │ id         uuid PK  │
                            │     │ job_id     uuid FK  │
                            │     │ file_type  text     │
                            │     │ r2_key     text     │
                            │     │ file_name  text     │
                            │     │ file_size  bigint   │
                            │     │ metadata   jsonb    │
                            │     │ created_at timestamptz
                            │     └─────────────────────┘
                            │
├───────────────────────────┴─────────────────────────────────────┤
│                         TREE CLUSTER                            │
├─────────────────────────────────────────────────────────────────┤

┌─────────────────────┐     ┌─────────────────────┐
│    tree_nodes       │     │     node_files      │
├─────────────────────┤     ├─────────────────────┤
│ id         uuid PK  │◄────│ id         uuid PK  │
│ parent_id  uuid FK ─┘     │ node_id    uuid FK  │
│ client_id  text     │     │ file_type  text     │
│ node_type  text     │     │ r2_key     text UK  │
│ name       text     │     │ file_name  text     │
│ code       text     │     │ file_size  bigint   │
│ version    int      │     │ mime_type  text     │
│ status     text     │     │ metadata   jsonb    │
│ attributes jsonb    │     │ created_at timestamptz
│ sort_order int      │     │ updated_at timestamptz
│ path       text     │     └─────────────────────┘
│ depth      int      │
│ pdf_status text     │
│ is_locked  bool     │
│ created_at timestamptz
│ updated_at timestamptz
└─────────────────────┘

node_type: 'folder' | 'document'
```

---

## Таблицы

### jobs

Основная таблица задач OCR.

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | uuid | Первичный ключ |
| `client_id` | text | Идентификатор клиента |
| `document_id` | text | SHA256 хеш PDF файла |
| `document_name` | text | Имя PDF файла |
| `task_name` | text | Название задачи |
| `status` | text | `draft`, `queued`, `processing`, `done`, `error` |
| `progress` | real | Прогресс (0.0 - 1.0) |
| `engine` | text | OCR движок: `openrouter`, `datalab` |
| `r2_prefix` | text | Префикс файлов в R2 |
| `error_message` | text | Сообщение об ошибке |

**Индексы:** `client_id`, `document_id`, `status`, `created_at DESC`

---

### job_files

Файлы, связанные с задачей.

| Поле | Тип | Описание |
|------|-----|----------|
| `job_id` | uuid | FK на jobs (CASCADE) |
| `file_type` | text | `pdf`, `blocks`, `annotation`, `result`, `crop` |
| `r2_key` | text | Путь к файлу в R2 |
| `file_size` | bigint | Размер в байтах |
| `metadata` | jsonb | Для кропов: `block_id`, `page_index`, `coords_norm` |

---

### job_settings

Настройки моделей для задачи.

| Поле | Тип | Описание |
|------|-----|----------|
| `job_id` | uuid | FK на jobs (UNIQUE, CASCADE) |
| `text_model` | text | Модель для текста |
| `table_model` | text | Модель для таблиц |
| `image_model` | text | Модель для изображений |

---

### tree_nodes

Иерархия проектов с произвольной вложенностью.

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | uuid | Первичный ключ |
| `parent_id` | uuid | FK на tree_nodes (CASCADE) |
| `client_id` | text | Идентификатор клиента |
| `node_type` | text | `folder` или `document` |
| `name` | text | Название узла |
| `path` | text | Materialized path: `uuid1.uuid2.uuid3` |
| `depth` | int | Глубина от корня (0 = корневой) |
| `pdf_status` | text | Статус PDF документа |
| `attributes` | jsonb | Доп. атрибуты |

**Индексы:** `parent_id`, `client_id`, `path`, `depth`

---

### node_files

Файлы узлов дерева.

| Поле | Тип | Описание |
|------|-----|----------|
| `node_id` | uuid | FK на tree_nodes (CASCADE) |
| `file_type` | text | `pdf`, `annotation`, `result_json`, `result_md`, `crop` |
| `r2_key` | text | Путь к файлу в R2 (UNIQUE с node_id) |
| `file_size` | bigint | Размер в байтах |
| `mime_type` | text | MIME тип |

---

### Справочники

**stage_types** — типы стадий: `ПД` (Проектная документация), `РД` (Рабочая документация)

**section_types** — типы разделов: `АР`, `КР`, `ОВ`, `ВК`, `ЭО`, `СС`, `ГП`, `ПОС`, `ПЗ`

---

## Основные запросы

```sql
-- Задачи клиента
SELECT * FROM jobs WHERE client_id = 'xxx' ORDER BY created_at DESC;

-- Активные задачи
SELECT * FROM jobs WHERE status IN ('queued', 'processing');

-- Файлы задачи
SELECT * FROM job_files WHERE job_id = 'xxx';

-- Дерево проекта (корневые)
SELECT * FROM tree_nodes WHERE parent_id IS NULL AND client_id = 'xxx' ORDER BY sort_order;

-- Дочерние узлы
SELECT * FROM tree_nodes WHERE parent_id = 'xxx' ORDER BY sort_order;
```

---

## Миграции

```bash
# Через Supabase SQL Editor или psql
psql -h db.xxx.supabase.co -U postgres -d postgres -f database/migrations/prod.sql
```
