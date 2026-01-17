"""Datalab OCR Backend."""

import logging
from typing import Optional

from PIL import Image

logger = logging.getLogger(__name__)


class DatalabOCRBackend:
    """OCR via Datalab Marker API."""

    API_URL = "https://www.datalab.to/api/v1/marker"
    MAX_WIDTH = 4000

    # Default values (overridden via settings)
    DEFAULT_POLL_INTERVAL = 3
    DEFAULT_POLL_MAX_ATTEMPTS = 90
    DEFAULT_MAX_RETRIES = 3

    def __init__(
        self,
        api_key: str,
        rate_limiter=None,
        poll_interval: Optional[int] = None,
        poll_max_attempts: Optional[int] = None,
        max_retries: Optional[int] = None,
    ):
        if not api_key:
            raise ValueError("DATALAB_API_KEY not specified")
        self.api_key = api_key
        self.headers = {"X-Api-Key": api_key}
        self.rate_limiter = rate_limiter
        self.last_html_result: Optional[str] = None  # HTML result of last request

        # Polling settings (from parameters or default)
        self.poll_interval = poll_interval if poll_interval is not None else self.DEFAULT_POLL_INTERVAL
        self.poll_max_attempts = poll_max_attempts if poll_max_attempts is not None else self.DEFAULT_POLL_MAX_ATTEMPTS
        self.max_retries = max_retries if max_retries is not None else self.DEFAULT_MAX_RETRIES

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
        except ImportError:
            raise ImportError("requests required: pip install requests")
        logger.info(
            f"Datalab OCR initialized (poll_interval={self.poll_interval}s, "
            f"poll_max_attempts={self.poll_max_attempts}, max_retries={self.max_retries})"
        )

    def recognize(
        self, image: Image.Image, prompt: Optional[dict] = None, json_mode: bool = None
    ) -> str:
        """Recognize image via Datalab API."""
        import os
        import tempfile
        import time

        logger.info(f"Datalab.recognize: получено изображение {image.width}x{image.height}")

        if self.rate_limiter:
            if not self.rate_limiter.acquire():
                logger.warning("Datalab.recognize: rate limiter timeout")
                return "[Error: rate limiter timeout]"

        try:
            if image.width > self.MAX_WIDTH:
                ratio = self.MAX_WIDTH / image.width
                new_width = self.MAX_WIDTH
                new_height = int(image.height * ratio)
                logger.info(
                    f"Resizing image {image.width}x{image.height} -> {new_width}x{new_height}"
                )
                image = image.resize((new_width, new_height), Image.LANCZOS)

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                image.save(tmp, format="PNG")
                tmp_path = tmp.name

            try:
                # Outer retry loop for re-sending on polling timeout
                for full_retry in range(self.max_retries):
                    if full_retry > 0:
                        logger.warning(
                            f"Datalab: re-sending request (attempt {full_retry + 1}/{self.max_retries})"
                        )

                    response = None
                    for retry in range(self.max_retries):
                        with open(tmp_path, "rb") as f:
                            import json

                            files = {"file": (os.path.basename(tmp_path), f, "image/png")}
                            data = {
                                "mode": "accurate",
                                "paginate": "true",
                                "output_format": "html",
                                "disable_image_extraction": "true",
                                "disable_image_captions": "true",
                                "additional_config": json.dumps(
                                    {"keep_pageheader_in_output": True}
                                ),
                            }

                            response = self.session.post(
                                self.API_URL,
                                headers=self.headers,
                                files=files,
                                data=data,
                                timeout=120,
                            )

                        if response.status_code == 429:
                            if self.rate_limiter and hasattr(self.rate_limiter, "report_429"):
                                retry_after = response.headers.get("Retry-After")
                                self.rate_limiter.report_429(
                                    int(retry_after) if retry_after else None
                                )
                            wait_time = min(60, (2**retry) * 10)
                            logger.warning(
                                f"Datalab API 429: waiting {wait_time}s (attempt {retry + 1}/{self.max_retries})"
                            )
                            time.sleep(wait_time)
                            continue
                        break

                    if response is None or response.status_code == 429:
                        return "[Datalab API Error: rate limit exceeded (429)]"

                    if response.status_code != 200:
                        logger.error(
                            f"Datalab API error: {response.status_code} - {response.text}"
                        )
                        return f"[Datalab API Error: {response.status_code}]"

                    result = response.json()

                    if not result.get("success"):
                        error = result.get("error", "Unknown error")
                        return f"[Datalab Error: {error}]"

                    check_url = result.get("request_check_url")
                    if not check_url:
                        if "json" in result:
                            json_result = result["json"]
                            if isinstance(json_result, dict):
                                import json as json_lib

                                return json_lib.dumps(json_result, ensure_ascii=False)
                            return json_result
                        return "[Error: no request_check_url]"

                    logger.info(f"Datalab: starting polling at URL: {check_url}")
                    for attempt in range(self.poll_max_attempts):
                        time.sleep(self.poll_interval)

                        logger.debug(
                            f"Datalab: polling attempt {attempt + 1}/{self.poll_max_attempts}"
                        )
                        poll_response = self.session.get(
                            check_url, headers=self.headers, timeout=30
                        )

                        if poll_response.status_code == 429:
                            if self.rate_limiter and hasattr(self.rate_limiter, "report_429"):
                                retry_after = poll_response.headers.get("Retry-After")
                                self.rate_limiter.report_429(
                                    int(retry_after) if retry_after else None
                                )
                            logger.warning("Datalab: 429 during polling, waiting 30s")
                            time.sleep(30)
                            continue

                        if poll_response.status_code != 200:
                            logger.warning(
                                f"Datalab: polling returned status {poll_response.status_code}: {poll_response.text}"
                            )
                            continue

                        poll_result = poll_response.json()
                        status = poll_result.get("status", "")

                        logger.info(
                            f"Datalab: current task status: '{status}' (attempt {attempt + 1}/{self.poll_max_attempts})"
                        )

                        if status == "complete":
                            logger.info("Datalab: task completed successfully")
                            html_result = poll_result.get("html", "")
                            logger.debug(
                                f"Datalab: response keys: {list(poll_result.keys())}"
                            )
                            self.last_html_result = html_result if html_result else None
                            return html_result if html_result else ""
                        elif status == "failed":
                            error = poll_result.get("error", "Unknown error")
                            logger.error(f"Datalab: task failed with error: {error}")
                            return f"[Datalab Error: {error}]"
                        elif status not in ["processing", "pending", "queued"]:
                            logger.warning(
                                f"Datalab: unknown status '{status}'. Full response: {poll_result}"
                            )

                    # Polling timeout - try sending new request
                    logger.warning(
                        f"Datalab: polling timeout after {self.poll_max_attempts} attempts, "
                        f"retry {full_retry + 1}/{self.max_retries}"
                    )

                    if full_retry < self.max_retries - 1:
                        # Wait before re-sending
                        wait_time = (full_retry + 1) * 10
                        logger.info(f"Datalab: waiting {wait_time}s before re-sending")
                        time.sleep(wait_time)

                # All retries exhausted
                logger.error(
                    f"Datalab: timeout exceeded after {self.max_retries} full attempts"
                )
                logger.warning(
                    f"Datalab: skipping block due to timeout, continuing processing"
                )
                return "[TIMEOUT]"

            finally:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)

        except Exception as e:
            logger.error(f"Datalab OCR error: {e}", exc_info=True)
            return f"[Datalab OCR Error: {e}]"
        finally:
            if self.rate_limiter:
                self.rate_limiter.release()
