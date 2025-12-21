-- ============================================
-- RD Project Database Schema
-- Единая схема БД для Supabase
-- ============================================


-- ============================================
-- УДАЛЕНИЕ СУЩЕСТВУЮЩЕЙ СТРУКТУРЫ
-- ============================================

-- Триггеры
DROP TRIGGER IF EXISTS update_tree_nodes_updated_at ON tree_nodes;
DROP TRIGGER IF EXISTS update_node_files_updated_at ON node_files;
DROP TRIGGER IF EXISTS update_jobs_updated_at ON jobs;
DROP TRIGGER IF EXISTS update_job_settings_updated_at ON job_settings;

-- Индексы
DROP INDEX IF EXISTS idx_tree_nodes_parent_id;
DROP INDEX IF EXISTS idx_tree_nodes_client_id;
DROP INDEX IF EXISTS idx_tree_nodes_type;
DROP INDEX IF EXISTS idx_tree_nodes_sort;
DROP INDEX IF EXISTS idx_node_files_node_id;
DROP INDEX IF EXISTS idx_node_files_type;
DROP INDEX IF EXISTS idx_node_files_r2_key;
DROP INDEX IF EXISTS idx_node_files_unique_r2;
DROP INDEX IF EXISTS idx_jobs_client_id;
DROP INDEX IF EXISTS idx_jobs_document_id;
DROP INDEX IF EXISTS idx_jobs_status;
DROP INDEX IF EXISTS idx_jobs_node_id;
DROP INDEX IF EXISTS idx_jobs_created_at;
DROP INDEX IF EXISTS idx_job_files_job_id;
DROP INDEX IF EXISTS idx_job_files_type;
DROP INDEX IF EXISTS idx_job_settings_job_id;

-- Таблицы (порядок важен из-за FK)
DROP TABLE IF EXISTS job_settings CASCADE;
DROP TABLE IF EXISTS job_files CASCADE;
DROP TABLE IF EXISTS jobs CASCADE;
DROP TABLE IF EXISTS node_files CASCADE;
DROP TABLE IF EXISTS tree_documents CASCADE;  -- deprecated, удаляем если есть
DROP TABLE IF EXISTS tree_nodes CASCADE;
DROP TABLE IF EXISTS section_types CASCADE;
DROP TABLE IF EXISTS stage_types CASCADE;

-- Функции
DROP FUNCTION IF EXISTS update_updated_at_column() CASCADE;


-- ============================================
-- СОЗДАНИЕ СТРУКТУРЫ
-- ============================================

-- Функция для автообновления updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;


-- ============================================
-- ТАБЛИЦЫ
-- ============================================

-- Дерево проектов (узлы: client, project, section, stage, task, document)
CREATE TABLE IF NOT EXISTS tree_nodes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_id UUID REFERENCES tree_nodes(id) ON DELETE CASCADE,
    client_id TEXT NOT NULL,
    node_type TEXT NOT NULL,  -- 'client', 'project', 'section', 'stage', 'task', 'document'
    name TEXT NOT NULL,
    code TEXT,
    version INTEGER DEFAULT 1,
    status TEXT DEFAULT 'active',  -- 'active', 'archived', 'deleted'
    attributes JSONB DEFAULT '{}',
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE tree_nodes IS 'Дерево проектов - иерархическая структура узлов';
COMMENT ON COLUMN tree_nodes.node_type IS 'Тип узла: client, project, section, stage, task, document';
COMMENT ON COLUMN tree_nodes.attributes IS 'Дополнительные атрибуты узла (JSON)';


-- Все файлы привязанные к узлам дерева (PDF, аннотации, результаты OCR, кропы)
CREATE TABLE IF NOT EXISTS node_files (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    node_id UUID NOT NULL REFERENCES tree_nodes(id) ON DELETE CASCADE,
    file_type TEXT NOT NULL,  -- 'pdf', 'annotation', 'result_md', 'result_zip', 'crop', 'image'
    r2_key TEXT NOT NULL,
    file_name TEXT NOT NULL,
    file_size BIGINT DEFAULT 0,
    mime_type TEXT DEFAULT 'application/octet-stream',
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    CONSTRAINT node_files_file_type_check CHECK (
        file_type IN ('pdf', 'annotation', 'result_md', 'result_zip', 'crop', 'image')
    )
);

COMMENT ON TABLE node_files IS 'Все файлы привязанные к узлам дерева (PDF, аннотации, markdown, кропы)';
COMMENT ON COLUMN node_files.file_type IS 'Тип файла: pdf, annotation, result_md, result_zip, crop, image';
COMMENT ON COLUMN node_files.r2_key IS 'Ключ объекта в R2 storage';
COMMENT ON COLUMN node_files.metadata IS 'Метаданные: version, page_index для кропов и т.д.';


-- OCR задачи
CREATE TABLE IF NOT EXISTS jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id TEXT NOT NULL,
    document_id TEXT NOT NULL,  -- хеш PDF файла
    document_name TEXT NOT NULL,
    task_name TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'queued',  -- 'draft', 'queued', 'processing', 'done', 'error', 'paused'
    progress REAL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    error_message TEXT,
    engine TEXT DEFAULT '',  -- 'openrouter', 'datalab'
    r2_prefix TEXT,
    node_id UUID REFERENCES tree_nodes(id) ON DELETE SET NULL
);

COMMENT ON TABLE jobs IS 'OCR задачи обработки документов';
COMMENT ON COLUMN jobs.node_id IS 'ID узла дерева документа (для связи OCR результатов с деревом проектов)';
COMMENT ON COLUMN jobs.document_id IS 'Хеш PDF файла для идентификации';


-- Файлы OCR задач (входные блоки, результаты)
CREATE TABLE IF NOT EXISTS job_files (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    file_type TEXT NOT NULL,  -- 'blocks', 'pdf', 'result_md', 'result_zip'
    r2_key TEXT NOT NULL,
    file_name TEXT NOT NULL,
    file_size BIGINT DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE job_files IS 'Файлы связанные с OCR задачами';


-- Настройки OCR задач (модели)
CREATE TABLE IF NOT EXISTS job_settings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID NOT NULL UNIQUE REFERENCES jobs(id) ON DELETE CASCADE,
    text_model TEXT DEFAULT '',
    table_model TEXT DEFAULT '',
    image_model TEXT DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE job_settings IS 'Настройки моделей для OCR задач';


-- Справочник типов разделов
CREATE TABLE IF NOT EXISTS section_types (
    id SERIAL PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    sort_order INTEGER DEFAULT 0
);


-- Справочник типов стадий
CREATE TABLE IF NOT EXISTS stage_types (
    id SERIAL PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    sort_order INTEGER DEFAULT 0
);


-- ============================================
-- ТРИГГЕРЫ
-- ============================================

CREATE TRIGGER update_tree_nodes_updated_at 
    BEFORE UPDATE ON tree_nodes 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_node_files_updated_at 
    BEFORE UPDATE ON node_files 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_jobs_updated_at 
    BEFORE UPDATE ON jobs 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_job_settings_updated_at 
    BEFORE UPDATE ON job_settings 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();


-- ============================================
-- ИНДЕКСЫ
-- ============================================

-- tree_nodes
CREATE INDEX idx_tree_nodes_parent_id ON tree_nodes(parent_id);
CREATE INDEX idx_tree_nodes_client_id ON tree_nodes(client_id);
CREATE INDEX idx_tree_nodes_type ON tree_nodes(node_type);
CREATE INDEX idx_tree_nodes_sort ON tree_nodes(parent_id, sort_order);

-- node_files
CREATE INDEX idx_node_files_node_id ON node_files(node_id);
CREATE INDEX idx_node_files_type ON node_files(file_type);
CREATE INDEX idx_node_files_r2_key ON node_files(r2_key);
CREATE UNIQUE INDEX idx_node_files_unique_r2 ON node_files(node_id, r2_key);

-- jobs
CREATE INDEX idx_jobs_client_id ON jobs(client_id);
CREATE INDEX idx_jobs_document_id ON jobs(document_id);
CREATE INDEX idx_jobs_status ON jobs(status);
CREATE INDEX idx_jobs_node_id ON jobs(node_id);
CREATE INDEX idx_jobs_created_at ON jobs(created_at DESC);

-- job_files
CREATE INDEX idx_job_files_job_id ON job_files(job_id);
CREATE INDEX idx_job_files_type ON job_files(file_type);

-- job_settings
CREATE INDEX idx_job_settings_job_id ON job_settings(job_id);


-- ============================================
-- НАЧАЛЬНЫЕ ДАННЫЕ
-- ============================================

-- Типы разделов проекта (русские коды)
INSERT INTO section_types (code, name, sort_order) VALUES
    ('АР', 'Архитектурные решения', 1),
    ('КЖ', 'Конструкции железобетонные', 2),
    ('КМ', 'Конструкции металлические', 3),
    ('КД', 'Конструкции деревянные', 4),
    ('ОВ', 'Отопление и вентиляция', 5),
    ('ВК', 'Водоснабжение и канализация', 6),
    ('ЭО', 'Электрооборудование', 7),
    ('ЭС', 'Электроснабжение', 8),
    ('СС', 'Слаботочные системы', 9),
    ('ГП', 'Генеральный план', 10),
    ('ПОС', 'Проект организации строительства', 11),
    ('ПОД', 'Проект организации демонтажа', 12),
    ('СМ', 'Сметная документация', 13),
    ('ПЗ', 'Пояснительная записка', 14),
    ('ТХ', 'Технологические решения', 15)
ON CONFLICT (code) DO NOTHING;

-- Типы стадий проекта (русские коды)
INSERT INTO stage_types (code, name, sort_order) VALUES
    ('ПД', 'Проектная документация', 1),
    ('РД', 'Рабочая документация', 2),
    ('ИД', 'Исполнительная документация', 3)
ON CONFLICT (code) DO NOTHING;

