-- Миграция: добавление колонки is_correction_mode в job_settings
-- Дата: 2026-02-02
-- Описание: Поддержка режима корректировки блоков OCR
-- Связанные коммиты: 34c7d67, d27402f

ALTER TABLE public.job_settings
ADD COLUMN IF NOT EXISTS is_correction_mode boolean DEFAULT false;

COMMENT ON COLUMN public.job_settings.is_correction_mode IS 'Режим корректировки: обновить только указанные блоки';
