FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Dependencies for PyMuPDF + curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install server dependencies
COPY apps/remote_ocr_server/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Copy code (new structure)
COPY packages /app/packages
COPY apps /app/apps

EXPOSE 8000

# CMD is set in docker-compose (web or worker)
CMD ["uvicorn", "apps.remote_ocr_server.main:app", "--host", "0.0.0.0", "--port", "8000"]
