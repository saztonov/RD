#!/bin/bash
# Cron скрипт для ежедневного обновления статусов PDF
# Добавить в crontab: 0 2 * * * /path/to/cron_update_statuses.sh

# Переход в директорию проекта
cd "$(dirname "$0")/../../.."

# Загрузка переменных окружения
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

# Запуск скрипта обновления
python services/remote_ocr/server/update_pdf_statuses.py >> logs/pdf_status_update.log 2>&1
