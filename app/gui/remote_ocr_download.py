"""Методы скачивания для Remote OCR панели"""

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class DownloadMixin:
    """Миксин для скачивания результатов"""
    
    def _auto_download_result(self, job_id: str):
        """Запустить скачивание результата из R2 в фоне с прогрессом"""
        client = self._get_client()
        if client is None:
            return
        
        try:
            job_details = client.get_job_details(job_id)
            r2_prefix = job_details.get("r2_prefix")
            
            if not r2_prefix:
                logger.warning(f"Задача {job_id} не имеет r2_prefix")
                return
            
            if job_id in self._job_output_dirs:
                extract_dir = Path(self._job_output_dirs[job_id])
            else:
                from app.gui.folder_settings_dialog import get_projects_dir
                download_dir = get_projects_dir()
                if download_dir and Path(download_dir).exists():
                    extract_dir = Path(download_dir) / f"result_{job_id[:8]}"
                else:
                    import tempfile
                    tmp_base = Path(tempfile.gettempdir()) / "rd_ocr_results"
                    tmp_base.mkdir(exist_ok=True)
                    extract_dir = tmp_base / f"result_{job_id[:8]}"
            
            if job_id not in self._job_output_dirs:
                self._job_output_dirs[job_id] = str(extract_dir)
                self._save_job_mappings()
            
            result_exists = extract_dir.exists() and (extract_dir / "annotation.json").exists()
            
            if not result_exists:
                self._executor.submit(self._download_result_bg, job_id, r2_prefix, str(extract_dir))
            else:
                logger.debug(f"Результат уже скачан: {extract_dir}")
                
        except Exception as e:
            logger.error(f"Ошибка подготовки скачивания {job_id}: {e}")

    def _download_result_bg(self, job_id: str, r2_prefix: str, extract_dir: str):
        """Фоновое скачивание результата с прогрессом.
        
        Скачиваем только: annotation.json, result.md (по имени документа), crops/
        НЕ скачиваем: document.pdf, result.zip
        """
        try:
            from rd_core.r2_storage import R2Storage
            r2 = R2Storage()
            
            extract_path = Path(extract_dir)
            extract_path.mkdir(parents=True, exist_ok=True)
            
            # Получаем информацию о задаче для имени документа
            client = self._get_client()
            job_details = client.get_job_details(job_id) if client else {}
            doc_name = job_details.get("document_name", "result.pdf")
            doc_stem = Path(doc_name).stem
            node_id = job_details.get("node_id")
            
            # Определяем prefix: tree_docs/{node_id} или ocr_jobs/{job_id}
            if node_id:
                actual_prefix = f"tree_docs/{node_id}"
            else:
                actual_prefix = r2_prefix
            
            crops_prefix = f"{actual_prefix}/crops/"
            crop_files = r2.list_by_prefix(crops_prefix)
            
            # Файлы для скачивания: annotation.json + {doc_stem}.md
            files_to_download = [
                ("annotation.json", "annotation.json"),
                (f"{doc_stem}.md", f"{doc_stem}.md"),
            ]
            # Обратная совместимость: если нет {doc_stem}.md, пробуем result.md
            if not r2.exists(f"{actual_prefix}/{doc_stem}.md"):
                files_to_download[1] = ("result.md", f"{doc_stem}.md")
            
            total_files = len(files_to_download) + len(crop_files)
            self._signals.download_started.emit(job_id, total_files)
            
            current = 0
            
            for remote_name, local_name in files_to_download:
                current += 1
                self._signals.download_progress.emit(job_id, current, local_name)
                remote_key = f"{actual_prefix}/{remote_name}"
                local_path = extract_path / local_name
                r2.download_file(remote_key, str(local_path))
            
            if crop_files:
                crops_dir = extract_path / "crops"
                crops_dir.mkdir(exist_ok=True)
                
                for remote_key in crop_files:
                    current += 1
                    filename = remote_key.split("/")[-1]
                    if filename:
                        self._signals.download_progress.emit(job_id, current, f"crops/{filename}")
                        local_path = crops_dir / filename
                        r2.download_file(remote_key, str(local_path))
            
            logger.info(f"✅ Результат скачан из R2: {extract_dir}")
            self._signals.download_finished.emit(job_id, extract_dir)
            
        except Exception as e:
            logger.error(f"Ошибка скачивания результата {job_id}: {e}")
            self._signals.download_error.emit(job_id, str(e))

