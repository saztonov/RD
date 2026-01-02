# Схема базы данных

## Обзор

Приложение использует **Supabase** (PostgreSQL) для хранения:
- Задач OCR и их файлов
- Иерархии проектов (Tree)
- Справочников (типы стадий и разделов)

## ER-диаграмма

```
┌─────────────────────┐     ┌─────────────────────┐
│       jobs          │     │    job_settings     │
├─────────────────────┤     ├─────────────────────┤
│ id           uuid PK│◄────│ job_id    uuid PK FK│
│ client_id    text   │     │ text_model    text  │
│ document_id  text   │     │ table_model   text  │
│ document_name text  │     │ image_model   text  │
│ task_name    text   │     │ created_at timestamptz
│ status       text   │     │ updated_at timestamptz
│ progress     real   │     └─────────────────────┘
│ engine       text   │
│ r2_prefix    text   │     ┌─────────────────────┐
│ error_message text  │     │     job_files       │
│ created_at timestamptz    ├─────────────────────┤
│ updated_at timestamptz    │ id         uuid PK  │
└─────────────────────┘◄────│ job_id     uuid FK  │
                            │ file_type  text     │
                            │ r2_key     text     │
                            │ file_name  text     │
                            │ file_size  bigint   │
                            │ created_at timestamptz
                            └─────────────────────┘


┌─────────────────────┐     ┌─────────────────────┐
│    tree_nodes       │     │   tree_documents    │
├─────────────────────┤     ├─────────────────────┤
│ id         uuid PK  │◄────│ id         uuid PK  │
│ parent_id  uuid FK ─┘     │ node_id    uuid FK  │
│ client_id  text     │     │ file_name  text     │
│ node_type  text     │     │ r2_key     text     │
│ name       text     │     │ file_size  bigint   │
│ code       text     │     │ mime_type  text     │
│ version    int      │     │ version    int      │
│ status     text     │     │ created_at timestamptz
│ attributes jsonb    │     └─────────────────────┘
│ sort_order int      │
│ created_at timestamptz
│ updated_at timestamptz
└─────────────────────┘


┌─────────────────────┐     ┌─────────────────────┐
│    stage_types      │     │   section_types     │
├─────────────────────┤     ├─────────────────────┤
│ id         serial PK│     │ id         serial PK│
│ code       text UK  │     │ code       text UK  │
│ name       text     │     │ name       text     │
│ sort_order int      │     │ sort_order int      │
└─────────────────────┘     └─────────────────────┘
```

---

## Таблицы

### jobs

Основная таблица задач OCR.

```sql
CREATE TABLE jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id text NOT NULL,
    document_id text NOT NULL,
    document_name text NOT NULL,
    task_name text NOT NULL DEFAULT '',
    status text NOT NULL DEFAULT 'queued',
    progress real DEFAULT 0,
    engine text DEFAULT '',
    r2_prefix text,
    error_message text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
```

#### Поля

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | uuid | Первичный ключ |
| `client_id` | text | Идентификатор клиента (из `~/.config/CoreStructure/client_id.txt`) |
| `document_id` | text | SHA256 хеш PDF файла |
| `document_name` | text | Имя PDF файла |
| `task_name` | text | Название задачи (пользовательское) |
| `status` | text | Статус: `draft`, `queued`, `processing`, `done`, `error`, `paused` |
| `progress` | real | Прогресс выполнения (0.0 - 1.0) |
| `engine` | text | OCR движок: `openrouter`, `datalab` |
| `r2_prefix` | text | Префикс файлов в R2 (`ocr_jobs/{job_id}`) |
| `error_message` | text | Сообщение об ошибке (если status=error) |
| `created_at` | timestamptz | Дата создания |
| `updated_at` | timestamptz | Дата последнего обновления |

#### Индексы

```sql
CREATE INDEX idx_jobs_client_id ON jobs(client_id);
CREATE INDEX idx_jobs_document_id ON jobs(document_id);
CREATE INDEX idx_jobs_status ON jobs(status);
CREATE INDEX idx_jobs_created_at ON jobs(created_at DESC);
```

#### Триггер

```sql
CREATE TRIGGER update_jobs_updated_at
    BEFORE UPDATE ON jobs
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
```

---

### job_files

Файлы, связанные с задачей.

```sql
CREATE TABLE job_files (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id uuid NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    file_type text NOT NULL,
    r2_key text NOT NULL,
    file_name text NOT NULL,
    file_size bigint DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now()
);
```

#### Типы файлов (file_type)

| Тип | Описание |
|-----|----------|
| `pdf` | Исходный PDF документ |
| `blocks` | blocks.json с координатами блоков |
| `annotation` | annotation.json с полной разметкой |
| `result_md` | result.md — результат OCR |
| `result_zip` | result.zip — архив с результатами |
| `crop` | Кроп блока (PDF) |

#### Индексы

```sql
CREATE INDEX idx_job_files_job_id ON job_files(job_id);
CREATE INDEX idx_job_files_type ON job_files(file_type);
```

---

### job_settings

Настройки моделей для задачи.

```sql
CREATE TABLE job_settings (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id uuid NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    text_model text DEFAULT '',
    table_model text DEFAULT '',
    image_model text DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(job_id)
);
```

#### Примеры моделей

| Поле | Пример значения |
|------|-----------------|
| `text_model` | `qwen/qwen3-vl-30b-a3b-instruct` |
| `table_model` | `google/gemini-2.5-flash-preview-05-20` |
| `image_model` | `openai/gpt-4o` |

---

### tree_nodes

Иерархия проектов.

```sql
CREATE TABLE tree_nodes (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_id uuid REFERENCES tree_nodes(id) ON DELETE CASCADE,
    client_id text NOT NULL,
    node_type text NOT NULL,
    name text NOT NULL,
    code text,
    version integer DEFAULT 1,
    status text DEFAULT 'active',
    attributes jsonb DEFAULT '{}',
    sort_order integer DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    
    CHECK (node_type IN ('project', 'stage', 'section', 'task_folder', 'document')),
    CHECK (status IN ('active', 'completed', 'archived'))
);
```

#### Типы узлов (node_type)

| Тип | Уровень | Родитель | Описание |
|-----|---------|----------|----------|
| `project` | 0 | NULL | Проект (корневой) |
| `stage` | 1 | project | Стадия (ПД/РД) |
| `section` | 2 | stage | Раздел (АР, КР, ОВ...) |
| `task_folder` | 3 | section | Папка заданий |
| `document` | 4 | task_folder | Документ PDF |

#### Поле attributes

```json
// Для document
{
  "original_name": "план_этажа.pdf",
  "r2_key": "documents/uuid/file.pdf",
  "file_size": 1234567,
  "mime_type": "application/pdf",
  "local_path": "C:/path/to/file.pdf"
}
```

#### Индексы

```sql
CREATE INDEX idx_tree_nodes_parent_id ON tree_nodes(parent_id);
CREATE INDEX idx_tree_nodes_client_id ON tree_nodes(client_id);
CREATE INDEX idx_tree_nodes_type ON tree_nodes(node_type);
CREATE INDEX idx_tree_nodes_sort ON tree_nodes(parent_id, sort_order);
```

---

### tree_documents

Файлы документов (версионирование).

```sql
CREATE TABLE tree_documents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    node_id uuid NOT NULL REFERENCES tree_nodes(id) ON DELETE CASCADE,
    file_name text NOT NULL,
    r2_key text NOT NULL,
    file_size bigint DEFAULT 0,
    mime_type text DEFAULT 'application/pdf',
    version integer DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now()
);
```

---

### stage_types

Справочник типов стадий.

```sql
CREATE TABLE stage_types (
    id serial PRIMARY KEY,
    code text UNIQUE NOT NULL,
    name text NOT NULL,
    sort_order integer DEFAULT 0
);

-- Предзаполнение
INSERT INTO stage_types (code, name, sort_order) VALUES
    ('ПД', 'Проектная документация', 1),
    ('РД', 'Рабочая документация', 2);
```

---

### section_types

Справочник типов разделов.

```sql
CREATE TABLE section_types (
    id serial PRIMARY KEY,
    code text UNIQUE NOT NULL,
    name text NOT NULL,
    sort_order integer DEFAULT 0
);

-- Предзаполнение
INSERT INTO section_types (code, name, sort_order) VALUES
    ('АР', 'Архитектурные решения', 1),
    ('КР', 'Конструктивные решения', 2),
    ('ОВ', 'Отопление и вентиляция', 3),
    ('ВК', 'Водоснабжение и канализация', 4),
    ('ЭО', 'Электрооборудование', 5),
    ('СС', 'Слаботочные системы', 6),
    ('ГП', 'Генеральный план', 7),
    ('ПОС', 'Проект организации строительства', 8),
    ('ПЗ', 'Пояснительная записка', 9);
```

---

## Функции

### update_updated_at_column

Автоматическое обновление `updated_at`.

```sql
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;
```

---

## Триггеры

```sql
-- jobs
CREATE TRIGGER update_jobs_updated_at
    BEFORE UPDATE ON jobs
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- job_settings
CREATE TRIGGER update_job_settings_updated_at
    BEFORE UPDATE ON job_settings
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- tree_nodes
CREATE TRIGGER update_tree_nodes_updated_at
    BEFORE UPDATE ON tree_nodes
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
```

---

## Миграции

### Создание схемы

```bash
# Через Supabase SQL Editor или psql
psql -h db.xxx.supabase.co -U postgres -d postgres -f tree_schema.sql
psql -h db.xxx.supabase.co -U postgres -d postgres -f database/migrations/prod.sql
```

### Экспорт схемы

```bash
pg_dump -h db.xxx.supabase.co -U postgres -d postgres \
    --schema-only --no-owner --no-privileges \
    > database/migrations/schema_export.sql
```

---

## Запросы

### Получить задачи клиента

```sql
SELECT * FROM jobs
WHERE client_id = 'xxx-xxx-xxx'
ORDER BY created_at DESC;
```

### Получить активные задачи

```sql
SELECT * FROM jobs
WHERE status IN ('queued', 'processing')
ORDER BY created_at;
```

### Получить файлы задачи

```sql
SELECT * FROM job_files
WHERE job_id = 'xxx-xxx-xxx'
ORDER BY file_type;
```

### Получить дерево проекта

```sql
-- Корневые проекты
SELECT * FROM tree_nodes
WHERE parent_id IS NULL
  AND client_id = 'xxx-xxx-xxx'
ORDER BY sort_order, created_at;

-- Дочерние узлы
SELECT * FROM tree_nodes
WHERE parent_id = 'xxx-xxx-xxx'
ORDER BY sort_order, created_at;
```

### Рекурсивный запрос всего дерева

```sql
WITH RECURSIVE tree AS (
    SELECT *, 0 as level
    FROM tree_nodes
    WHERE parent_id IS NULL AND client_id = 'xxx-xxx-xxx'
    
    UNION ALL
    
    SELECT tn.*, t.level + 1
    FROM tree_nodes tn
    JOIN tree t ON tn.parent_id = t.id
)
SELECT * FROM tree
ORDER BY level, sort_order;
```

### Подсчёт задач по статусам

```sql
SELECT status, COUNT(*) as count
FROM jobs
GROUP BY status
ORDER BY count DESC;
```

---

## RLS (Row Level Security)

Для production рекомендуется включить RLS:

```sql
-- Включить RLS
ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE tree_nodes ENABLE ROW LEVEL SECURITY;

-- Политика: клиент видит только свои данные
CREATE POLICY jobs_client_policy ON jobs
    USING (client_id = current_setting('app.client_id', true));

CREATE POLICY tree_nodes_client_policy ON tree_nodes
    USING (client_id = current_setting('app.client_id', true));
```

---

## Резервное копирование

### Ручной бэкап

```bash
pg_dump -h db.xxx.supabase.co -U postgres -d postgres \
    --data-only \
    -t jobs -t job_files -t job_settings \
    -t tree_nodes -t tree_documents \
    > backup_$(date +%Y%m%d).sql
```

### Восстановление

```bash
psql -h db.xxx.supabase.co -U postgres -d postgres \
    < backup_20250120.sql
```

---

## Мониторинг

### Размер таблиц

```sql
SELECT
    relname as table_name,
    pg_size_pretty(pg_total_relation_size(relid)) as total_size
FROM pg_catalog.pg_statio_user_tables
ORDER BY pg_total_relation_size(relid) DESC;
```

### Количество записей

```sql
SELECT
    'jobs' as table_name, COUNT(*) FROM jobs
UNION ALL
SELECT
    'job_files', COUNT(*) FROM job_files
UNION ALL
SELECT
    'tree_nodes', COUNT(*) FROM tree_nodes;
```

### Медленные запросы

```sql
SELECT
    query,
    calls,
    mean_exec_time,
    total_exec_time
FROM pg_stat_statements
ORDER BY mean_exec_time DESC
LIMIT 10;
```

