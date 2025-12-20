-- Таблица jobs - основная информация о задачах
CREATE TABLE IF NOT EXISTS jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    document_name TEXT NOT NULL,
    task_name TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('draft', 'queued', 'processing', 'done', 'error', 'paused')),
    progress REAL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    error_message TEXT,
    engine TEXT DEFAULT '',
    r2_prefix TEXT NOT NULL
);

-- Таблица job_files - ссылки на файлы в R2
CREATE TABLE IF NOT EXISTS job_files (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    file_type TEXT NOT NULL CHECK (file_type IN ('pdf', 'blocks', 'annotation', 'result_md', 'result_zip', 'crop')),
    r2_key TEXT NOT NULL,
    file_name TEXT NOT NULL,
    file_size BIGINT DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Таблица job_settings - настройки задачи
CREATE TABLE IF NOT EXISTS job_settings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE UNIQUE,
    text_model TEXT DEFAULT '',
    table_model TEXT DEFAULT '',
    image_model TEXT DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Индексы
CREATE INDEX IF NOT EXISTS idx_jobs_client_id ON jobs(client_id);
CREATE INDEX IF NOT EXISTS idx_jobs_document_id ON jobs(document_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_job_files_job_id ON job_files(job_id);
CREATE INDEX IF NOT EXISTS idx_job_files_type ON job_files(file_type);
CREATE INDEX IF NOT EXISTS idx_job_settings_job_id ON job_settings(job_id);

-- Триггер для автообновления updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

DROP TRIGGER IF EXISTS update_jobs_updated_at ON jobs;
CREATE TRIGGER update_jobs_updated_at
    BEFORE UPDATE ON jobs
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_job_settings_updated_at ON job_settings;
CREATE TRIGGER update_job_settings_updated_at
    BEFORE UPDATE ON job_settings
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Миграция: удаление старых колонок (выполнить после переноса данных)
-- ALTER TABLE jobs DROP COLUMN IF EXISTS job_dir;
-- ALTER TABLE jobs DROP COLUMN IF EXISTS result_path;
