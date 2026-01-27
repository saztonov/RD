-- Migration: Добавить blocks_index в допустимые типы файлов node_files
-- Date: 2026-01-27
-- Description: Расширяет constraint node_files_file_type_check для поддержки нового типа blocks_index

-- Удаляем старый constraint (если существует)
ALTER TABLE public.node_files
DROP CONSTRAINT IF EXISTS node_files_file_type_check;

-- Создаём новый constraint с blocks_index
ALTER TABLE public.node_files
ADD CONSTRAINT node_files_file_type_check
CHECK (file_type IN (
    'pdf',
    'annotation',
    'result_md',
    'result_zip',
    'crop',
    'image',
    'ocr_html',
    'result_json',
    'crops_folder',
    'qa_manifest',
    'blocks_index'
));

-- Обновляем комментарий колонки
COMMENT ON COLUMN public.node_files.file_type IS 'Тип файла: pdf, annotation, result_md, result_zip, crop, image, ocr_html, result_json, crops_folder, qa_manifest, blocks_index';
