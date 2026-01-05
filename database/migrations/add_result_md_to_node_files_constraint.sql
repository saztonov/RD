-- Миграция: добавление result_md в CHECK constraint для node_files.file_type
-- Дата: 2026-01-04
-- Описание: Разрешить тип файла 'result_md' для хранения document.md файлов

-- Сначала удаляем старый constraint (если есть)
ALTER TABLE public.node_files DROP CONSTRAINT IF EXISTS node_files_file_type_check;

-- Добавляем новый constraint с поддержкой result_md
ALTER TABLE public.node_files ADD CONSTRAINT node_files_file_type_check 
    CHECK (file_type IN (
        'pdf', 
        'annotation', 
        'result_md', 
        'result_zip', 
        'crop', 
        'image', 
        'ocr_html', 
        'result_json', 
        'crops_folder'
    ));

-- Обновляем комментарий к столбцу
COMMENT ON COLUMN public.node_files.file_type IS 'Тип файла: pdf, annotation, result_md, result_zip, crop, image, ocr_html, result_json, crops_folder';
