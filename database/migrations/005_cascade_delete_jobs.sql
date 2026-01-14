-- Миграция: добавить CASCADE DELETE для jobs и node_files при удалении tree_nodes
-- Это обеспечивает автоматическое удаление связанных записей при удалении узла дерева

-- Удалить существующий foreign key для jobs
ALTER TABLE public.jobs DROP CONSTRAINT IF EXISTS jobs_node_id_fkey;

-- Создать новый с ON DELETE CASCADE
ALTER TABLE public.jobs
ADD CONSTRAINT jobs_node_id_fkey
FOREIGN KEY (node_id) REFERENCES public.tree_nodes(id)
ON DELETE CASCADE;

-- Удалить существующий foreign key для node_files
ALTER TABLE public.node_files DROP CONSTRAINT IF EXISTS node_files_node_id_fkey;

-- Создать новый с ON DELETE CASCADE
ALTER TABLE public.node_files
ADD CONSTRAINT node_files_node_id_fkey
FOREIGN KEY (node_id) REFERENCES public.tree_nodes(id)
ON DELETE CASCADE;

-- Примечание: CASCADE DELETE удаляет только записи в БД, не файлы в R2
-- Файлы R2 удаляются программно через _delete_document_files()
