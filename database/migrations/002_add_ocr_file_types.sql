-- Migration: Add ocr_html and result_json file types to node_files
-- Date: 2026-01-01

-- Update the file_type check constraint if it exists
-- First, drop the old constraint if exists (ignore error if not exists)
DO $$
BEGIN
    ALTER TABLE public.node_files DROP CONSTRAINT IF EXISTS node_files_file_type_check;
EXCEPTION
    WHEN undefined_object THEN NULL;
END $$;

-- Add updated constraint with new file types
ALTER TABLE public.node_files
ADD CONSTRAINT node_files_file_type_check 
CHECK (file_type IN ('pdf', 'annotation', 'result_md', 'result_zip', 'crop', 'image', 'ocr_html', 'result_json'));

-- Update comment to reflect new file types
COMMENT ON COLUMN public.node_files.file_type IS 'Тип файла: pdf, annotation, result_md, result_zip, crop, image, ocr_html, result_json';
