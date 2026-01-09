-- Migration: add_metadata_to_job_files
-- Description: Добавление поля metadata в job_files и каскадное удаление при удалении задачи
-- Date: 2025-01-09

-- ============================================================
-- 1. Добавляем поле metadata (jsonb) в таблицу job_files
-- Для кропов будет хранить: block_id, page_index, coords_norm, block_type
-- ============================================================
ALTER TABLE public.job_files
ADD COLUMN IF NOT EXISTS metadata jsonb DEFAULT '{}';

COMMENT ON COLUMN public.job_files.metadata IS 'Метаданные файла (для кропов: block_id, page_index, coords_norm, block_type)';

-- Индекс для поиска по metadata (GIN для jsonb)
CREATE INDEX IF NOT EXISTS idx_job_files_metadata ON public.job_files USING gin (metadata);

-- Индекс для быстрого поиска по block_id внутри metadata
CREATE INDEX IF NOT EXISTS idx_job_files_block_id ON public.job_files USING btree ((metadata->>'block_id'))
WHERE file_type = 'crop';

-- ============================================================
-- 2. Каскадное удаление job_files при удалении задачи
-- При DELETE FROM jobs → автоматически удаляются записи из job_files
-- node_files НЕ затрагиваются (они связаны с tree_nodes, не с jobs)
-- ============================================================

-- Удаляем старый constraint (без ON DELETE)
ALTER TABLE public.job_files
DROP CONSTRAINT IF EXISTS job_files_job_id_fkey;

-- Создаём новый constraint с ON DELETE CASCADE
ALTER TABLE public.job_files
ADD CONSTRAINT job_files_job_id_fkey
FOREIGN KEY (job_id) REFERENCES public.jobs(id) ON DELETE CASCADE;

COMMENT ON COLUMN public.job_files.job_id IS 'Ссылка на задачу (каскадное удаление при удалении job)';
