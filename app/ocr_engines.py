"""
OCR engines для распознавания текста
"""

import logging
from abc import ABC, abstractmethod
from typing import Optional
from PIL import Image
import httpx
import asyncio
import base64
from io import BytesIO
from app.config import get_lm_base_url

logger = logging.getLogger(__name__)


class OCREngine(ABC):
    """Базовый класс для OCR-движков"""
    
    @abstractmethod
    def recognize(self, image: Image.Image, prompt: Optional[str] = None) -> str:
        """Распознать текст с изображения"""
        pass


class DummyOCREngine(OCREngine):
    """Заглушка OCR для тестов"""
    
    def recognize(self, image: Image.Image, prompt: Optional[str] = None) -> str:
        return "[Dummy OCR: установите настоящий OCR engine]"


class LocalVLMEngine(OCREngine):
    """OCR через ngrok endpoint (проксирует в LM Studio)"""
    
    def __init__(self, api_base: str = None, model_name: str = "qwen3-vl-32b-instruct"):
        # api_base игнорируется, всегда используем ngrok
        self.model_name = model_name
    
    def recognize(self, image: Image.Image, prompt: Optional[str] = None) -> str:
        """Распознать текст через ngrok endpoint"""
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        image_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
        
        user_prompt = prompt if prompt else "Распознай весь текст с этого изображения. Верни только текст, без комментариев."
        
        url = get_lm_base_url()
        payload = {
            "model": self.model_name,
            "messages": [
                {
                    "role": "system",
                    "content": "You are an expert design engineer and automation specialist. Your task is to analyze technical drawings and extract data into structured JSON or Markdown formats with 100% accuracy. Do not omit details. Do not hallucinate values."
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{image_base64}"}
                        }
                    ]
                }
            ],
            "max_tokens": 16384,
            "temperature": 0.1,
            "top_p": 0.9,
            "frequency_penalty": 0.0,
            "presence_penalty": 0.0
        }
        
        try:
            # Синхронная версия для совместимости
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(self._async_recognize(url, payload))
            loop.close()
            return result
        except Exception as e:
            logger.error(f"LocalVLM error: {e}", exc_info=True)
            return f"[Error: {e}]"
    
    async def _async_recognize(self, url: str, payload: dict) -> str:
        """Асинхронное распознавание"""
        async with httpx.AsyncClient(timeout=600.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            result = response.json()
            return result.get("choices", [{}])[0].get("message", {}).get("content", "").strip()


class OpenRouterVLMEngine(OCREngine):
    """OCR через OpenRouter API (qwen/qwen3-vl-30b-a3b-instruct)"""
    
    def __init__(self, api_key: str, model_name: str = "qwen/qwen3-vl-30b-a3b-instruct"):
        self.api_key = api_key
        self.model_name = model_name
        self._client = None
    
    def _get_client(self):
        """Lazy initialization клиента"""
        if self._client is None:
            try:
                from openai import OpenAI
                self._client = OpenAI(
                    base_url="https://openrouter.ai/api/v1",
                    api_key=self.api_key
                )
            except ImportError:
                raise ImportError(
                    "Для OpenRouter требуется библиотека openai.\n"
                    "Установите: pip install openai"
                )
        return self._client
    
    def recognize(self, image: Image.Image, prompt: Optional[str] = None) -> str:
        """Распознать текст через OpenRouter API"""
        import base64
        from io import BytesIO
        
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        image_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
        
        user_prompt = prompt if prompt else "Распознай весь текст с этого изображения. Верни только текст, без комментариев."
        
        client = self._get_client()
        response = client.chat.completions.create(
            model=self.model_name,
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert design engineer and automation specialist. Your task is to analyze technical drawings and extract data into structured JSON or Markdown formats with 100% accuracy. Do not omit details. Do not hallucinate values."
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{image_base64}"}
                        }
                    ]
                }
            ],
            max_tokens=16384,
            temperature=0.1,
            top_p=0.9
        )
        
        return response.choices[0].message.content.strip()


class ChandraOCREngine(OCREngine):
    """OCR через Chandra (surya-ocr)"""
    
    def __init__(self, method: str = "hf"):
        self.method = method
        self._model = None
        self._processor = None
    
    def _load_model(self):
        """Lazy loading модели"""
        if self._model is None or self._processor is None:
            try:
                if self.method == "hf":
                    from transformers import AutoProcessor, AutoModelForImageTextToText
                    model_name = "vidore/GOT_CPU"
                    self._processor = AutoProcessor.from_pretrained(model_name)
                    self._model = AutoModelForImageTextToText.from_pretrained(model_name)
                else:
                    from chandra_ocr import ChandraOCRModel
                    self._model = ChandraOCRModel()
            except ImportError as e:
                raise ImportError(
                    f"Для Chandra OCR требуется установка библиотек.\n"
                    f"Ошибка: {e}\n"
                    "Установите: pip install chandra-ocr или transformers"
                )
    
    def recognize(self, image: Image.Image, prompt: Optional[str] = None) -> str:
        """Распознать текст через Chandra"""
        self._load_model()
        
        if self.method == "hf":
            inputs = self._processor(images=image, return_tensors="pt")
            generated_ids = self._model.generate(**inputs, max_new_tokens=2048)
            result = self._processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
            return result.strip()
        else:
            result = self._model.recognize(image)
            return result.strip()


def create_ocr_engine(engine_type: str, **kwargs) -> OCREngine:
    """Создать OCR engine по типу"""
    if engine_type == "dummy":
        return DummyOCREngine()
    elif engine_type == "local_vlm":
        return LocalVLMEngine(**kwargs)
    elif engine_type == "openrouter":
        return OpenRouterVLMEngine(**kwargs)
    elif engine_type == "chandra":
        return ChandraOCREngine(**kwargs)
    else:
        raise ValueError(f"Неизвестный тип OCR engine: {engine_type}")
