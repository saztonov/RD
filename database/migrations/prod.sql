-- Database Schema SQL Export
-- Generated: 2025-12-20T11:40:30.535173
-- Database: postgres
-- Host: aws-1-eu-north-1.pooler.supabase.com

-- ============================================
-- TABLES
-- ============================================

-- Table: public.job_files
CREATE TABLE IF NOT EXISTS public.job_files (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    job_id uuid NOT NULL,
    file_type text NOT NULL,
    r2_key text NOT NULL,
    file_name text NOT NULL,
    file_size bigint DEFAULT 0,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    CONSTRAINT job_files_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.jobs(id),
    CONSTRAINT job_files_pkey PRIMARY KEY (id)
);

-- Table: public.job_settings
CREATE TABLE IF NOT EXISTS public.job_settings (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    job_id uuid NOT NULL,
    text_model text DEFAULT ''::text,
    table_model text DEFAULT ''::text,
    image_model text DEFAULT ''::text,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    updated_at timestamp with time zone NOT NULL DEFAULT now(),
    CONSTRAINT job_settings_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.jobs(id),
    CONSTRAINT job_settings_job_id_key UNIQUE (job_id),
    CONSTRAINT job_settings_pkey PRIMARY KEY (id)
);

-- Table: public.jobs
CREATE TABLE IF NOT EXISTS public.jobs (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    client_id text NOT NULL,
    document_id text NOT NULL,
    document_name text NOT NULL,
    task_name text NOT NULL DEFAULT ''::text,
    status text NOT NULL DEFAULT 'queued'::text,
    progress real DEFAULT 0,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    updated_at timestamp with time zone NOT NULL DEFAULT now(),
    error_message text,
    engine text DEFAULT ''::text,
    r2_prefix text,
    CONSTRAINT jobs_pkey PRIMARY KEY (id)
);

-- Table: public.section_types
CREATE TABLE IF NOT EXISTS public.section_types (
    id integer NOT NULL DEFAULT nextval('section_types_id_seq'::regclass),
    code text NOT NULL,
    name text NOT NULL,
    sort_order integer DEFAULT 0,
    CONSTRAINT section_types_code_key UNIQUE (code),
    CONSTRAINT section_types_pkey PRIMARY KEY (id)
);

-- Table: public.stage_types
CREATE TABLE IF NOT EXISTS public.stage_types (
    id integer NOT NULL DEFAULT nextval('stage_types_id_seq'::regclass),
    code text NOT NULL,
    name text NOT NULL,
    sort_order integer DEFAULT 0,
    CONSTRAINT stage_types_code_key UNIQUE (code),
    CONSTRAINT stage_types_pkey PRIMARY KEY (id)
);

-- Table: public.tree_documents
CREATE TABLE IF NOT EXISTS public.tree_documents (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    node_id uuid NOT NULL,
    file_name text NOT NULL,
    r2_key text NOT NULL,
    file_size bigint DEFAULT 0,
    mime_type text DEFAULT 'application/pdf'::text,
    version integer DEFAULT 1,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    CONSTRAINT tree_documents_node_id_fkey FOREIGN KEY (node_id) REFERENCES public.tree_nodes(id),
    CONSTRAINT tree_documents_pkey PRIMARY KEY (id)
);

-- Table: public.tree_nodes
CREATE TABLE IF NOT EXISTS public.tree_nodes (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    parent_id uuid,
    client_id text NOT NULL,
    node_type text NOT NULL,
    name text NOT NULL,
    code text,
    version integer DEFAULT 1,
    status text DEFAULT 'active'::text,
    attributes jsonb DEFAULT '{}'::jsonb,
    sort_order integer DEFAULT 0,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    updated_at timestamp with time zone NOT NULL DEFAULT now(),
    CONSTRAINT tree_nodes_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.tree_nodes(id),
    CONSTRAINT tree_nodes_pkey PRIMARY KEY (id)
);


-- ============================================
-- FUNCTIONS
-- ============================================

-- Function: public.update_updated_at_column
CREATE OR REPLACE FUNCTION public.update_updated_at_column()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$function$



-- ============================================
-- TRIGGERS
-- ============================================

-- Trigger: update_job_settings_updated_at on public.job_settings
CREATE TRIGGER update_job_settings_updated_at BEFORE UPDATE ON public.job_settings FOR EACH ROW EXECUTE FUNCTION update_updated_at_column()

-- Trigger: update_jobs_updated_at on public.jobs
CREATE TRIGGER update_jobs_updated_at BEFORE UPDATE ON public.jobs FOR EACH ROW EXECUTE FUNCTION update_updated_at_column()

-- Trigger: update_tree_nodes_updated_at on public.tree_nodes
CREATE TRIGGER update_tree_nodes_updated_at BEFORE UPDATE ON public.tree_nodes FOR EACH ROW EXECUTE FUNCTION update_updated_at_column()


-- ============================================
-- INDEXES
-- ============================================

-- Index on public.job_files
CREATE INDEX idx_job_files_job_id ON public.job_files USING btree (job_id);

-- Index on public.job_files
CREATE INDEX idx_job_files_type ON public.job_files USING btree (file_type);

-- Index on public.job_settings
CREATE INDEX idx_job_settings_job_id ON public.job_settings USING btree (job_id);

-- Index on public.job_settings
CREATE UNIQUE INDEX job_settings_job_id_key ON public.job_settings USING btree (job_id);

-- Index on public.jobs
CREATE INDEX idx_jobs_client_id ON public.jobs USING btree (client_id);

-- Index on public.jobs
CREATE INDEX idx_jobs_created_at ON public.jobs USING btree (created_at DESC);

-- Index on public.jobs
CREATE INDEX idx_jobs_document_id ON public.jobs USING btree (document_id);

-- Index on public.jobs
CREATE INDEX idx_jobs_status ON public.jobs USING btree (status);

-- Index on public.section_types
CREATE UNIQUE INDEX section_types_code_key ON public.section_types USING btree (code);

-- Index on public.stage_types
CREATE UNIQUE INDEX stage_types_code_key ON public.stage_types USING btree (code);

-- Index on public.tree_documents
CREATE INDEX idx_tree_documents_node_id ON public.tree_documents USING btree (node_id);

-- Index on public.tree_nodes
CREATE INDEX idx_tree_nodes_client_id ON public.tree_nodes USING btree (client_id);

-- Index on public.tree_nodes
CREATE INDEX idx_tree_nodes_parent_id ON public.tree_nodes USING btree (parent_id);

-- Index on public.tree_nodes
CREATE INDEX idx_tree_nodes_sort ON public.tree_nodes USING btree (parent_id, sort_order);

-- Index on public.tree_nodes
CREATE INDEX idx_tree_nodes_type ON public.tree_nodes USING btree (node_type);


-- ============================================
-- ROLES AND PRIVILEGES
-- ============================================

-- Role: anon
CREATE ROLE anon;

-- Role: authenticated
CREATE ROLE authenticated;

-- Role: authenticator
CREATE ROLE authenticator WITH LOGIN NOINHERIT;

-- Role: dashboard_user
CREATE ROLE dashboard_user WITH CREATEDB CREATEROLE REPLICATION;

-- Role: postgres
CREATE ROLE postgres WITH CREATEDB CREATEROLE LOGIN REPLICATION BYPASSRLS;

-- Role: service_role
CREATE ROLE service_role WITH BYPASSRLS;

-- Role: supabase_admin
CREATE ROLE supabase_admin WITH SUPERUSER CREATEDB CREATEROLE LOGIN REPLICATION BYPASSRLS;

-- Role: supabase_auth_admin
CREATE ROLE supabase_auth_admin WITH CREATEROLE LOGIN NOINHERIT;

-- Role: supabase_etl_admin
CREATE ROLE supabase_etl_admin WITH LOGIN REPLICATION;

-- Role: supabase_read_only_user
CREATE ROLE supabase_read_only_user WITH LOGIN BYPASSRLS;

-- Role: supabase_realtime_admin
CREATE ROLE supabase_realtime_admin WITH NOINHERIT;

-- Role: supabase_replication_admin
CREATE ROLE supabase_replication_admin WITH LOGIN REPLICATION;

-- Role: supabase_storage_admin
CREATE ROLE supabase_storage_admin WITH CREATEROLE LOGIN NOINHERIT;
