-- =====================================================
-- Миграция: удаление OCR server settings из app_settings
-- =====================================================
-- Дата: 2026-02-08
-- Описание: Настройки OCR сервера перенесены из Supabase в YAML конфиг
--           (services/remote_ocr/server/config.yaml).
--           Удаляем запись ocr_server_settings из app_settings.

-- 1. Удалить запись с настройками OCR сервера
DELETE FROM public.app_settings
WHERE key = 'ocr_server_settings';

-- 2. Проверка: если таблица app_settings больше не нужна,
--    раскомментируйте следующие строки:

-- DROP TRIGGER IF EXISTS app_settings_updated_at ON public.app_settings;
-- DROP TABLE IF EXISTS public.app_settings;
-- DROP FUNCTION IF EXISTS public.update_app_settings_timestamp();

-- Примечание: функции get_app_setting / set_app_setting работают с qa_app_settings,
-- а не с app_settings, поэтому их НЕ трогаем.
