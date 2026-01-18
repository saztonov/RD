"""OpenRouter OCR Backend with model fallback support."""

import logging
from pathlib import Path
from typing import Callable, List, Optional, Tuple, Union

from PIL import Image

import requests

from rd_pipeline.ocr.utils import image_to_base64, image_to_pdf_base64, pdf_file_to_base64
from rd_pipeline.ocr.http_utils import create_session_with_retries

logger = logging.getLogger(__name__)

# HTTP status codes that trigger fallback to next model
FALLBACK_STATUS_CODES = (500, 502, 503, 529)  # 529 = model overloaded


class OpenRouterBackend:
    """OCR via OpenRouter API with model fallback support."""

    _providers_cache: dict = {}

    DEFAULT_SYSTEM = "You are an expert design engineer and automation specialist. Your task is to analyze technical drawings and extract data into structured JSON or Markdown formats with 100% accuracy. Do not omit details. Do not hallucinate values."
    DEFAULT_USER = "Recognize the content of the image."

    def __init__(
        self,
        api_key: str,
        model_name: str = "qwen/qwen3-vl-30b-a3b-instruct",
        rate_limiter=None,
        fallback_models: Optional[List[str]] = None,
        max_fallback_attempts: int = 2,
    ):
        """Initialize OpenRouter backend.

        Args:
            api_key: OpenRouter API key
            model_name: Primary model to use
            rate_limiter: Optional rate limiter instance
            fallback_models: List of fallback models to try on failure
            max_fallback_attempts: Maximum number of fallback attempts
        """
        self.api_key = api_key
        self.model_name = model_name
        self.rate_limiter = rate_limiter
        self.fallback_models = fallback_models or []
        self.max_fallback_attempts = max_fallback_attempts
        self._provider_order: Optional[List[str]] = None
        self.session = create_session_with_retries()
        logger.info(
            f"OpenRouter initialized (model: {self.model_name}, "
            f"fallbacks: {len(self.fallback_models)})"
        )

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

    def _prepare_prompts(self, prompt: Optional[dict]) -> Tuple[str, str]:
        """Extract system and user prompts from dict or use defaults.

        Args:
            prompt: Optional dict with 'system' and 'user' keys

        Returns:
            Tuple of (system_prompt, user_prompt)
        """
        if prompt and isinstance(prompt, dict):
            system_prompt = prompt.get("system", "") or self.DEFAULT_SYSTEM
            user_prompt = prompt.get("user", "") or self.DEFAULT_USER
        else:
            system_prompt = self.DEFAULT_SYSTEM
            user_prompt = self.DEFAULT_USER
        return system_prompt, user_prompt

    def _detect_json_mode(
        self, system_prompt: str, user_prompt: str, json_mode: Optional[bool]
    ) -> bool:
        """Detect if JSON mode should be enabled.

        Args:
            system_prompt: System prompt text
            user_prompt: User prompt text
            json_mode: Explicit JSON mode setting (overrides detection)

        Returns:
            True if JSON mode should be enabled
        """
        if json_mode is not None:
            return json_mode
        prompt_text = (system_prompt + user_prompt).lower()
        return "json" in prompt_text and (
            "return" in prompt_text or "верни" in prompt_text
        )

    def _build_payload(
        self,
        model: str,
        content_items: List[dict],
        system_prompt: str,
        json_mode: bool,
        is_gemini3: bool,
    ) -> dict:
        """Build request payload.

        Args:
            model: Model name to use
            content_items: List of content items (text, image_url)
            system_prompt: System prompt
            json_mode: Whether to enable JSON response format
            is_gemini3: Whether this is a Gemini-3 model

        Returns:
            Request payload dict
        """
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content_items},
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

        return payload

    def _handle_error_response(self, response: requests.Response) -> str:
        """Handle error response and return error message.

        Args:
            response: HTTP response object

        Returns:
            Error message string
        """
        error_detail = response.text[:500] if response.text else "No details"
        logger.error(
            f"OpenRouter API error: {response.status_code} - {error_detail}"
        )

        if response.status_code == 403:
            try:
                err_json = response.json()
                err_msg = err_json.get("error", {}).get("message", "Access denied")
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

    def _parse_response(self, response: requests.Response) -> str:
        """Parse successful response.

        Args:
            response: HTTP response object

        Returns:
            Extracted text content
        """
        result = response.json()
        return result["choices"][0]["message"]["content"].strip()

    def _execute_with_fallbacks(
        self,
        payload_builder: Callable[[str], dict],
        timeout: int = 120,
    ) -> str:
        """Execute request with model fallback support.

        Args:
            payload_builder: Function that takes model name and returns payload
            timeout: Request timeout in seconds

        Returns:
            OCR result or error message
        """
        models_to_try = [self.model_name] + self.fallback_models[: self.max_fallback_attempts]
        last_error = None

        for i, model in enumerate(models_to_try):
            is_fallback = i > 0
            if is_fallback:
                logger.info(f"Trying fallback model: {model}")

            try:
                payload = payload_builder(model)

                response = self.session.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=timeout,
                )

                if response.status_code == 200:
                    text = self._parse_response(response)
                    if is_fallback:
                        logger.info(f"Fallback model {model} succeeded")
                    logger.debug(f"OpenRouter OCR: recognized {len(text)} characters")
                    return text

                # Check if error is retriable (should try fallback)
                if response.status_code in FALLBACK_STATUS_CODES:
                    last_error = f"HTTP {response.status_code}"
                    logger.warning(
                        f"Model {model} unavailable ({response.status_code}), "
                        f"trying next fallback"
                    )
                    continue

                # Non-retriable error - return immediately
                return self._handle_error_response(response)

            except requests.exceptions.Timeout:
                last_error = "timeout"
                logger.warning(f"Model {model} timeout, trying next fallback")
                continue
            except requests.exceptions.ConnectionError as e:
                last_error = f"connection error: {e}"
                logger.warning(f"Model {model} connection error, trying next fallback")
                continue
            except Exception as e:
                logger.error(f"Unexpected error with model {model}: {e}", exc_info=True)
                return f"[OpenRouter OCR Error: {e}]"

        return f"[OpenRouter Error: All models failed. Last error: {last_error}]"

    def recognize(
        self,
        image: Image.Image,
        prompt: Optional[dict] = None,
        json_mode: bool = None,
        timeout_multiplier: int = 1,
    ) -> str:
        """Recognize text via OpenRouter API.

        Args:
            image: PIL Image to recognize
            prompt: Optional dict with 'system' and 'user' keys
            json_mode: Force JSON output mode
            timeout_multiplier: Accepted for interface compatibility (not used)

        Returns:
            Recognized text or error message
        """
        # Rate limiting
        if self.rate_limiter:
            if not self.rate_limiter.acquire():
                return "[Error: rate limiter timeout]"

        try:
            if self._provider_order is None:
                self._provider_order = self._fetch_cheapest_providers() or []

            system_prompt, user_prompt = self._prepare_prompts(prompt)
            json_mode_enabled = self._detect_json_mode(system_prompt, user_prompt, json_mode)

            def build_payload(model: str) -> dict:
                is_gemini3 = "gemini-3" in model.lower()

                if is_gemini3:
                    file_b64 = image_to_pdf_base64(image)
                    media_type = "application/pdf"
                else:
                    file_b64 = image_to_base64(image)
                    media_type = "image/png"

                content_items = [
                    {"type": "text", "text": user_prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{media_type};base64,{file_b64}"},
                    },
                ]

                return self._build_payload(
                    model=model,
                    content_items=content_items,
                    system_prompt=system_prompt,
                    json_mode=json_mode_enabled,
                    is_gemini3=is_gemini3,
                )

            return self._execute_with_fallbacks(build_payload, timeout=120)

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
        timeout_multiplier: int = 1,
    ) -> str:
        """Recognize text directly from PDF file.

        Only for Gemini-3 models.

        Args:
            pdf_path: Path to PDF file
            prompt: Optional dict with 'system' and 'user' keys
            json_mode: Force JSON output mode
            timeout_multiplier: Accepted for interface compatibility (not used)

        Returns:
            Recognized text or error message
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

            system_prompt, user_prompt = self._prepare_prompts(prompt)
            json_mode_enabled = self._detect_json_mode(system_prompt, user_prompt, json_mode)

            # Read PDF file directly
            file_b64 = pdf_file_to_base64(str(pdf_path))

            def build_payload(model: str) -> dict:
                content_items = [
                    {"type": "text", "text": user_prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:application/pdf;base64,{file_b64}"},
                    },
                ]

                return self._build_payload(
                    model=model,
                    content_items=content_items,
                    system_prompt=system_prompt,
                    json_mode=json_mode_enabled,
                    is_gemini3=True,
                )

            result = self._execute_with_fallbacks(build_payload, timeout=120)
            logger.debug(f"OpenRouter OCR (native PDF): recognized {len(result)} characters")
            return result

        except Exception as e:
            logger.error(f"OpenRouter OCR (native PDF) error: {e}", exc_info=True)
            return f"[OpenRouter OCR Error: {e}]"
        finally:
            if self.rate_limiter:
                self.rate_limiter.release()
