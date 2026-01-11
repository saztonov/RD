-- Миграция: добавление client_id в таблицу jobs
-- Дата: 2025-01-11
-- Описание: Добавляет колонку client_id для идентификации клиента

-- Добавляем колонку client_id (с дефолтным значением для обратной совместимости)
ALTER TABLE public.jobs
ADD COLUMN IF NOT EXISTS client_id text NOT NULL DEFAULT 'default';

-- Убираем default после добавления (новые записи должны явно указывать client_id)
ALTER TABLE public.jobs
ALTER COLUMN client_id DROP DEFAULT;

-- Создаем индекс для быстрого поиска по client_id
CREATE INDEX IF NOT EXISTS idx_jobs_client_id ON public.jobs(client_id);

-- Комментарий к колонке
COMMENT ON COLUMN public.jobs.client_id IS 'Идентификатор клиента (из ~/.config/CoreStructure/client_id.txt)';
