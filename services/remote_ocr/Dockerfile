FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Зависимости для PyMuPDF
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1-mesa-glx \
    && rm -rf /var/lib/apt/lists/*

# Устанавливаем зависимости сервера
COPY services/remote_ocr/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

EXPOSE 8000

# CMD задаётся в docker-compose для dev (с --reload)
CMD ["uvicorn", "services.remote_ocr.server.main:app", "--host", "0.0.0.0", "--port", "8000"]
