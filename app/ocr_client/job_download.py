"""Миксин скачивания результатов OCR задач."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

import httpx

logger = logging.getLogger(__name__)


class JobDownloadMixin:
    """Скачивание результатов и блоков задач."""

    def download_result(self, job_id: str, target_zip_path: str) -> str:
        """Скачать результат задачи."""
        resp = self._request_with_retry("get", f"/jobs/{job_id}/result", timeout=300.0)

        Path(target_zip_path).parent.mkdir(parents=True, exist_ok=True)
        with open(target_zip_path, "wb") as f:
            f.write(resp.content)

        return target_zip_path

    def get_job_blocks(self, job_id: str) -> Optional[List[dict]]:
        """Получить блоки задачи с сервера."""
        try:
            details = self.get_job_details(job_id)
            r2_base_url = details.get("r2_base_url")

            if not r2_base_url:
                return None

            # Получаем блоки из R2
            blocks_url = f"{r2_base_url}/annotation.json"
            resp = httpx.get(blocks_url, timeout=30.0)
            if resp.status_code == 200:
                return resp.json()

            # Fallback на blocks.json
            blocks_url = f"{r2_base_url}/blocks.json"
            resp = httpx.get(blocks_url, timeout=30.0)
            if resp.status_code == 200:
                return resp.json()

        except Exception as e:
            logger.warning(f"Ошибка получения блоков: {e}")

        return None
