"""TLS verification policy for Supabase connections.

Supabase ходит через тот же прокси (``pro3.fvds.ru``) с собственным CA, что и OCR.
Поэтому при отсутствии ``SUPABASE_CA_CERT`` используется общий ``OCR_CA_CERT``.

Env:
- ``SUPABASE_CA_CERT`` / ``OCR_CA_CERT`` — путь к CA-бандлу прокси.
- ``SUPABASE_VERIFY_SSL`` / ``OCR_VERIFY_SSL`` = ``false`` — отключить проверку
  (только временная диагностика).
"""
from __future__ import annotations

import os
from typing import Union

from rd_core.tls_policy import resolve_verify


def supabase_ssl_verify() -> Union[bool, str]:
    """Вернуть значение ``verify`` для httpx-клиентов Supabase."""
    ca_cert = os.getenv("SUPABASE_CA_CERT") or os.getenv("OCR_CA_CERT")
    verify_flag = os.getenv("SUPABASE_VERIFY_SSL") or os.getenv("OCR_VERIFY_SSL")
    return resolve_verify(ca_cert, verify_flag)
