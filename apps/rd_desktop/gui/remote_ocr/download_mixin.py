"""Методы скачивания для Remote OCR панели"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class DownloadMixin:
    """Миксин для скачивания результатов"""

    def _auto_download_result(self, job_id: str):
        """Запустить скачивание результата из R2 в папку текущего документа"""
        # Защита от повторного запуска (polling + realtime гонка)
        if job_id in self._downloaded_jobs:
            logger.debug(f"Скачивание {job_id[:8]} уже запущено, пропуск")
            return
        self._downloaded_jobs.add(job_id)
        logger.info(f"Запуск скачивания результата: {job_id[:8]}")

        client = self._get_client()
        if client is None:
            self._downloaded_jobs.discard(job_id)
            return

        try:
            job_details = client.get_job_details(job_id)
            r2_prefix = job_details.get("r2_prefix")

            if not r2_prefix:
                logger.warning(f"Задача {job_id} не имеет r2_prefix")
                self._downloaded_jobs.discard(job_id)
                return

            # Получаем путь к текущему PDF из main_window
            pdf_path = getattr(self.main_window, "_current_pdf_path", None)
            if not pdf_path:
                logger.warning(
                    f"Нет открытого документа для сохранения результатов job {job_id}"
                )
                self._downloaded_jobs.discard(job_id)
                return

            pdf_path = Path(pdf_path)
            extract_dir = pdf_path.parent

            # Всегда скачиваем новые результаты (перезапуск OCR очищает старые)
            self._executor.submit(
                self._download_result_bg, job_id, r2_prefix, str(extract_dir)
            )

        except Exception as e:
            logger.error(f"Ошибка подготовки скачивания {job_id}: {e}")
            self._downloaded_jobs.discard(job_id)

    def _download_result_bg(self, job_id: str, r2_prefix: str, extract_dir: str):
        """Фоновое скачивание результата в папку текущего документа."""
        try:
            from rd_adapters.storage.caching import get_metadata_cache
            from rd_adapters.storage import R2SyncStorage as R2Storage

            r2 = R2Storage()

            extract_path = Path(extract_dir)
            extract_path.mkdir(parents=True, exist_ok=True)

            # Получаем информацию о задаче
            client = self._get_client()
            job_details = client.get_job_details(job_id) if client else {}

            # Получаем имя PDF из main_window для локальных имен файлов
            pdf_path = getattr(self.main_window, "_current_pdf_path", None)
            doc_name = job_details.get("document_name", "result.pdf")
            pdf_stem = Path(pdf_path).stem if pdf_path else Path(doc_name).stem

            # Используем ocr_result_prefix (изолированная папка задачи) с простыми именами
            # Формат: tree_docs/{node_id}/ocr_runs/{job_id}/result.json
            ocr_prefix = job_details.get("ocr_result_prefix") or r2_prefix

            # Инвалидируем кэш метаданных для префикса перед скачиванием
            get_metadata_cache().invalidate_prefix(ocr_prefix + "/")
            logger.debug(f"Invalidated metadata cache for prefix: {ocr_prefix}/")

            # OCR результаты хранятся с простыми именами в изолированной папке задачи
            # Локально сохраняем с префиксом pdf_stem для удобства пользователя
            files_to_download = [
                ("annotation.json", f"{pdf_stem}_annotation.json"),
                ("ocr.html", f"{pdf_stem}_ocr.html"),
                ("result.json", f"{pdf_stem}_result.json"),
                ("document.md", f"{pdf_stem}_document.md"),
            ]

            self._signals.download_started.emit(job_id, len(files_to_download))

            downloaded_count = 0
            for idx, (remote_name, local_name) in enumerate(files_to_download, 1):
                self._signals.download_progress.emit(job_id, idx, local_name)
                remote_key = f"{ocr_prefix}/{remote_name}"
                local_path = extract_path / local_name
                try:
                    # Проверяем без кэша (свежие данные с сервера)
                    if r2.exists(remote_key, use_cache=False):
                        # Скачиваем без дискового кэша (сервер мог обновить файл)
                        r2.download_file(remote_key, str(local_path), use_cache=False)
                        logger.info(f"Скачан: {local_path}")
                        downloaded_count += 1
                    else:
                        logger.warning(f"Файл не найден: {remote_key}")
                except Exception as e:
                    logger.warning(f"Не удалось скачать {remote_key}: {e}")

            logger.info(f"✅ Результат скачан: {extract_dir} ({downloaded_count} файлов)")
            self._signals.download_finished.emit(job_id, extract_dir)

        except Exception as e:
            logger.error(f"Ошибка скачивания {job_id}: {e}")
            self._signals.download_error.emit(job_id, str(e))
