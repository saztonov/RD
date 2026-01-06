-- ============================================
-- Migration: Remove client_id from all tables
-- Date: 2026-01-07
-- Description: Удаление поля client_id из проекта
-- ============================================

-- ============================================
-- STEP 1: DROP INDEXES that use client_id
-- ============================================

-- tree_nodes indexes
DROP INDEX IF EXISTS idx_tree_nodes_client_id;
DROP INDEX IF EXISTS idx_tree_nodes_client_parent;
DROP INDEX IF EXISTS idx_tree_nodes_roots;

-- jobs indexes
DROP INDEX IF EXISTS idx_jobs_client_id;

-- user_prompts indexes
DROP INDEX IF EXISTS idx_user_prompts_client_id;

-- ============================================
-- STEP 2: DROP COLUMNS client_id
-- ============================================

-- tree_nodes
ALTER TABLE tree_nodes DROP COLUMN IF EXISTS client_id;

-- jobs
ALTER TABLE jobs DROP COLUMN IF EXISTS client_id;

-- user_prompts
ALTER TABLE user_prompts DROP COLUMN IF EXISTS client_id;

-- ============================================
-- STEP 3: RECREATE INDEXES without client_id
-- ============================================

-- Index for root nodes (without client_id)
CREATE INDEX IF NOT EXISTS idx_tree_nodes_roots
ON tree_nodes (sort_order)
WHERE parent_id IS NULL;

-- ============================================
-- STEP 4: REMOVE DUPLICATE INDEXES
-- ============================================

-- idx_node_files_unique_r2 is a duplicate of node_files_node_id_r2_key_unique
DROP INDEX IF EXISTS idx_node_files_unique_r2;

-- ============================================
-- STEP 5: ADD OPTIMIZATION INDEXES
-- ============================================

-- For incremental polling of jobs
CREATE INDEX IF NOT EXISTS idx_jobs_updated_at
ON jobs (updated_at DESC);

-- For filtering active jobs
CREATE INDEX IF NOT EXISTS idx_jobs_active_status
ON jobs (status, updated_at DESC)
WHERE status IN ('queued', 'processing');

-- ============================================
-- VERIFICATION (run to check results)
-- ============================================
-- SELECT
--     c.table_name,
--     c.column_name
-- FROM information_schema.columns c
-- WHERE c.column_name = 'client_id'
--   AND c.table_schema = 'public';
--
-- SELECT indexname, indexdef
-- FROM pg_indexes
-- WHERE tablename IN ('tree_nodes', 'jobs', 'user_prompts');
