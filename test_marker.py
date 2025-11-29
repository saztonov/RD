#!/usr/bin/env python
try:
    from marker.converters.pdf import PdfConverter
    print("✓ marker.converters.pdf импортирован")
except ImportError as e:
    print(f"✗ Ошибка импорта marker.converters: {e}")

try:
    from marker.models import create_model_dict
    print("✓ marker.models импортирован")
except ImportError as e:
    print(f"✗ Ошибка импорта marker.models: {e}")

# Попробуем альтернативные импорты
try:
    import marker
    print(f"✓ marker доступен: {marker.__file__}")
except ImportError as e:
    print(f"✗ marker не найден: {e}")

# Проверим установленные пакеты marker-pdf
import importlib.metadata
try:
    version = importlib.metadata.version('marker-pdf')
    print(f"✓ marker-pdf версия: {version}")
    
    # Посмотрим на содержимое пакета
    import importlib.resources
    print("Попытка найти модули marker-pdf...")
except Exception as e:
    print(f"Ошибка: {e}")

