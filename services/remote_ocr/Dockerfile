FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Зависимости для PyMuPDF
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

# Устанавливаем зависимости сервера
COPY services/remote_ocr/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Копируем код
COPY rd_core /app/rd_core
COPY services /app/services

# Непривилегированный пользователь (убирает Celery SecurityWarning о запуске под root).
# /data — рабочая директория OCR (named volume ocr_data), /tmp — для job-кропов.
RUN groupadd -r app && useradd -r -g app -u 10001 app \
    && mkdir -p /data \
    && chown -R app:app /data /app
USER app

EXPOSE 8000

# CMD задаётся в docker-compose (web или worker)
CMD ["uvicorn", "services.remote_ocr.server.main:app", "--host", "0.0.0.0", "--port", "8000"]
