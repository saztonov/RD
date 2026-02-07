"""Chandra OCR Backend (LM Studio / OpenAI-compatible API)"""
import logging
import os
from typing import Optional

from PIL import Image

from rd_core.ocr.utils import image_to_base64

logger = logging.getLogger(__name__)

# Промпт из официального репо Chandra (ocr_test.py)
ALLOWED_TAGS = "p, h1, h2, h3, h4, h5, h6, table, thead, tbody, tr, th, td, ul, ol, li, br, sub, sup, div, span, img, math, mi, mo, mn, msup, msub, mfrac, msqrt, mrow, mover, munder, munderover, mtable, mtr, mtd, mtext, mspace, input"
ALLOWED_ATTRIBUTES = "colspan, rowspan, alt, type, checked, value, data-bbox, data-label"

CHANDRA_DEFAULT_PROMPT = f"""OCR this image to HTML.

Only use these tags [{ALLOWED_TAGS}], and these attributes [{ALLOWED_ATTRIBUTES}].

Guidelines:
* Inline math: Surround math with <math>...</math> tags. Math expressions should be rendered in KaTeX-compatible LaTeX. Use display for block math.
* Tables: Use colspan and rowspan attributes to match table structure.
* Formatting: Maintain consistent formatting with the image, including spacing, indentation, subscripts/superscripts, and special characters.
* Images: Include a description of any images in the alt attribute of an <img> tag. Do not fill out the src property.
* Forms: Mark checkboxes and radio buttons properly.
* Text: join lines together properly into paragraphs using <p>...</p> tags. Use <br> tags for line breaks within paragraphs, but only when absolutely necessary to maintain meaning.
* Use the simplest possible HTML structure that accurately represents the content of the block.
* Make sure the text is accurate and easy for a human to read and interpret. Reading order should be correct and natural."""


class ChandraBackend:
    """OCR через Chandra модель (LM Studio, OpenAI-compatible API)"""

    DEFAULT_BASE_URL = "https://louvred-madie-gigglier.ngrok-free.dev"

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = base_url or os.getenv("CHANDRA_BASE_URL", self.DEFAULT_BASE_URL)
        self._model_id: Optional[str] = None

        try:
            import requests
            from requests.adapters import HTTPAdapter
            from urllib3.util.retry import Retry

            self.session = requests.Session()
            retry = Retry(total=3, backoff_factor=0.5, status_forcelist=[502, 503, 504])
            adapter = HTTPAdapter(
                pool_connections=5, pool_maxsize=10, max_retries=retry
            )
            self.session.mount("https://", adapter)
            self.session.mount("http://", adapter)
            self.requests = requests
        except ImportError:
            raise ImportError("Требуется установить requests: pip install requests")

        logger.info(f"ChandraBackend инициализирован (base_url: {self.base_url})")

    def _discover_model(self) -> str:
        """Авто-определение модели через /v1/models"""
        if self._model_id:
            return self._model_id

        try:
            resp = self.session.get(
                f"{self.base_url}/v1/models",
                timeout=30,
            )
            if resp.status_code == 200:
                for m in resp.json().get("data", []):
                    if "chandra" in m.get("id", "").lower():
                        self._model_id = m["id"]
                        logger.info(f"Chandra модель найдена: {self._model_id}")
                        return self._model_id
        except Exception as e:
            logger.warning(f"Ошибка определения модели Chandra: {e}")

        self._model_id = "chandra-ocr"
        logger.info(f"Chandra модель не найдена, используется fallback: {self._model_id}")
        return self._model_id

    def supports_pdf_input(self) -> bool:
        """Chandra не поддерживает прямой ввод PDF"""
        return False

    def recognize(
        self,
        image: Optional[Image.Image],
        prompt: Optional[dict] = None,
        json_mode: bool = None,
        pdf_file_path: Optional[str] = None,
    ) -> str:
        """Распознать текст через Chandra (LM Studio API)"""
        if image is None:
            return "[Ошибка: Chandra требует изображение]"

        try:
            model_id = self._discover_model()
            img_b64 = image_to_base64(image)

            # Используем переданный prompt или дефолтный Chandra промпт
            if prompt and isinstance(prompt, dict):
                user_prompt = prompt.get("user", "") or CHANDRA_DEFAULT_PROMPT
            else:
                user_prompt = CHANDRA_DEFAULT_PROMPT

            payload = {
                "model": model_id,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{img_b64}"
                                },
                            },
                            {
                                "type": "text",
                                "text": user_prompt,
                            },
                        ],
                    }
                ],
                "max_tokens": 12384,
                "temperature": 0,
                "top_p": 0.1,
            }

            response = self.session.post(
                f"{self.base_url}/v1/chat/completions",
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=300,
            )

            if response.status_code != 200:
                error_detail = response.text[:500] if response.text else "No details"
                logger.error(
                    f"Chandra API error: {response.status_code} - {error_detail}"
                )
                return f"[Ошибка Chandra API: {response.status_code}]"

            result = response.json()
            text = result["choices"][0]["message"]["content"].strip()
            logger.debug(f"Chandra OCR: распознано {len(text)} символов")
            return text

        except self.requests.exceptions.Timeout:
            logger.error("Chandra OCR: превышен таймаут")
            return "[Ошибка: превышен таймаут запроса к Chandra]"
        except Exception as e:
            logger.error(f"Ошибка Chandra OCR: {e}", exc_info=True)
            return f"[Ошибка Chandra OCR: {e}]"
