-- Миграция: Категории изображений с промптами
-- Дата: 2024-12-28

-- Таблица категорий изображений
CREATE TABLE IF NOT EXISTS public.image_categories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    code TEXT NOT NULL UNIQUE,
    description TEXT,
    system_prompt TEXT NOT NULL DEFAULT '',
    user_prompt TEXT NOT NULL DEFAULT '',
    is_default BOOLEAN DEFAULT FALSE,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT now() NOT NULL
);

-- Комментарии
COMMENT ON TABLE public.image_categories IS 'Категории изображений с промптами для OCR';
COMMENT ON COLUMN public.image_categories.name IS 'Отображаемое название категории';
COMMENT ON COLUMN public.image_categories.code IS 'Уникальный код категории (slug)';
COMMENT ON COLUMN public.image_categories.system_prompt IS 'System/Role промпт для модели';
COMMENT ON COLUMN public.image_categories.user_prompt IS 'User Input промпт для модели';
COMMENT ON COLUMN public.image_categories.is_default IS 'Категория по умолчанию для всех новых IMAGE блоков';

-- Индексы
CREATE INDEX IF NOT EXISTS idx_image_categories_code ON public.image_categories(code);
CREATE INDEX IF NOT EXISTS idx_image_categories_is_default ON public.image_categories(is_default) WHERE is_default = TRUE;

-- Триггер обновления updated_at
CREATE OR REPLACE FUNCTION update_image_categories_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_image_categories_updated_at ON public.image_categories;
CREATE TRIGGER trigger_image_categories_updated_at
    BEFORE UPDATE ON public.image_categories
    FOR EACH ROW
    EXECUTE FUNCTION update_image_categories_updated_at();

-- Вставка категории по умолчанию
INSERT INTO public.image_categories (name, code, description, system_prompt, user_prompt, is_default, sort_order)
VALUES (
    'По умолчанию',
    'default',
    'Базовая категория для всех изображений',
    'You are an expert design engineer and automation specialist. Your task is to analyze technical drawings and extract data into structured JSON format with 100% accuracy. Do not omit details. Do not hallucinate values.',
    'Analyze this image and extract all relevant information. Return the result as a valid JSON object.',
    TRUE,
    0
)
ON CONFLICT (code) DO NOTHING;



