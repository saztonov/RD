-- ============================================
-- Migration: 011_blocks_table.sql
-- Description: Таблица блоков аннотаций PDF документов
-- ============================================

-- Table: public.blocks
-- Description: Блоки разметки PDF документов (замена annotation.json)
CREATE TABLE IF NOT EXISTS public.blocks (
    id text NOT NULL,                                               -- ArmorID format (XXXX-XXXX-XXX)
    node_id uuid NOT NULL,                                          -- Ссылка на документ (tree_nodes)
    page_index integer NOT NULL,                                    -- Индекс страницы (0-based)

    -- Координаты
    coords_px integer[] NOT NULL,                                   -- [x1, y1, x2, y2] в пикселях
    coords_norm real[] NOT NULL,                                    -- [x1, y1, x2, y2] нормализованные 0..1

    -- Тип и форма
    block_type text NOT NULL DEFAULT 'text',                        -- 'text' | 'image'
    source text NOT NULL DEFAULT 'user',                            -- 'user' | 'auto'
    shape_type text NOT NULL DEFAULT 'rectangle',                   -- 'rectangle' | 'polygon'
    polygon_points jsonb,                                           -- [[x1,y1], [x2,y2], ...] для полигонов

    -- OCR данные
    ocr_text text,                                                  -- Результат OCR
    prompt jsonb,                                                   -- {"system": "...", "user": "..."}
    hint text,                                                      -- Подсказка пользователя для OCR
    pdfplumber_text text,                                           -- Сырой текст из pdfplumber

    -- Связи и группировка
    linked_block_id text,                                           -- Связанный блок (IMAGE+TEXT)
    group_id text,                                                  -- ID группы блоков
    group_name text,                                                -- Название группы
    category_id uuid,                                               -- Категория изображения
    category_code text,                                             -- Код категории (stamp, table, etc)

    -- Мультиклиентность и версионирование
    client_id text,                                                 -- ID клиента (для фильтрации)
    version integer NOT NULL DEFAULT 1,                             -- Версия для optimistic locking
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    updated_at timestamp with time zone NOT NULL DEFAULT now(),

    -- Констрейнты
    CONSTRAINT blocks_pkey PRIMARY KEY (id),
    CONSTRAINT blocks_node_id_fkey FOREIGN KEY (node_id)
        REFERENCES public.tree_nodes(id) ON DELETE CASCADE,
    CONSTRAINT blocks_category_id_fkey FOREIGN KEY (category_id)
        REFERENCES public.image_categories(id) ON DELETE SET NULL
);

-- Комментарии
COMMENT ON TABLE public.blocks IS 'Блоки аннотаций PDF документов (замена annotation.json)';
COMMENT ON COLUMN public.blocks.id IS 'ArmorID блока (формат XXXX-XXXX-XXX)';
COMMENT ON COLUMN public.blocks.node_id IS 'Ссылка на документ в tree_nodes';
COMMENT ON COLUMN public.blocks.page_index IS 'Индекс страницы (0-based)';
COMMENT ON COLUMN public.blocks.coords_px IS 'Координаты в пикселях [x1, y1, x2, y2]';
COMMENT ON COLUMN public.blocks.coords_norm IS 'Нормализованные координаты [x1, y1, x2, y2] в диапазоне 0..1';
COMMENT ON COLUMN public.blocks.block_type IS 'Тип блока: text или image';
COMMENT ON COLUMN public.blocks.source IS 'Источник блока: user (ручной) или auto (OCR)';
COMMENT ON COLUMN public.blocks.shape_type IS 'Форма блока: rectangle или polygon';
COMMENT ON COLUMN public.blocks.polygon_points IS 'Точки полигона [[x1,y1], [x2,y2], ...] для shape_type=polygon';
COMMENT ON COLUMN public.blocks.ocr_text IS 'Результат OCR распознавания';
COMMENT ON COLUMN public.blocks.prompt IS 'Промпт для OCR {"system": "...", "user": "..."}';
COMMENT ON COLUMN public.blocks.hint IS 'Подсказка пользователя для OCR';
COMMENT ON COLUMN public.blocks.pdfplumber_text IS 'Сырой текст извлеченный pdfplumber';
COMMENT ON COLUMN public.blocks.linked_block_id IS 'ID связанного блока (для пар IMAGE+TEXT)';
COMMENT ON COLUMN public.blocks.group_id IS 'ID группы блоков';
COMMENT ON COLUMN public.blocks.group_name IS 'Название группы блоков';
COMMENT ON COLUMN public.blocks.category_id IS 'ID категории изображения';
COMMENT ON COLUMN public.blocks.category_code IS 'Код категории (stamp, table, etc)';
COMMENT ON COLUMN public.blocks.client_id IS 'ID клиента для мультиклиентности';
COMMENT ON COLUMN public.blocks.version IS 'Версия для optimistic concurrency control';
COMMENT ON COLUMN public.blocks.created_at IS 'Дата и время создания блока';
COMMENT ON COLUMN public.blocks.updated_at IS 'Дата и время последнего обновления';

-- Индексы для производительности
CREATE INDEX idx_blocks_node_id ON public.blocks(node_id);
CREATE INDEX idx_blocks_node_page ON public.blocks(node_id, page_index);
CREATE INDEX idx_blocks_group_id ON public.blocks(group_id) WHERE group_id IS NOT NULL;
CREATE INDEX idx_blocks_client_id ON public.blocks(client_id) WHERE client_id IS NOT NULL;
CREATE INDEX idx_blocks_updated_at ON public.blocks(updated_at DESC);

-- Триггер для автообновления updated_at
CREATE OR REPLACE FUNCTION update_blocks_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER tr_blocks_updated_at
    BEFORE UPDATE ON public.blocks
    FOR EACH ROW
    EXECUTE FUNCTION update_blocks_updated_at();

-- Включаем Realtime для таблицы blocks
ALTER PUBLICATION supabase_realtime ADD TABLE public.blocks;

-- Права доступа
GRANT ALL ON TABLE public.blocks TO anon;
GRANT ALL ON TABLE public.blocks TO authenticated;
GRANT ALL ON TABLE public.blocks TO service_role;
