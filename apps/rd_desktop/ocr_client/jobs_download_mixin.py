"""Mixin для скачивания результатов OCR задач"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

import httpx

logger = logging.getLogger(__name__)


class JobsDownloadMixin:
    """Методы скачивания результатов и получения деталей задач"""

    def get_job_details(self, job_id: str) -> dict:
        """Получить детальную информацию о задаче"""
        resp = self._request_with_retry("get", f"/jobs/{job_id}/details")
        return resp.json()

    def get_job_progress(self, job_id: str) -> dict:
        """
        Получить детальный прогресс задачи с информацией о фазах.

        Возвращает:
            {
                "job_id": str,
                "status": str,
                "progress": float,
                "status_message": str,
                "phase_data": {
                    "current_phase": str,
                    "pass1": {...},
                    "pass2_strips": {...},
                    "pass2_images": {...},
                    "blocks_summary": {...},
                },
                "blocks": [...],
                "crops": [...],
            }
        """
        resp = self._request_with_retry("get", f"/jobs/{job_id}/progress")
        return resp.json()

    def download_result(self, job_id: str, target_zip_path: str) -> str:
        """
        Скачать результат задачи

        Args:
            job_id: ID задачи
            target_zip_path: путь для сохранения zip

        Returns:
            Путь к скачанному файлу
        """
        resp = self._request_with_retry("get", f"/jobs/{job_id}/result", timeout=300.0)

        Path(target_zip_path).parent.mkdir(parents=True, exist_ok=True)
        with open(target_zip_path, "wb") as f:
            f.write(resp.content)

        return target_zip_path

    def get_job_blocks(self, job_id: str) -> Optional[List[dict]]:
        """
        Получить блоки задачи с сервера

        Args:
            job_id: ID задачи

        Returns:
            Список блоков или None
        """
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
