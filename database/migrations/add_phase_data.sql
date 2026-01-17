-- Migration: Add phase_data column to jobs table
-- Description: Stores detailed phase information during OCR processing
-- Date: 2026-01-17

-- Add phase_data column (jsonb for storing structured phase info)
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS phase_data jsonb;

COMMENT ON COLUMN public.jobs.phase_data IS 'Детальная информация о фазах обработки OCR (PASS1, PASS2 strips/images)';
