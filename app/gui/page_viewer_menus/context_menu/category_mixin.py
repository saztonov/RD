"""Миксин для работы с категориями в контекстном меню"""
import logging

logger = logging.getLogger(__name__)


class CategoryMixin:
    """Миксин для кэширования и работы с категориями изображений"""

    _image_categories_cache = None
    _tree_client = None

    def _get_image_categories(self):
        """Получить категории изображений из кэша или Supabase"""
        if CategoryMixin._image_categories_cache is not None:
            return CategoryMixin._image_categories_cache

        try:
            if CategoryMixin._tree_client is None:
                from app.tree_client import TreeClient

                CategoryMixin._tree_client = TreeClient()

            if CategoryMixin._tree_client.is_available():
                CategoryMixin._image_categories_cache = (
                    CategoryMixin._tree_client.get_image_categories()
                )
            else:
                CategoryMixin._image_categories_cache = []
        except Exception as e:
            logger.warning(f"Не удалось загрузить категории: {e}")
            CategoryMixin._image_categories_cache = []

        return CategoryMixin._image_categories_cache

    @classmethod
    def invalidate_categories_cache(cls):
        """Сбросить кэш категорий"""
        cls._image_categories_cache = None
