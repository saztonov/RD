-- Migration: tree_nodes v2
-- Description: Добавление произвольной вложенности, materialized path, счётчиков
-- Date: 2025-01-06

-- ============================================================================
-- ЧАСТЬ 1: Добавление новых колонок
-- ============================================================================

-- Materialized path для быстрого обхода дерева (формат: uuid1.uuid2.uuid3)
ALTER TABLE tree_nodes ADD COLUMN IF NOT EXISTS path text;

-- Глубина узла от корня (0 = корневой)
ALTER TABLE tree_nodes ADD COLUMN IF NOT EXISTS depth integer DEFAULT 0;

-- Счётчик прямых дочерних узлов
ALTER TABLE tree_nodes ADD COLUMN IF NOT EXISTS children_count integer DEFAULT 0;

-- Счётчик всех потомков (рекурсивно)
ALTER TABLE tree_nodes ADD COLUMN IF NOT EXISTS descendants_count integer DEFAULT 0;

-- Счётчик файлов в node_files для этого узла
ALTER TABLE tree_nodes ADD COLUMN IF NOT EXISTS files_count integer DEFAULT 0;


-- ============================================================================
-- ЧАСТЬ 2: Вычисление path и depth для существующих данных
-- ============================================================================

-- Рекурсивно вычисляем path и depth
WITH RECURSIVE tree_paths AS (
    -- Корневые узлы (parent_id IS NULL)
    SELECT
        id,
        id::text as computed_path,
        0 as computed_depth
    FROM tree_nodes
    WHERE parent_id IS NULL

    UNION ALL

    -- Рекурсивно добавляем дочерние
    SELECT
        n.id,
        tp.computed_path || '.' || n.id::text as computed_path,
        tp.computed_depth + 1 as computed_depth
    FROM tree_nodes n
    JOIN tree_paths tp ON n.parent_id = tp.id
)
UPDATE tree_nodes t
SET
    path = tp.computed_path,
    depth = tp.computed_depth
FROM tree_paths tp
WHERE t.id = tp.id;


-- ============================================================================
-- ЧАСТЬ 3: Вычисление счётчиков для существующих данных
-- ============================================================================

-- children_count: количество прямых детей
UPDATE tree_nodes t
SET children_count = (
    SELECT COUNT(*)
    FROM tree_nodes c
    WHERE c.parent_id = t.id
);

-- descendants_count: количество всех потомков
-- Используем path для подсчёта (все узлы чей path начинается с текущего)
UPDATE tree_nodes t
SET descendants_count = (
    SELECT COUNT(*)
    FROM tree_nodes d
    WHERE d.path LIKE t.path || '.%'
);

-- files_count: количество файлов в node_files
UPDATE tree_nodes t
SET files_count = (
    SELECT COUNT(*)
    FROM node_files f
    WHERE f.node_id = t.id
);


-- ============================================================================
-- ЧАСТЬ 4: Миграция node_type (сохраняем legacy в attributes)
-- ============================================================================

-- Сохраняем старый node_type в attributes.legacy_node_type
UPDATE tree_nodes
SET attributes = COALESCE(attributes, '{}'::jsonb) || jsonb_build_object('legacy_node_type', node_type)
WHERE node_type IN ('project', 'stage', 'section', 'task_folder');

-- Конвертируем в новые типы
UPDATE tree_nodes
SET node_type = 'folder'
WHERE node_type IN ('project', 'stage', 'section', 'task_folder');

-- document остаётся document (без изменений)


-- ============================================================================
-- ЧАСТЬ 5: Новые индексы для производительности
-- ============================================================================

-- Индекс для поиска потомков по path (LIKE 'prefix.%')
CREATE INDEX IF NOT EXISTS idx_tree_nodes_path
    ON tree_nodes USING btree (path text_pattern_ops);

-- Индекс по глубине
CREATE INDEX IF NOT EXISTS idx_tree_nodes_depth
    ON tree_nodes (depth);

-- Составной индекс для lazy loading дочерних узлов
DROP INDEX IF EXISTS idx_tree_nodes_parent_sort;
CREATE INDEX idx_tree_nodes_parent_sort
    ON tree_nodes (parent_id, sort_order, created_at);

-- Индекс для корневых узлов (parent_id IS NULL)
CREATE INDEX IF NOT EXISTS idx_tree_nodes_roots
    ON tree_nodes (client_id, sort_order)
    WHERE parent_id IS NULL;

-- Индекс для папок (для фильтрации)
CREATE INDEX IF NOT EXISTS idx_tree_nodes_folders
    ON tree_nodes (parent_id, sort_order)
    WHERE node_type = 'folder';


-- ============================================================================
-- ЧАСТЬ 6: Триггеры для автообновления path и depth
-- ============================================================================

-- Функция обновления path и depth при INSERT или UPDATE parent_id
CREATE OR REPLACE FUNCTION update_tree_node_path_and_depth()
RETURNS TRIGGER AS $$
DECLARE
    parent_path text;
    parent_depth integer;
BEGIN
    IF NEW.parent_id IS NULL THEN
        -- Корневой узел
        NEW.path := NEW.id::text;
        NEW.depth := 0;
    ELSE
        -- Получаем path и depth родителя
        SELECT path, depth INTO parent_path, parent_depth
        FROM tree_nodes
        WHERE id = NEW.parent_id;

        IF parent_path IS NULL THEN
            -- Родитель не найден или ещё не обработан
            NEW.path := NEW.id::text;
            NEW.depth := 0;
        ELSE
            NEW.path := parent_path || '.' || NEW.id::text;
            NEW.depth := parent_depth + 1;
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Триггер для INSERT
DROP TRIGGER IF EXISTS tr_tree_nodes_path_insert ON tree_nodes;
CREATE TRIGGER tr_tree_nodes_path_insert
    BEFORE INSERT ON tree_nodes
    FOR EACH ROW
    EXECUTE FUNCTION update_tree_node_path_and_depth();

-- Триггер для UPDATE parent_id
DROP TRIGGER IF EXISTS tr_tree_nodes_path_update ON tree_nodes;
CREATE TRIGGER tr_tree_nodes_path_update
    BEFORE UPDATE OF parent_id ON tree_nodes
    FOR EACH ROW
    WHEN (OLD.parent_id IS DISTINCT FROM NEW.parent_id)
    EXECUTE FUNCTION update_tree_node_path_and_depth();


-- ============================================================================
-- ЧАСТЬ 7: Триггеры для счётчика children_count
-- ============================================================================

CREATE OR REPLACE FUNCTION update_parent_children_count()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.parent_id IS NOT NULL THEN
            UPDATE tree_nodes
            SET children_count = children_count + 1
            WHERE id = NEW.parent_id;
        END IF;
        RETURN NEW;

    ELSIF TG_OP = 'DELETE' THEN
        IF OLD.parent_id IS NOT NULL THEN
            UPDATE tree_nodes
            SET children_count = children_count - 1
            WHERE id = OLD.parent_id;
        END IF;
        RETURN OLD;

    ELSIF TG_OP = 'UPDATE' THEN
        -- Если изменился parent_id
        IF OLD.parent_id IS DISTINCT FROM NEW.parent_id THEN
            IF OLD.parent_id IS NOT NULL THEN
                UPDATE tree_nodes
                SET children_count = children_count - 1
                WHERE id = OLD.parent_id;
            END IF;
            IF NEW.parent_id IS NOT NULL THEN
                UPDATE tree_nodes
                SET children_count = children_count + 1
                WHERE id = NEW.parent_id;
            END IF;
        END IF;
        RETURN NEW;
    END IF;

    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS tr_tree_nodes_children_count ON tree_nodes;
CREATE TRIGGER tr_tree_nodes_children_count
    AFTER INSERT OR UPDATE OF parent_id OR DELETE ON tree_nodes
    FOR EACH ROW
    EXECUTE FUNCTION update_parent_children_count();


-- ============================================================================
-- ЧАСТЬ 8: Триггеры для счётчика descendants_count
-- ============================================================================

CREATE OR REPLACE FUNCTION update_ancestors_descendants_count()
RETURNS TRIGGER AS $$
DECLARE
    ancestor_ids uuid[];
    delta integer;
    path_parts text[];
BEGIN
    IF TG_OP = 'INSERT' THEN
        -- Парсим path для получения предков
        IF NEW.path IS NOT NULL AND NEW.path != NEW.id::text THEN
            path_parts := string_to_array(NEW.path, '.');
            -- Убираем последний элемент (сам узел)
            path_parts := path_parts[1:array_length(path_parts, 1) - 1];

            IF array_length(path_parts, 1) > 0 THEN
                ancestor_ids := path_parts::uuid[];
                UPDATE tree_nodes
                SET descendants_count = descendants_count + 1
                WHERE id = ANY(ancestor_ids);
            END IF;
        END IF;
        RETURN NEW;

    ELSIF TG_OP = 'DELETE' THEN
        -- Уменьшаем счётчики у всех предков
        IF OLD.path IS NOT NULL AND OLD.path != OLD.id::text THEN
            path_parts := string_to_array(OLD.path, '.');
            path_parts := path_parts[1:array_length(path_parts, 1) - 1];

            -- Delta = 1 (сам узел) + его потомки
            delta := 1 + COALESCE(OLD.descendants_count, 0);

            IF array_length(path_parts, 1) > 0 THEN
                ancestor_ids := path_parts::uuid[];
                UPDATE tree_nodes
                SET descendants_count = descendants_count - delta
                WHERE id = ANY(ancestor_ids);
            END IF;
        END IF;
        RETURN OLD;
    END IF;

    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS tr_tree_nodes_descendants_count ON tree_nodes;
CREATE TRIGGER tr_tree_nodes_descendants_count
    AFTER INSERT OR DELETE ON tree_nodes
    FOR EACH ROW
    EXECUTE FUNCTION update_ancestors_descendants_count();


-- ============================================================================
-- ЧАСТЬ 9: Триггеры для счётчика files_count (при изменении node_files)
-- ============================================================================

CREATE OR REPLACE FUNCTION update_node_files_count()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        UPDATE tree_nodes
        SET files_count = files_count + 1
        WHERE id = NEW.node_id;
        RETURN NEW;

    ELSIF TG_OP = 'DELETE' THEN
        UPDATE tree_nodes
        SET files_count = files_count - 1
        WHERE id = OLD.node_id;
        RETURN OLD;

    ELSIF TG_OP = 'UPDATE' THEN
        -- Если изменился node_id
        IF OLD.node_id IS DISTINCT FROM NEW.node_id THEN
            UPDATE tree_nodes
            SET files_count = files_count - 1
            WHERE id = OLD.node_id;

            UPDATE tree_nodes
            SET files_count = files_count + 1
            WHERE id = NEW.node_id;
        END IF;
        RETURN NEW;
    END IF;

    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS tr_node_files_count ON node_files;
CREATE TRIGGER tr_node_files_count
    AFTER INSERT OR UPDATE OF node_id OR DELETE ON node_files
    FOR EACH ROW
    EXECUTE FUNCTION update_node_files_count();


-- ============================================================================
-- ЧАСТЬ 10: Полезные функции
-- ============================================================================

-- Получить всех потомков узла
CREATE OR REPLACE FUNCTION get_tree_descendants(p_node_id uuid)
RETURNS TABLE(
    id uuid,
    name text,
    node_type text,
    depth integer,
    path text
) AS $$
BEGIN
    RETURN QUERY
    SELECT t.id, t.name, t.node_type, t.depth, t.path
    FROM tree_nodes t
    WHERE t.path LIKE (
        SELECT tn.path || '.%' FROM tree_nodes tn WHERE tn.id = p_node_id
    )
    ORDER BY t.path;
END;
$$ LANGUAGE plpgsql;


-- Получить всех предков узла (от корня к узлу)
CREATE OR REPLACE FUNCTION get_tree_ancestors(p_node_id uuid)
RETURNS TABLE(
    id uuid,
    name text,
    depth integer
) AS $$
DECLARE
    node_path text;
    path_parts text[];
BEGIN
    -- Получаем path узла
    SELECT path INTO node_path FROM tree_nodes WHERE tree_nodes.id = p_node_id;

    IF node_path IS NULL THEN
        RETURN;
    END IF;

    -- Парсим path
    path_parts := string_to_array(node_path, '.');

    -- Возвращаем всех предков (кроме самого узла)
    RETURN QUERY
    SELECT t.id, t.name, t.depth
    FROM tree_nodes t
    WHERE t.id = ANY(path_parts[1:array_length(path_parts, 1) - 1]::uuid[])
    ORDER BY t.depth;
END;
$$ LANGUAGE plpgsql;


-- Переместить узел (обновляет path всех потомков)
CREATE OR REPLACE FUNCTION move_tree_node(
    p_node_id uuid,
    p_new_parent_id uuid
) RETURNS boolean AS $$
DECLARE
    old_path text;
    new_parent_path text;
    new_path text;
    new_depth integer;
BEGIN
    -- Получаем текущий путь узла
    SELECT path INTO old_path FROM tree_nodes WHERE id = p_node_id;

    IF old_path IS NULL THEN
        RETURN false;
    END IF;

    -- Определяем новый путь
    IF p_new_parent_id IS NULL THEN
        new_path := p_node_id::text;
        new_depth := 0;
    ELSE
        SELECT path INTO new_parent_path FROM tree_nodes WHERE id = p_new_parent_id;

        IF new_parent_path IS NULL THEN
            RETURN false;
        END IF;

        -- Проверяем что не перемещаем в собственного потомка
        IF new_parent_path LIKE old_path || '.%' THEN
            RETURN false;
        END IF;

        new_path := new_parent_path || '.' || p_node_id::text;
        SELECT depth + 1 INTO new_depth FROM tree_nodes WHERE id = p_new_parent_id;
    END IF;

    -- Обновляем путь у узла и всех потомков
    UPDATE tree_nodes
    SET
        path = new_path || substring(path from length(old_path) + 1),
        depth = depth - (SELECT depth FROM tree_nodes WHERE id = p_node_id) + new_depth,
        parent_id = CASE WHEN id = p_node_id THEN p_new_parent_id ELSE parent_id END,
        updated_at = now()
    WHERE path = old_path OR path LIKE old_path || '.%';

    RETURN true;
END;
$$ LANGUAGE plpgsql;


-- ============================================================================
-- ЧАСТЬ 11: Миграция job_files -> node_files для существующих jobs с node_id
-- ============================================================================

-- Добавляем уникальный constraint для upsert в node_files
-- (если ещё не существует)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'node_files_node_id_r2_key_unique'
    ) THEN
        ALTER TABLE node_files
        ADD CONSTRAINT node_files_node_id_r2_key_unique
        UNIQUE (node_id, r2_key);
    END IF;
END $$;

-- Переносим записи из job_files в node_files для завершённых jobs с node_id
-- Маппинг типов: job_files → node_files
--   result → result_json
--   ocr_html → ocr_html (без изменений)
--   annotation → annotation (без изменений)
--   crop → crop (без изменений)
INSERT INTO node_files (id, node_id, file_type, r2_key, file_name, file_size, metadata, created_at)
SELECT
    gen_random_uuid(),
    j.node_id,
    CASE jf.file_type
        WHEN 'result' THEN 'result_json'
        WHEN 'result_md' THEN 'result_md'
        WHEN 'document_md' THEN 'result_md'
        WHEN 'ocr_html' THEN 'ocr_html'
        WHEN 'annotation' THEN 'annotation'
        WHEN 'crop' THEN 'crop'
        ELSE jf.file_type
    END as file_type,
    jf.r2_key,
    jf.file_name,
    jf.file_size,
    jsonb_build_object('migrated_from_job', j.id, 'migrated_at', now()),
    jf.created_at
FROM job_files jf
JOIN jobs j ON jf.job_id = j.id
WHERE j.node_id IS NOT NULL
  AND j.status = 'done'
  -- Только типы которые можно мигрировать в node_files
  AND jf.file_type IN ('result', 'result_md', 'document_md', 'ocr_html', 'annotation', 'crop', 'result_json', 'result_zip', 'image')
ON CONFLICT (node_id, r2_key) DO NOTHING;


-- ============================================================================
-- ЧАСТЬ 12: Добавляем поле migrated_to_node в jobs
-- ============================================================================

ALTER TABLE jobs ADD COLUMN IF NOT EXISTS migrated_to_node boolean DEFAULT false;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS migrated_at timestamptz;

-- Помечаем уже мигрированные jobs
UPDATE jobs
SET migrated_to_node = true, migrated_at = now()
WHERE node_id IS NOT NULL AND status = 'done';


-- ============================================================================
-- КОММЕНТАРИИ
-- ============================================================================

COMMENT ON COLUMN tree_nodes.path IS 'Materialized path: uuid1.uuid2.uuid3 для быстрого поиска предков/потомков';
COMMENT ON COLUMN tree_nodes.depth IS 'Глубина узла от корня (0 = корневой проект)';
COMMENT ON COLUMN tree_nodes.children_count IS 'Количество прямых дочерних узлов (обновляется триггером)';
COMMENT ON COLUMN tree_nodes.descendants_count IS 'Количество всех потомков (обновляется триггером)';
COMMENT ON COLUMN tree_nodes.files_count IS 'Количество файлов в node_files для этого узла (обновляется триггером)';
COMMENT ON COLUMN jobs.migrated_to_node IS 'Флаг: результаты перенесены в node_files';
COMMENT ON COLUMN jobs.migrated_at IS 'Время переноса результатов в node_files';
