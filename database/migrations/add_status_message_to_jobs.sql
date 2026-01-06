-- Migration: Add status_message column to jobs table
-- Description: Добавляет колонку status_message для отображения детальной информации
--              о текущей операции в Remote OCR Jobs панели
-- Date: 2026-01-06

-- Добавляем колонку status_message в таблицу jobs
ALTER TABLE public.jobs
ADD COLUMN IF NOT EXISTS status_message text;

-- Комментарий к колонке
COMMENT ON COLUMN public.jobs.status_message IS 'Детальное сообщение о текущей операции (отображается в колонке "Детали")';
