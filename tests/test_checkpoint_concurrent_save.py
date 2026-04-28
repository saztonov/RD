"""Тест thread-safety OCRCheckpoint.save() при параллельных
mark_image_processed / mark_strip_processed.

Регрессия 2026-04-28: json.dump(self.partial_results) падал с
RuntimeError("dictionary changed size during iteration") когда другой
fork-pool worker модифицировал словарь параллельно.
"""

import threading
import time
from pathlib import Path

from services.remote_ocr.server.checkpoint_models import OCRCheckpoint


def test_concurrent_mark_and_save_does_not_crash(tmp_path):
    """Запускаем save() в одном потоке и параллельно множественные mark_*
    в других. За 1 секунду НЕ должно быть RuntimeError."""
    cp = OCRCheckpoint(job_id="test-job", phase="pass2_strips")

    stop = threading.Event()
    errors: list[BaseException] = []

    save_path = tmp_path / "checkpoint.json"

    def saver():
        try:
            while not stop.is_set():
                cp.save(save_path)
                # Даём другим потокам шанс мутировать
                time.sleep(0.001)
        except BaseException as e:
            errors.append(e)

    def writer_strips(start_id: int):
        try:
            i = start_id
            while not stop.is_set():
                cp.mark_strip_processed(
                    f"strip_{i:04d}",
                    block_results={f"block_{i}_{j}": f"text-{j}" for j in range(5)},
                )
                i += 1
        except BaseException as e:
            errors.append(e)

    def writer_images(start_id: int):
        try:
            i = start_id
            while not stop.is_set():
                # split-блок: добавляем по частям, чтобы трогать partial_parts
                cp.mark_image_processed(
                    f"img_{i:04d}", f"part-text-{i}-0", part_idx=0, total_parts=2
                )
                cp.mark_image_processed(
                    f"img_{i:04d}", f"part-text-{i}-1", part_idx=1, total_parts=2
                )
                # И обычный single-part блок
                cp.mark_image_processed(
                    f"single_{i:04d}", f"single-{i}", part_idx=0, total_parts=1
                )
                i += 1
        except BaseException as e:
            errors.append(e)

    threads = [
        threading.Thread(target=saver, daemon=True),
        threading.Thread(target=writer_strips, args=(0,), daemon=True),
        threading.Thread(target=writer_strips, args=(10000,), daemon=True),
        threading.Thread(target=writer_images, args=(0,), daemon=True),
        threading.Thread(target=writer_images, args=(20000,), daemon=True),
    ]
    for t in threads:
        t.start()

    time.sleep(1.0)
    stop.set()
    for t in threads:
        t.join(timeout=2)

    assert not errors, f"Concurrent save/mark выдал ошибку: {errors}"

    # И сам checkpoint остался валидным — можно загрузить обратно
    loaded = OCRCheckpoint.load(save_path)
    assert loaded is not None
    assert loaded.job_id == "test-job"
