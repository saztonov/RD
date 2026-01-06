"""Сигналы для Remote OCR панели"""

from PySide6.QtCore import QObject, Signal


class WorkerSignals(QObject):
    """Сигналы для фоновых задач"""

    jobs_loaded = Signal(list)
    jobs_error = Signal(str)
    job_uploading = Signal(object)  # JobInfo с status="uploading" - показывается сразу
    job_created = Signal(object)
    job_create_error = Signal(str, str)  # error_type, message
    # Сигналы для скачивания
    download_started = Signal(str, int)  # job_id, total_files
    download_progress = Signal(str, int, str)  # job_id, current_file_num, filename
    download_finished = Signal(str, str)  # job_id, extract_dir
    download_error = Signal(str, str)  # job_id, error_message
