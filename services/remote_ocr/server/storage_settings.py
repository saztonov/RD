"""Операции с настройками задач OCR"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional, Dict, Any, List

from .storage_client import get_client
from .storage_models import JobSettings

logger = logging.getLogger(__name__)

# Кэш категорий изображений (время жизни ~ 5 минут)
_image_categories_cache: Optional[List[Dict[str, Any]]] = None
_image_categories_cache_time: Optional[datetime] = None


def get_image_categories() -> List[Dict[str, Any]]:
    """Получить все категории изображений (с кэшированием)"""
    global _image_categories_cache, _image_categories_cache_time
    
    # Проверяем кэш (5 минут)
    if _image_categories_cache is not None and _image_categories_cache_time is not None:
        age = (datetime.utcnow() - _image_categories_cache_time).total_seconds()
        if age < 300:  # 5 минут
            return _image_categories_cache
    
    try:
        client = get_client()
        result = client.table("image_categories").select("*").order("sort_order").execute()
        _image_categories_cache = result.data or []
        _image_categories_cache_time = datetime.utcnow()
        logger.info(f"Загружено {len(_image_categories_cache)} категорий изображений")
        return _image_categories_cache
    except Exception as e:
        logger.warning(f"Ошибка загрузки категорий: {e}")
        return []


def get_image_category_by_id(category_id: str) -> Optional[Dict[str, Any]]:
    """Получить категорию по ID"""
    categories = get_image_categories()
    for cat in categories:
        if cat.get("id") == category_id:
            return cat
    return None


def get_image_category_by_code(code: str) -> Optional[Dict[str, Any]]:
    """Получить категорию по коду"""
    categories = get_image_categories()
    for cat in categories:
        if cat.get("code") == code:
            return cat
    return None


def get_default_image_category() -> Optional[Dict[str, Any]]:
    """Получить категорию по умолчанию (code='default' или is_default=True)"""
    categories = get_image_categories()
    # Приоритет: категория с code='default'
    for cat in categories:
        if cat.get("code") == "default":
            return cat
    # Fallback: категория с is_default=True
    for cat in categories:
        if cat.get("is_default"):
            return cat
    # Fallback: первая категория
    return categories[0] if categories else None


def get_category_prompt(category_id: Optional[str] = None, category_code: Optional[str] = None) -> Optional[Dict[str, str]]:
    """
    Получить промпт категории по ID или коду.
    Возвращает {"system": "...", "user": "..."}
    """
    category = None
    
    if category_id:
        category = get_image_category_by_id(category_id)
    elif category_code:
        category = get_image_category_by_code(category_code)
    
    if not category:
        category = get_default_image_category()
    
    if category:
        return {
            "system": category.get("system_prompt", ""),
            "user": category.get("user_prompt", "")
        }
    
    return None


def save_job_settings(
    job_id: str,
    text_model: str = "",
    table_model: str = "",
    image_model: str = ""
) -> JobSettings:
    """Сохранить/обновить настройки задачи"""
    now = datetime.utcnow().isoformat()
    client = get_client()
    
    # Upsert: вставить или обновить
    client.table("job_settings").upsert({
        "job_id": job_id,
        "text_model": text_model,
        "table_model": table_model,
        "image_model": image_model,
        "updated_at": now
    }, on_conflict="job_id").execute()
    
    return JobSettings(
        job_id=job_id,
        text_model=text_model,
        table_model=table_model,
        image_model=image_model
    )


def get_job_settings(job_id: str) -> Optional[JobSettings]:
    """Получить настройки задачи"""
    client = get_client()
    result = client.table("job_settings").select("*").eq("job_id", job_id).execute()
    
    if not result.data:
        return None
    
    row = result.data[0]
    return JobSettings(
        job_id=row["job_id"],
        text_model=row.get("text_model", ""),
        table_model=row.get("table_model", ""),
        image_model=row.get("image_model", "")
    )

