-- Migration: Add qa_manifest to node_files.file_type check constraint
-- Date: 2026-01-11
-- Description: Adds qa_manifest to the list of valid file types for node_files

-- Drop existing constraint
ALTER TABLE node_files DROP CONSTRAINT IF EXISTS node_files_file_type_check;

-- Add updated constraint with qa_manifest
ALTER TABLE node_files ADD CONSTRAINT node_files_file_type_check
  CHECK (file_type IN (
    'pdf',
    'annotation',
    'result_json',
    'result_md',
    'ocr_html',
    'qa_manifest',
    'crop',
    'crops_folder'
  ));
