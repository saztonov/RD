"""Datalab OCR Backend"""
import logging
from typing import Optional
from PIL import Image

logger = logging.getLogger(__name__)


class DatalabOCRBackend:
    """OCR через Datalab Marker API"""
    
    API_URL = "https://www.datalab.to/api/v1/marker"
    POLL_INTERVAL = 3
    MAX_POLL_ATTEMPTS = 180
    MAX_RETRIES = 3
    MAX_WIDTH = 4000
    
    BLOCK_CORRECTION_PROMPT = """You are a specialized QA OCR assistant for Russian Construction Documentation (Stages P & RD). Your goal is to transcribe image blocks into strict Markdown for automated error checking.

RULES:
1. **Content Fidelity (CRITICAL)**: Transcribe text and numbers EXACTLY as seen. 
   - NEVER "fix" math errors. If the sum in the image is wrong, keep it wrong. We need to find these errors.
   - NEVER round numbers. Preserve all decimals (e.g., "34,5").
2. **Tables**: If the image shows a table (Explication, Bill of Materials), output a VALID Markdown table.
   - If headers are cut off (missing from the image), output the data rows as a table without inventing headers.
   - Preserve merged cell content if implied.
3. **Abbreviations**: Keep Russian technical acronyms exactly as printed: "МХМТС", "БКТ", "ПУИ", "ВРУ", "ЛК", "С/у". Do not expand them.
4. **OCR Correction**: Fix ONLY visual character errors typical for Cyrillic OCR:
   - '0' (digit) vs 'O' (letter)
   - '3' (digit) vs 'З' (letter)
   - 'б' (letter) vs '6' (digit)
   - 'м2' -> 'м²'
5. **Drawings**: If the image is a drawing (e.g., parking layout), output a bulleted list of text labels and dimensions found (e.g., "- Малое м/м: 2600x5300").
6. **Block Separators (CRITICAL)**: If you see text like "[[[BLOCK_ID: uuid]]]" (black text on white background), you MUST preserve it EXACTLY in your output. These are block identifiers that must appear in the final text.
7. **Output**: Return ONLY the clean Markdown. No conversational filler."""
    
    def __init__(self, api_key: str, rate_limiter=None):
        if not api_key:
            raise ValueError("DATALAB_API_KEY не указан")
        self.api_key = api_key
        self.headers = {"X-Api-Key": api_key}
        self.rate_limiter = rate_limiter
        try:
            import requests
            from requests.adapters import HTTPAdapter
            from urllib3.util.retry import Retry
            
            self.session = requests.Session()
            retry = Retry(total=3, backoff_factor=0.5, status_forcelist=[502, 503, 504])
            adapter = HTTPAdapter(pool_connections=5, pool_maxsize=10, max_retries=retry)
            self.session.mount("https://", adapter)
            self.session.mount("http://", adapter)
        except ImportError:
            raise ImportError("Требуется установить requests: pip install requests")
        logger.info("Datalab OCR инициализирован")
    
    def recognize(self, image: Image.Image, prompt: Optional[dict] = None, json_mode: bool = None) -> str:
        """Распознать изображение через Datalab API"""
        import tempfile
        import time
        import os
        
        if self.rate_limiter:
            if not self.rate_limiter.acquire():
                return "[Ошибка: таймаут ожидания rate limiter]"
        
        try:
            if image.width > self.MAX_WIDTH:
                ratio = self.MAX_WIDTH / image.width
                new_width = self.MAX_WIDTH
                new_height = int(image.height * ratio)
                logger.info(f"Сжатие изображения {image.width}x{image.height} -> {new_width}x{new_height}")
                image = image.resize((new_width, new_height), Image.LANCZOS)
            
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                image.save(tmp, format='PNG')
                tmp_path = tmp.name
            
            try:
                response = None
                for retry in range(self.MAX_RETRIES):
                    with open(tmp_path, 'rb') as f:
                        import json
                        files = {'file': (os.path.basename(tmp_path), f, 'image/png')}
                        data = {
                            'mode': 'accurate',
                            'force_ocr': 'true',
                            'paginate': 'false',
                            'use_llm': 'true',
                            'output_format': 'json',
                            'disable_image_extraction': 'true',
                            'block_correction_prompt': self.BLOCK_CORRECTION_PROMPT,
                            'additional_config': json.dumps({'keep_pageheader_in_output': True})
                        }
                        
                        response = self.session.post(
                            self.API_URL,
                            headers=self.headers,
                            files=files,
                            data=data,
                            timeout=120
                        )
                    
                    if response.status_code == 429:
                        wait_time = min(60, (2 ** retry) * 10)
                        logger.warning(f"Datalab API 429: ждём {wait_time}с (попытка {retry + 1}/{self.MAX_RETRIES})")
                        time.sleep(wait_time)
                        continue
                    break
                
                if response is None or response.status_code == 429:
                    return "[Ошибка Datalab API: превышен лимит запросов (429)]"
                
                if response.status_code != 200:
                    logger.error(f"Datalab API error: {response.status_code} - {response.text}")
                    return f"[Ошибка Datalab API: {response.status_code}]"
                
                result = response.json()
                
                if not result.get('success'):
                    error = result.get('error', 'Unknown error')
                    return f"[Ошибка Datalab: {error}]"
                
                check_url = result.get('request_check_url')
                if not check_url:
                    if 'json' in result:
                        json_result = result['json']
                        if isinstance(json_result, dict):
                            import json as json_lib
                            return json_lib.dumps(json_result, ensure_ascii=False)
                        return json_result
                    return "[Ошибка: нет request_check_url]"
                
                logger.info(f"Datalab: начало поллинга результата по URL: {check_url}")
                for attempt in range(self.MAX_POLL_ATTEMPTS):
                    time.sleep(self.POLL_INTERVAL)
                    
                    logger.debug(f"Datalab: попытка поллинга {attempt + 1}/{self.MAX_POLL_ATTEMPTS}")
                    poll_response = self.session.get(check_url, headers=self.headers, timeout=30)
                    
                    if poll_response.status_code == 429:
                        logger.warning("Datalab: 429 при поллинге, ждём 30с")
                        time.sleep(30)
                        continue
                    
                    if poll_response.status_code != 200:
                        logger.warning(f"Datalab: поллинг вернул статус {poll_response.status_code}: {poll_response.text}")
                        continue
                    
                    poll_result = poll_response.json()
                    status = poll_result.get('status', '')
                    
                    logger.info(f"Datalab: текущий статус задачи: '{status}' (попытка {attempt + 1}/{self.MAX_POLL_ATTEMPTS})")
                    
                    if status == 'complete':
                        logger.info("Datalab: задача успешно завершена")
                        json_result = poll_result.get('json', '')
                        logger.debug(f"Datalab: тип результата: {type(json_result)}, ключи ответа: {list(poll_result.keys())}")
                        # Если результат - dict, преобразуем в строку JSON
                        if isinstance(json_result, dict):
                            import json as json_lib
                            return json_lib.dumps(json_result, ensure_ascii=False)
                        return json_result if json_result else ''
                    elif status == 'failed':
                        error = poll_result.get('error', 'Unknown error')
                        logger.error(f"Datalab: задача завершилась с ошибкой: {error}")
                        return f"[Ошибка Datalab: {error}]"
                    elif status not in ['processing', 'pending', 'queued']:
                        logger.warning(f"Datalab: неизвестный статус '{status}'. Полный ответ: {poll_result}")
                
                logger.error(f"Datalab: превышено время ожидания после {self.MAX_POLL_ATTEMPTS} попыток")
                return "[Ошибка Datalab: превышено время ожидания]"
                
            finally:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                    
        except Exception as e:
            logger.error(f"Ошибка Datalab OCR: {e}", exc_info=True)
            return f"[Ошибка Datalab OCR: {e}]"
        finally:
            if self.rate_limiter:
                self.rate_limiter.release()

