"""Async Chandra OCR Backend (LM Studio / OpenAI-compatible API)"""
import logging
import os
from typing import Optional

import httpx
from PIL import Image

from rd_core.ocr.chandra import CHANDRA_DEFAULT_PROMPT, CHANDRA_DEFAULT_SYSTEM
from rd_core.ocr.utils import image_to_base64

logger = logging.getLogger(__name__)


class AsyncChandraBackend:
    """Асинхронный OCR через Chandra модель (LM Studio, OpenAI-compatible API)"""

    DEFAULT_BASE_URL = "https://louvred-madie-gigglier.ngrok-free.dev"

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = base_url or os.getenv("CHANDRA_BASE_URL", self.DEFAULT_BASE_URL)
        self._model_id: Optional[str] = None
        self._client: Optional[httpx.AsyncClient] = None

        logger.info(f"AsyncChandraBackend инициализирован (base_url: {self.base_url})")

    async def _get_client(self) -> httpx.AsyncClient:
        """Получить или создать httpx AsyncClient с connection pooling"""
        if self._client is None or self._client.is_closed:
            transport = httpx.AsyncHTTPTransport(
                retries=3,
                limits=httpx.Limits(
                    max_connections=10,
                    max_keepalive_connections=5,
                    keepalive_expiry=30.0,
                ),
            )
            self._client = httpx.AsyncClient(
                transport=transport,
                timeout=httpx.Timeout(300.0, connect=30.0),
            )
        return self._client

    async def close(self):
        """Закрыть HTTP клиент"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _discover_model(self) -> str:
        """Авто-определение модели через /v1/models"""
        if self._model_id:
            return self._model_id

        try:
            client = await self._get_client()
            resp = await client.get(
                f"{self.base_url}/v1/models",
                timeout=30.0,
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

    async def recognize_async(
        self,
        image: Optional[Image.Image],
        prompt: Optional[dict] = None,
        json_mode: bool = None,
        pdf_file_path: Optional[str] = None,
    ) -> str:
        """Асинхронно распознать текст через Chandra (LM Studio API)"""
        if image is None:
            return "[Ошибка: Chandra требует изображение]"

        try:
            client = await self._get_client()
            model_id = await self._discover_model()
            img_b64 = image_to_base64(image)

            # Chandra всегда использует свой специализированный HTML промпт
            # System prompt берём из переданного dict (контекст задачи)
            if prompt and isinstance(prompt, dict):
                system_prompt = prompt.get("system", "") or CHANDRA_DEFAULT_SYSTEM
            else:
                system_prompt = CHANDRA_DEFAULT_SYSTEM
            user_prompt = CHANDRA_DEFAULT_PROMPT

            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append(
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
            )

            payload = {
                "model": model_id,
                "messages": messages,
                "max_tokens": 12384,
                "temperature": 0,
                "top_p": 0.1,
            }

            response = await client.post(
                f"{self.base_url}/v1/chat/completions",
                headers={"Content-Type": "application/json"},
                json=payload,
            )

            if response.status_code != 200:
                error_detail = response.text[:500] if response.text else "No details"
                logger.error(
                    f"Chandra API error: {response.status_code} - {error_detail}"
                )
                return f"[Ошибка Chandra API: {response.status_code}]"

            result = response.json()
            text = result["choices"][0]["message"]["content"].strip()
            logger.debug(f"AsyncChandra OCR: распознано {len(text)} символов")
            return text

        except httpx.TimeoutException:
            logger.error("AsyncChandra OCR: превышен таймаут")
            return "[Ошибка: превышен таймаут запроса к Chandra]"
        except Exception as e:
            logger.error(f"Ошибка AsyncChandra OCR: {e}", exc_info=True)
            return f"[Ошибка Chandra OCR: {e}]"

    def __del__(self):
        """Cleanup при удалении объекта"""
        if self._client and not self._client.is_closed:
            logger.debug("AsyncChandraBackend: client not closed properly")
