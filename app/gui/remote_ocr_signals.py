"""Сигналы для Remote OCR панели"""

from PySide6.QtCore import Signal, QObject


class WorkerSignals(QObject):
    """Сигналы для фоновых задач"""
    jobs_loaded = Signal(list)
    jobs_error = Signal(str)
    job_created = Signal(object)
    job_create_error = Signal(str, str)  # error_type, message
    # Сигналы для скачивания
    download_started = Signal(str, int)  # job_id, total_files
    download_progress = Signal(str, int, str)  # job_id, current_file_num, filename
    download_finished = Signal(str, str)  # job_id, extract_dir
    download_error = Signal(str, str)  # job_id, error_message
    # Сигналы для черновика
    draft_created = Signal(object)  # job_info
    draft_create_error = Signal(str, str)  # error_type, message
    # Сигналы для повторного распознавания
    rerun_started = Signal(str)  # old_job_id
    rerun_created = Signal(str, object)  # old_job_id, new_job_info
    rerun_error = Signal(str, str)  # old_job_id, error_message

