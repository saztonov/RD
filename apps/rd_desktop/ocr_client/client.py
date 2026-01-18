"""HTTP-клиент для удалённого OCR сервера

Модуль разбит на mixins по функциональности:
- base.py: HTTP инфраструктура и базовый класс
- jobs_create_mixin.py: создание задач (create_job, create_job_v2)
- jobs_crud_mixin.py: CRUD операции (list, get, delete, restart, cancel)
- jobs_download_mixin.py: скачивание результатов и деталей
"""
from __future__ import annotations

from dataclasses import dataclass

from apps.rd_desktop.ocr_client.base import RemoteOCRClientBase
from apps.rd_desktop.ocr_client.jobs_create_mixin import JobsCreateMixin
from apps.rd_desktop.ocr_client.jobs_crud_mixin import JobsCrudMixin
from apps.rd_desktop.ocr_client.jobs_download_mixin import JobsDownloadMixin


@dataclass
class RemoteOCRClient(
    RemoteOCRClientBase,
    JobsCreateMixin,
    JobsCrudMixin,
    JobsDownloadMixin,
):
    """
    Клиент для удалённого OCR сервера.

    Составлен из mixins:
    - RemoteOCRClientBase: HTTP инфраструктура
    - JobsCreateMixin: создание задач
    - JobsCrudMixin: CRUD операции
    - JobsDownloadMixin: скачивание результатов
    """
    pass
