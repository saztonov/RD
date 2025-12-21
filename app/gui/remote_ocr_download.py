"""Методы скачивания для Remote OCR панели"""

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class DownloadMixin:
    """Миксин для скачивания результатов"""
    
    def _auto_download_result(self, job_id: str, open_after: bool = False):
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
                if open_after:
                    self._pending_open_in_editor = job_id
                self._executor.submit(self._download_result_bg, job_id, r2_prefix, str(extract_dir))
            else:
                logger.debug(f"Результат уже скачан: {extract_dir}")
                if open_after:
                    self._open_job_in_editor_internal(job_id)
                
        except Exception as e:
            logger.error(f"Ошибка подготовки скачивания {job_id}: {e}")

    def _download_result_bg(self, job_id: str, r2_prefix: str, extract_dir: str):
        """Фоновое скачивание результата с прогрессом"""
        try:
            from rd_core.r2_storage import R2Storage
            r2 = R2Storage()
            
            extract_path = Path(extract_dir)
            extract_path.mkdir(parents=True, exist_ok=True)
            
            main_files = ["annotation.json", "result.md", "document.pdf"]
            crops_prefix = f"{r2_prefix}/crops/"
            crop_files = r2.list_by_prefix(crops_prefix)
            
            total_files = len(main_files) + len(crop_files)
            self._signals.download_started.emit(job_id, total_files)
            
            current = 0
            
            for filename in main_files:
                current += 1
                self._signals.download_progress.emit(job_id, current, filename)
                remote_key = f"{r2_prefix}/{filename}"
                local_path = extract_path / filename
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

