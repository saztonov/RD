-- Таблица tree_nodes - иерархия проектов
-- Уровни: project(0) -> stage(1) -> section(2) -> task_folder(3) -> document(4)

CREATE TABLE IF NOT EXISTS tree_nodes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_id UUID REFERENCES tree_nodes(id) ON DELETE CASCADE,
    client_id TEXT NOT NULL,
    node_type TEXT NOT NULL CHECK (node_type IN ('project', 'stage', 'section', 'task_folder', 'document')),
    name TEXT NOT NULL,
    code TEXT,  -- Шифр раздела (например AR-01)
    version INTEGER DEFAULT 1,  -- Версия для документов
    status TEXT DEFAULT 'active' CHECK (status IN ('active', 'completed', 'archived')),
    attributes JSONB DEFAULT '{}',
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Таблица для хранения файлов документов
CREATE TABLE IF NOT EXISTS tree_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    node_id UUID NOT NULL REFERENCES tree_nodes(id) ON DELETE CASCADE,
    file_name TEXT NOT NULL,
    r2_key TEXT NOT NULL,
    file_size BIGINT DEFAULT 0,
    mime_type TEXT DEFAULT 'application/pdf',
    version INTEGER DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Справочник стадий
CREATE TABLE IF NOT EXISTS stage_types (
    id SERIAL PRIMARY KEY,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    sort_order INTEGER DEFAULT 0
);

-- Справочник разделов документации
CREATE TABLE IF NOT EXISTS section_types (
    id SERIAL PRIMARY KEY,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    sort_order INTEGER DEFAULT 0
);

-- Заполнение справочников
INSERT INTO stage_types (code, name, sort_order) VALUES 
    ('ПД', 'Проектная документация', 1),
    ('РД', 'Рабочая документация', 2)
ON CONFLICT (code) DO NOTHING;

INSERT INTO section_types (code, name, sort_order) VALUES 
    ('АР', 'Архитектурные решения', 1),
    ('КР', 'Конструктивные решения', 2),
    ('ОВ', 'Отопление и вентиляция', 3),
    ('ВК', 'Водоснабжение и канализация', 4),
    ('ЭО', 'Электрооборудование', 5),
    ('СС', 'Слаботочные системы', 6),
    ('ГП', 'Генеральный план', 7),
    ('ПОС', 'Проект организации строительства', 8),
    ('ПЗ', 'Пояснительная записка', 9)
ON CONFLICT (code) DO NOTHING;

-- Индексы
CREATE INDEX IF NOT EXISTS idx_tree_nodes_parent_id ON tree_nodes(parent_id);
CREATE INDEX IF NOT EXISTS idx_tree_nodes_client_id ON tree_nodes(client_id);
CREATE INDEX IF NOT EXISTS idx_tree_nodes_type ON tree_nodes(node_type);
CREATE INDEX IF NOT EXISTS idx_tree_nodes_sort ON tree_nodes(parent_id, sort_order);
CREATE INDEX IF NOT EXISTS idx_tree_documents_node_id ON tree_documents(node_id);

-- Триггер для updated_at
DROP TRIGGER IF EXISTS update_tree_nodes_updated_at ON tree_nodes;
CREATE TRIGGER update_tree_nodes_updated_at
    BEFORE UPDATE ON tree_nodes
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

