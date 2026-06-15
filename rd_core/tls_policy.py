"""Единая политика TLS-проверки для HTTP-клиентов (requests / httpx).

Прокси ``pro3.fvds.ru`` использует собственный CA. Чтобы доверять прокси и при
этом не ломать прямые соединения к публичным хостам (datalab.com, R2 и т.д.),
кастомный CA объединяется с системным бандлом (certifi) в один файл.

Env-переменные:
- ``*_CA_CERT`` — путь к CA-сертификату прокси (предпочтительно).
- ``*_VERIFY_SSL=false`` — отключить проверку (только для временной диагностики).
"""
from __future__ import annotations

import functools
import os
import tempfile
from pathlib import Path
from typing import Optional, Union

VerifyType = Union[bool, str]

_FALSEY = ("0", "false", "no", "off")

# Корень проекта (родитель пакета rd_core) — для поиска certs/ на десктопе.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _resolve_ca_path(ca_cert: str) -> Optional[str]:
    """Найти существующий файл CA.

    В контейнере путь ``/certs/proxy-ca.pem`` существует как есть. На десктопе
    (Windows) тот же путь не существует — ищем относительно cwd и корня проекта,
    чтобы один и тот же ``.env`` работал в обоих окружениях.
    """
    rel = ca_cert.lstrip("/\\")
    base = os.path.basename(ca_cert)
    candidates = [
        ca_cert,
        os.path.join(os.getcwd(), rel),
        str(_PROJECT_ROOT / rel),
        os.path.join(os.getcwd(), "certs", base),
        str(_PROJECT_ROOT / "certs" / base),
    ]
    for path in candidates:
        if path and os.path.exists(path):
            return path
    return None


@functools.lru_cache(maxsize=8)
def combined_ca_bundle(ca_cert: str) -> str:
    """Создать объединённый CA-бандл (certifi + кастомный CA) и вернуть путь.

    При ошибке (нет certifi / нет доступа) возвращает исходный ``ca_cert``.
    """
    try:
        import certifi

        fd, path = tempfile.mkstemp(suffix="-ca-bundle.pem", prefix="rd-")
        with os.fdopen(fd, "wb") as out:
            with open(certifi.where(), "rb") as sys_ca:
                out.write(sys_ca.read())
            out.write(b"\n")
            with open(ca_cert, "rb") as proxy_ca:
                out.write(proxy_ca.read())
        return path
    except Exception:
        return ca_cert


def resolve_verify(ca_cert: Optional[str], verify_flag: Optional[str]) -> VerifyType:
    """Вычислить значение ``verify`` для requests/httpx.

    Приоритет:
    1. ``ca_cert`` задан и файл существует → объединённый бандл (certifi + CA).
    2. ``ca_cert`` задан, но файла нет → вернуть путь как есть (явная ошибка TLS).
    3. ``verify_flag`` в (0/false/no/off) → ``False`` (аварийный обход).
    4. иначе → ``True`` (системная проверка).
    """
    if ca_cert:
        resolved = _resolve_ca_path(ca_cert)
        if resolved:
            return combined_ca_bundle(os.path.abspath(resolved))
        return ca_cert
    if verify_flag is not None and verify_flag.strip().lower() in _FALSEY:
        return False
    return True
