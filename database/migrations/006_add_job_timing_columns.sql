-- Миграция: Добавить колонки времени и статистики в таблицу jobs
-- Эти колонки используются в storage_jobs.py для отслеживания прогресса задач

ALTER TABLE public.jobs
ADD COLUMN IF NOT EXISTS started_at timestamp with time zone,
ADD COLUMN IF NOT EXISTS completed_at timestamp with time zone,
ADD COLUMN IF NOT EXISTS block_stats jsonb;

COMMENT ON COLUMN public.jobs.started_at IS 'Время начала обработки задачи';
COMMENT ON COLUMN public.jobs.completed_at IS 'Время завершения обработки задачи';
COMMENT ON COLUMN public.jobs.block_stats IS 'Статистика обработанных блоков (количество по типам)';
