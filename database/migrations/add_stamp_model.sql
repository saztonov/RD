-- Добавление поля stamp_model в таблицу job_settings
-- Дата: 2026-01-02

-- Добавить колонку stamp_model в job_settings
ALTER TABLE job_settings
ADD COLUMN IF NOT EXISTS stamp_model TEXT DEFAULT '';

-- Комментарий к колонке
COMMENT ON COLUMN job_settings.stamp_model IS 'Модель для распознавания штампов (IMAGE блоки с code=stamp)';
