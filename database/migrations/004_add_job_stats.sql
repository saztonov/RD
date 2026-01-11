-- Migration: Add job statistics fields
-- Description: Add started_at, completed_at, block_stats columns to jobs table
-- Date: 2026-01-12

-- Add started_at column (when job started processing, different from created_at)
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS started_at timestamp with time zone;

-- Add completed_at column (when job finished processing)
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS completed_at timestamp with time zone;

-- Add block_stats column (JSON with statistics)
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS block_stats jsonb DEFAULT '{}'::jsonb;

-- Comments
COMMENT ON COLUMN public.jobs.started_at IS 'Время начала обработки (отличается от created_at - когда задача создана)';
COMMENT ON COLUMN public.jobs.completed_at IS 'Время завершения обработки';
COMMENT ON COLUMN public.jobs.block_stats IS 'Статистика блоков: {total, text, table, image, stamp, processing_time_seconds, avg_time_per_block, estimated_text_time, estimated_table_time, estimated_image_time, estimated_stamp_time}';

-- Index for faster filtering by completion time
CREATE INDEX IF NOT EXISTS idx_jobs_completed_at ON public.jobs(completed_at) WHERE completed_at IS NOT NULL;
