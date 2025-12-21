"""Методы скачивания для Remote OCR панели"""

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class DownloadMixin:
    """Миксин для скачивания результатов"""
    
    def _auto_download_result(self, job_id: str):
        """Запустить скачивание результата из R2 в папку текущего документа"""
        client = self._get_client()
        if client is None:
            return
        
        try:
            job_details = client.get_job_details(job_id)
            r2_prefix = job_details.get("r2_prefix")
            
            if not r2_prefix:
                logger.warning(f"Задача {job_id} не имеет r2_prefix")
                return
            
            # Получаем путь к текущему PDF из main_window
            pdf_path = getattr(self.main_window, '_current_pdf_path', None)
            if not pdf_path:
                logger.warning(f"Нет открытого документа для сохранения результатов job {job_id}")
                return
            
            pdf_path = Path(pdf_path)
            extract_dir = pdf_path.parent
            
            # Проверяем, есть ли уже результат (annotation с OCR текстом)
            ann_path = extract_dir / f"{pdf_path.stem}_annotation.json"
            result_exists = ann_path.exists()
            
            # Проверяем содержит ли annotation ocr_text (признак OCR)
            if result_exists:
                try:
                    import json
                    with open(ann_path, 'r', encoding='utf-8') as f:
                        ann_data = json.load(f)
                    # Проверяем наличие ocr_text в блоках
                    has_ocr = False
                    for page in ann_data.get('pages', []):
                        for block in page.get('blocks', []):
                            if block.get('ocr_text'):
                                has_ocr = True
                                break
                        if has_ocr:
                            break
                    result_exists = has_ocr
                except Exception:
                    result_exists = False
            
            if not result_exists:
                self._executor.submit(self._download_result_bg, job_id, r2_prefix, str(extract_dir))
            else:
                logger.debug(f"Результат уже скачан: {extract_dir}")
                
        except Exception as e:
            logger.error(f"Ошибка подготовки скачивания {job_id}: {e}")

    def _download_result_bg(self, job_id: str, r2_prefix: str, extract_dir: str):
        """Фоновое скачивание результата в папку текущего документа.
        
        Сохраняем: {pdf_stem}_annotation.json, {pdf_stem}.md, crops/
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
            
            # Получаем имя PDF из main_window для правильного именования файлов
            pdf_path = getattr(self.main_window, '_current_pdf_path', None)
            if pdf_path:
                pdf_stem = Path(pdf_path).stem
            else:
                pdf_stem = doc_stem
            
            # Используем result_prefix из API (папка где лежит PDF)
            actual_prefix = job_details.get("result_prefix") or r2_prefix
            
            crops_prefix = f"{actual_prefix}/crops/"
            crop_files = r2.list_by_prefix(crops_prefix)
            
            # Файлы для скачивания: {doc_stem}_annotation.json, {doc_stem}.md
            files_to_download = [
                (f"{doc_stem}_annotation.json", f"{pdf_stem}_annotation.json"),
                (f"{doc_stem}.md", f"{pdf_stem}.md"),
            ]
            # Обратная совместимость: старые форматы файлов
            if not r2.exists(f"{actual_prefix}/{doc_stem}_annotation.json"):
                files_to_download[0] = ("annotation.json", f"{pdf_stem}_annotation.json")
            if not r2.exists(f"{actual_prefix}/{doc_stem}.md"):
                files_to_download[1] = ("result.md", f"{pdf_stem}.md")
            
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
            
            logger.info(f"✅ Результат скачан в папку документа: {extract_dir}")
            self._signals.download_finished.emit(job_id, extract_dir)
            
        except Exception as e:
            logger.error(f"Ошибка скачивания результата {job_id}: {e}")
            self._signals.download_error.emit(job_id, str(e))

