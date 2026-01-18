"""OpenRouter OCR Backend."""

import logging
from pathlib import Path
from typing import List, Optional, Union

from PIL import Image

import requests

from rd_pipeline.ocr.utils import image_to_base64, image_to_pdf_base64, pdf_file_to_base64
from rd_pipeline.ocr.http_utils import create_session_with_retries

logger = logging.getLogger(__name__)


class OpenRouterBackend:
    """OCR via OpenRouter API."""

    _providers_cache: dict = {}

    DEFAULT_SYSTEM = "You are an expert design engineer and automation specialist. Your task is to analyze technical drawings and extract data into structured JSON or Markdown formats with 100% accuracy. Do not omit details. Do not hallucinate values."
    DEFAULT_USER = "Recognize the content of the image."

    def __init__(
        self,
        api_key: str,
        model_name: str = "qwen/qwen3-vl-30b-a3b-instruct",
        rate_limiter=None,
    ):
        self.api_key = api_key
        self.model_name = model_name
        self.rate_limiter = rate_limiter
        self._provider_order: Optional[List[str]] = None
        self.session = create_session_with_retries()
        logger.info(f"OpenRouter initialized (model: {self.model_name})")

    def _fetch_cheapest_providers(self) -> Optional[List[str]]:
        """Get list of providers sorted by price."""
        if self.model_name in OpenRouterBackend._providers_cache:
            return OpenRouterBackend._providers_cache[self.model_name]

        try:
            response = self.session.get(
                "https://openrouter.ai/api/v1/models",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=30,
            )
            if response.status_code != 200:
                logger.warning(
                    f"Failed to get models list: {response.status_code}"
                )
                return None

            models_data = response.json().get("data", [])

            model_info = None
            for m in models_data:
                if m.get("id") == self.model_name:
                    model_info = m
                    break

            if not model_info:
                logger.warning(f"Model {self.model_name} not found in list")
                return None

            pricing = model_info.get("endpoint", {}).get("pricing", {})
            if not pricing:
                pricing = model_info.get("pricing", {})

            providers_pricing = []
            if isinstance(pricing, dict) and "providers" in pricing:
                for provider_id, pdata in pricing.get("providers", {}).items():
                    prompt_cost = float(pdata.get("prompt", 0) or 0)
                    completion_cost = float(pdata.get("completion", 0) or 0)
                    total = prompt_cost + completion_cost
                    providers_pricing.append((provider_id, total))
            elif isinstance(pricing, list):
                for pdata in pricing:
                    provider_id = pdata.get("provider_id") or pdata.get("provider")
                    if provider_id:
                        prompt_cost = float(pdata.get("prompt", 0) or 0)
                        completion_cost = float(pdata.get("completion", 0) or 0)
                        total = prompt_cost + completion_cost
                        providers_pricing.append((provider_id, total))

            if not providers_pricing:
                logger.info("Provider pricing not found, using default")
                return None

            providers_pricing.sort(key=lambda x: x[1])
            provider_order = [p[0] for p in providers_pricing]

            logger.info(f"Providers for {self.model_name} (by price): {provider_order}")
            OpenRouterBackend._providers_cache[self.model_name] = provider_order
            return provider_order

        except Exception as e:
            logger.warning(f"Error getting providers: {e}")
            return None

    def recognize(
        self, image: Image.Image, prompt: Optional[dict] = None, json_mode: bool = None
    ) -> str:
        """Recognize text via OpenRouter API."""
        # Rate limiting
        if self.rate_limiter:
            if not self.rate_limiter.acquire():
                return "[Error: rate limiter timeout]"

        try:
            if self._provider_order is None:
                self._provider_order = self._fetch_cheapest_providers() or []

            if prompt and isinstance(prompt, dict):
                system_prompt = prompt.get("system", "") or self.DEFAULT_SYSTEM
                user_prompt = prompt.get("user", "") or self.DEFAULT_USER
            else:
                system_prompt = self.DEFAULT_SYSTEM
                user_prompt = self.DEFAULT_USER

            if json_mode is None:
                prompt_text = (system_prompt + user_prompt).lower()
                json_mode = "json" in prompt_text and (
                    "return" in prompt_text or "верни" in prompt_text
                )

            is_gemini3 = "gemini-3" in self.model_name.lower()

            if is_gemini3:
                file_b64 = image_to_pdf_base64(image)
                media_type = "application/pdf"
            else:
                file_b64 = image_to_base64(image)
                media_type = "image/png"

            payload = {
                "model": self.model_name,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user_prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{media_type};base64,{file_b64}"
                                },
                            },
                        ],
                    },
                ],
                "max_tokens": 16384,
                "temperature": 0.0 if is_gemini3 else 0.1,
                "top_p": 0.9,
            }

            if json_mode:
                payload["response_format"] = {"type": "json_object"}

            if is_gemini3:
                payload["transforms"] = {"media_resolution": "MEDIA_RESOLUTION_HIGH"}

            if self._provider_order:
                payload["provider"] = {"order": self._provider_order}

            response = self.session.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=120,
            )

            if response.status_code != 200:
                error_detail = response.text[:500] if response.text else "No details"
                logger.error(
                    f"OpenRouter API error: {response.status_code} - {error_detail}"
                )

                if response.status_code == 403:
                    try:
                        err_json = response.json()
                        err_msg = err_json.get("error", {}).get(
                            "message", "Access denied"
                        )
                    except:
                        err_msg = "Check API key and balance at openrouter.ai"
                    return f"[OpenRouter Error 403: {err_msg}]"
                elif response.status_code == 401:
                    return "[OpenRouter Error 401: Invalid API key]"
                elif response.status_code == 429:
                    if self.rate_limiter and hasattr(self.rate_limiter, "report_429"):
                        retry_after = response.headers.get("Retry-After")
                        self.rate_limiter.report_429(
                            int(retry_after) if retry_after else None
                        )
                    return "[OpenRouter Error 429: Rate limit exceeded]"
                elif response.status_code == 402:
                    return "[OpenRouter Error 402: Insufficient credits]"

                return f"[OpenRouter API Error: {response.status_code}]"

            result = response.json()
            text = result["choices"][0]["message"]["content"].strip()
            logger.debug(f"OpenRouter OCR: recognized {len(text)} characters")
            return text

        except requests.exceptions.Timeout:
            logger.error("OpenRouter OCR: timeout exceeded")
            return "[Error: request timeout exceeded]"
        except Exception as e:
            logger.error(f"OpenRouter OCR error: {e}", exc_info=True)
            return f"[OpenRouter OCR Error: {e}]"
        finally:
            if self.rate_limiter:
                self.rate_limiter.release()

    def supports_native_pdf(self) -> bool:
        """Check if model supports direct PDF input (only Gemini-3)."""
        return "gemini-3" in self.model_name.lower()

    def recognize_pdf(
        self,
        pdf_path: Union[str, Path],
        prompt: Optional[dict] = None,
        json_mode: bool = None,
    ) -> str:
        """
        Recognize text directly from PDF file.
        Only for Gemini-3 models.

        Args:
            pdf_path: path to PDF file
            prompt: dict with keys 'system' and 'user' (optional)
            json_mode: force JSON output mode

        Returns:
            Recognized text
        """
        if not self.supports_native_pdf():
            raise NotImplementedError(
                f"Model {self.model_name} doesn't support direct PDF input"
            )

        # Rate limiting
        if self.rate_limiter:
            if not self.rate_limiter.acquire():
                return "[Error: rate limiter timeout]"

        try:
            pdf_path = Path(pdf_path)
            if not pdf_path.exists():
                return f"[Error: PDF file not found: {pdf_path}]"

            if self._provider_order is None:
                self._provider_order = self._fetch_cheapest_providers() or []

            if prompt and isinstance(prompt, dict):
                system_prompt = prompt.get("system", "") or self.DEFAULT_SYSTEM
                user_prompt = prompt.get("user", "") or self.DEFAULT_USER
            else:
                system_prompt = self.DEFAULT_SYSTEM
                user_prompt = self.DEFAULT_USER

            if json_mode is None:
                prompt_text = (system_prompt + user_prompt).lower()
                json_mode = "json" in prompt_text and (
                    "return" in prompt_text or "верни" in prompt_text
                )

            # Read PDF file directly
            file_b64 = pdf_file_to_base64(str(pdf_path))
            media_type = "application/pdf"

            payload = {
                "model": self.model_name,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user_prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{media_type};base64,{file_b64}"
                                },
                            },
                        ],
                    },
                ],
                "max_tokens": 16384,
                "temperature": 0.0,
                "top_p": 0.9,
            }

            if json_mode:
                payload["response_format"] = {"type": "json_object"}

            # Gemini-3 specific parameters
            payload["transforms"] = {"media_resolution": "MEDIA_RESOLUTION_HIGH"}

            if self._provider_order:
                payload["provider"] = {"order": self._provider_order}

            response = self.session.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=120,
            )

            if response.status_code != 200:
                error_detail = response.text[:500] if response.text else "No details"
                logger.error(
                    f"OpenRouter API error: {response.status_code} - {error_detail}"
                )

                if response.status_code == 403:
                    try:
                        err_json = response.json()
                        err_msg = err_json.get("error", {}).get(
                            "message", "Access denied"
                        )
                    except:
                        err_msg = "Check API key and balance at openrouter.ai"
                    return f"[OpenRouter Error 403: {err_msg}]"
                elif response.status_code == 401:
                    return "[OpenRouter Error 401: Invalid API key]"
                elif response.status_code == 429:
                    if self.rate_limiter and hasattr(self.rate_limiter, "report_429"):
                        retry_after = response.headers.get("Retry-After")
                        self.rate_limiter.report_429(
                            int(retry_after) if retry_after else None
                        )
                    return "[OpenRouter Error 429: Rate limit exceeded]"
                elif response.status_code == 402:
                    return "[OpenRouter Error 402: Insufficient credits]"

                return f"[OpenRouter API Error: {response.status_code}]"

            result = response.json()
            text = result["choices"][0]["message"]["content"].strip()
            logger.debug(f"OpenRouter OCR (native PDF): recognized {len(text)} characters")
            return text

        except requests.exceptions.Timeout:
            logger.error("OpenRouter OCR: timeout exceeded")
            return "[Error: request timeout exceeded]"
        except Exception as e:
            logger.error(f"OpenRouter OCR (native PDF) error: {e}", exc_info=True)
            return f"[OpenRouter OCR Error: {e}]"
        finally:
            if self.rate_limiter:
                self.rate_limiter.release()
