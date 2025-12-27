"""Загрузка результатов OCR в R2"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from .storage import Job, add_job_file, delete_job_files, get_node_pdf_r2_key
from .task_helpers import get_r2_storage

logger = logging.getLogger(__name__)


def upload_results_to_r2(job: Job, work_dir: Path, r2_prefix: str = None) -> str:
    """Загрузить результаты в R2 и записать в БД.
    
    Если есть node_id - загружаем в папку где лежит PDF (parent dir от pdf_r2_key)
    Иначе - в ocr_jobs/{job_id}/ (обратная совместимость)
    """
    r2 = get_r2_storage()
    
    # Определяем prefix для загрузки (если не передан)
    if r2_prefix is None:
        if job.node_id:
            pdf_r2_key = get_node_pdf_r2_key(job.node_id)
            if pdf_r2_key:
                from pathlib import PurePosixPath
                r2_prefix = str(PurePosixPath(pdf_r2_key).parent)
            else:
                r2_prefix = f"tree_docs/{job.node_id}"
        else:
            r2_prefix = job.r2_prefix
    
    doc_stem = Path(job.document_name).stem
    
    # result.json -> {doc_stem}_preliminary.json (OCR результаты)
    result_json_path = work_dir / "result.json"
    if result_json_path.exists():
        json_filename = f"{doc_stem}_preliminary.json"
        r2_key = f"{r2_prefix}/{json_filename}"
        r2.upload_file(str(result_json_path), r2_key)
        add_job_file(job.id, "preliminary_json", r2_key, json_filename, result_json_path.stat().st_size)
    
    # annotation.json -> {doc_stem}_annotation.json (перезаписываем существующий)
    annotation_path = work_dir / "annotation.json"
    if annotation_path.exists():
        # Удаляем старый blocks файл чтобы не дублировать annotation
        delete_job_files(job.id, ["blocks"])
        annotation_filename = f"{doc_stem}_annotation.json"
        r2_key = f"{r2_prefix}/{annotation_filename}"
        r2.upload_file(str(annotation_path), r2_key)
        add_job_file(job.id, "annotation", r2_key, annotation_filename, annotation_path.stat().st_size)
    
    # grouped_result.json -> {doc_stem}_result.json
    grouped_result_path = work_dir / "grouped_result.json"
    if grouped_result_path.exists():
        result_filename = f"{doc_stem}_result.json"
        r2_key = f"{r2_prefix}/{result_filename}"
        r2.upload_file(str(grouped_result_path), r2_key)
        add_job_file(job.id, "grouped_result", r2_key, result_filename, grouped_result_path.stat().st_size)
    
    # crops/ (проверяем оба варианта: crops и crops_final для двухпроходного алгоритма)
    for crops_subdir in ["crops", "crops_final"]:
        crops_path = work_dir / crops_subdir
        if crops_path.exists():
            for crop_file in crops_path.iterdir():
                if crop_file.is_file() and crop_file.suffix.lower() == ".pdf":
                    r2_key = f"{r2_prefix}/crops/{crop_file.name}"
                    r2.upload_file(str(crop_file), r2_key)
                    add_job_file(job.id, "crop", r2_key, crop_file.name, crop_file.stat().st_size)
                    logger.info(f"Загружен кроп в R2: {r2_key}")
    
    return r2_prefix


def copy_crops_to_final(work_dir: Path, blocks) -> None:
    """Копировать PDF кропы из crops/images в crops_final для загрузки в R2"""
    crops_dir = work_dir / "crops"
    images_subdir = crops_dir / "images"
    crops_final = work_dir / "crops_final"
    
    if not images_subdir.exists():
        return
    
    crops_final.mkdir(exist_ok=True)
    blocks_by_id = {b.id: b for b in blocks}
    
    for pdf_file in images_subdir.glob("*.pdf"):
        try:
            target = crops_final / pdf_file.name
            shutil.copy2(pdf_file, target)
            
            block_id = pdf_file.stem
            if block_id in blocks_by_id:
                blocks_by_id[block_id].image_file = str(target)
            
            logger.debug(f"PDF кроп скопирован: {pdf_file.name}")
        except Exception as e:
            logger.warning(f"Ошибка копирования PDF кропа {pdf_file}: {e}")

