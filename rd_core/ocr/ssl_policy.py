"""TLS verification policy for OCR HTTP sessions.

Бэкенды OCR (OpenRouter/Chandra) ходят через self-hosted прокси с собственным CA.
Datalab и прочие — напрямую к публичным хостам. Поэтому при заданном CA
используется объединённый бандл (certifi + CA), чтобы оба сценария работали.

Env:
- ``OCR_CA_CERT`` — путь к CA-бандлу прокси (предпочтительно).
- ``OCR_VERIFY_SSL=false`` — отключить проверку (только временная диагностика).
"""
from __future__ import annotations

import os
from typing import Union

from rd_core.tls_policy import resolve_verify


def ocr_ssl_verify() -> Union[bool, str]:
    """Вернуть значение ``verify`` для requests-сессий OCR."""
    return resolve_verify(os.getenv("OCR_CA_CERT"), os.getenv("OCR_VERIFY_SSL"))
