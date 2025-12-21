"""
Удаление штампов и QR-кодов из PDF документов.

Удаляет из content stream:
- Синие пути рамки (цвет 0.1098 0.53333 0.74902)
- Текстовые блоки (В ПРОИЗВОДСТВО РАБОТ, ООО, ГИП, дата)
- Белый прямоугольник (фон QR)
- XForm (QR-код)
"""
import re
import logging
from pathlib import Path
from typing import Optional, Callable

import fitz

logger = logging.getLogger(__name__)


class PDFStampRemover:
    """Удаление штампов из PDF"""
    
    STAMP_COLOR_PATTERN = r'0\.109\d*\s+0\.533\d*\s+0\.749\d*\s+rg\b'
    
    _NL = r'(?:\r?\n)'
    STAMP_BLOCK_START_PATTERN = (
        rf'q\s*{_NL}\s*1\s+0\s+0\s+1\s+0(?:\.\d+)?\s+0(?:\.\d+)?\s+cm\s*{_NL}\s*'
        rf'q\s*{_NL}\s*1\s+0\s+0\s+1\s+0(?:\.\d+)?\s+0(?:\.\d+)?\s+cm\s*{_NL}\s*'
        rf'q\s*{_NL}\s*{STAMP_COLOR_PATTERN}'
    )
    STAMP_BLOCK_START_PATTERN_ALT = (
        rf'q\s*{_NL}\s*1\s+0\s+0\s+1\s+0(?:\.\d+)?\s+0(?:\.\d+)?\s+cm\s*{_NL}\s*'
        rf'q\s*{_NL}\s*{STAMP_COLOR_PATTERN}'
    )
    
    def __init__(self, progress_callback: Optional[Callable[[int, str], None]] = None):
        self.progress_callback = progress_callback
    
    def _emit_progress(self, value: int, message: str):
        if self.progress_callback:
            self.progress_callback(value, message)
    
    def remove_stamps(self, input_path: str, output_path: str) -> tuple[bool, int, int]:
        """
        Удалить штампы из PDF.
        
        Returns:
            (success, pages_processed, total_pages)
        """
        try:
            self._emit_progress(0, "Открытие PDF файла...")
            doc = fitz.open(input_path)
            total_pages = len(doc)
            pages_processed = 0
            
            for page_num in range(total_pages):
                self._emit_progress(
                    int((page_num / total_pages) * 90),
                    f"Страница {page_num + 1} из {total_pages}..."
                )
                
                page = doc[page_num]
                if self._remove_stamp_from_page(doc, page, page_num + 1):
                    pages_processed += 1
            
            self._emit_progress(95, "Сохранение...")
            doc.save(output_path, garbage=4, deflate=True, clean=True)
            doc.close()
            
            self._emit_progress(100, "Готово!")
            return True, pages_processed, total_pages
            
        except Exception as e:
            logger.exception(f"Error removing stamps: {e}")
            return False, 0, 0
    
    def _remove_stamp_from_page(self, doc, page, page_num: int) -> bool:
        """Удалить штамп со страницы"""
        try:
            contents = page.get_contents() or []
            if isinstance(contents, int):
                contents = [contents]
            
            if not contents:
                return False
            
            for idx in range(len(contents) - 1, -1, -1):
                xref = contents[idx]
                try:
                    stream_bytes = doc.xref_stream(xref)
                except Exception:
                    stream_bytes = None
                
                if not stream_bytes:
                    continue
                
                stream_str = stream_bytes.decode("latin-1", errors="replace")
                stamp_start = self._find_stamp_start_in_content(stream_str)
                if stamp_start is None:
                    continue
                
                modified_str = stream_str[:stamp_start].rstrip() + "\n"
                modified_bytes = modified_str.encode("latin-1")
                doc.update_stream(xref, modified_bytes)
                
                for xref_tail in contents[idx + 1:]:
                    try:
                        doc.update_stream(xref_tail, b"\n")
                    except Exception:
                        pass
                
                logger.debug(f"Page {page_num}: stamp removed")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Page {page_num}: error - {e}")
            return False
    
    def _find_stamp_start_in_content(self, content_str: str) -> Optional[int]:
        """Найти позицию начала штампа"""
        for pat in (self.STAMP_BLOCK_START_PATTERN, self.STAMP_BLOCK_START_PATTERN_ALT):
            matches = list(re.finditer(pat, content_str))
            if matches:
                start = matches[-1].start()
                if self._looks_like_stamp_tail(content_str[start:]):
                    return start
        
        do_matches = list(re.finditer(r'/Fm[0-9A-Za-z]+\s+Do\b', content_str))
        if do_matches:
            fm_pos = do_matches[-1].start()
            prefix = content_str[:fm_pos]
            reset_matches = list(
                re.finditer(
                    rf'q\s*{self._NL}\s*1\s+0\s+0\s+1\s+0(?:\.\d+)?\s+0(?:\.\d+)?\s+cm\b',
                    prefix,
                )
            )
            if reset_matches:
                start = reset_matches[-1].start()
                if self._looks_like_stamp_tail(content_str[start:]):
                    return start
        
        return None
    
    def _looks_like_stamp_tail(self, tail: str) -> bool:
        """Эвристика для проверки хвоста"""
        blue_count = len(re.findall(self.STAMP_COLOR_PATTERN, tail))
        has_form_do = re.search(r'/Fm[0-9A-Za-z]+\s+Do\b', tail) is not None
        has_text_blocks = "BT" in tail and "ET" in tail
        return blue_count >= 4 and (has_form_do or has_text_blocks)


def remove_stamps_from_pdf(input_path: str, output_path: Optional[str] = None) -> tuple[bool, str]:
    """
    Удалить штампы из PDF файла.
    
    Args:
        input_path: Путь к исходному PDF
        output_path: Путь для сохранения (если None - создаётся рядом с _clean суффиксом)
    
    Returns:
        (success, output_path_or_error)
    """
    input_file = Path(input_path)
    if not input_file.exists():
        return False, "Файл не найден"
    
    if output_path is None:
        output_path = str(input_file.parent / f"{input_file.stem}_clean{input_file.suffix}")
    
    remover = PDFStampRemover()
    success, processed, total = remover.remove_stamps(input_path, output_path)
    
    if success:
        return True, output_path
    return False, "Ошибка обработки PDF"


