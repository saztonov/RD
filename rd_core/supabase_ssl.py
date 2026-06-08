"""TLS verification policy for Supabase connections.

Прокси Supabase может работать с самоподписанным сертификатом.
Управление проверкой TLS через переменные окружения:

- ``SUPABASE_CA_CERT`` — путь к CA-бандлу (предпочтительный способ).
- ``SUPABASE_VERIFY_SSL=false`` — отключить проверку (самоподписанный прокси).
"""
from __future__ import annotations

import os
from typing import Union


def supabase_ssl_verify() -> Union[bool, str]:
    """Вернуть значение ``verify`` для httpx-клиентов Supabase."""
    ca_cert = os.getenv("SUPABASE_CA_CERT")
    if ca_cert:
        return ca_cert

    value = (os.getenv("SUPABASE_VERIFY_SSL", "true") or "").strip().lower()
    if value in ("0", "false", "no", "off"):
        return False
    return True
