"""
Тест новой архитектуры UnifiedClient
Проверяет работу API proxy для Tree и Storage
"""
import sys
import os
from pathlib import Path

# Добавляем корень проекта в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

from app.unified_client import UnifiedClient


def test_health():
    """Тест 1: Проверка доступности API"""
    print("\n=== Тест 1: Health Check ===")
    client = UnifiedClient()
    
    if client.is_available():
        print("✅ API доступен")
        return True
    else:
        print("❌ API недоступен")
        return False


def test_tree_operations():
    """Тест 2: Операции с деревом проектов"""
    print("\n=== Тест 2: Tree Operations ===")
    client = UnifiedClient()
    
    try:
        # Получить корневые проекты
        roots = client.get_root_nodes()
        print(f"✅ Получено {len(roots)} корневых проектов")
        
        if roots:
            # Получить первый проект
            node = client.get_node(roots[0].id)
            print(f"✅ Получен узел: {node.name}")
            
            # Получить дочерние узлы
            children = client.get_children(roots[0].id)
            print(f"✅ Получено {len(children)} дочерних узлов")
        
        # Получить типы стадий
        stages = client.get_stage_types()
        print(f"✅ Получено {len(stages)} типов стадий")
        
        # Получить типы разделов
        sections = client.get_section_types()
        print(f"✅ Получено {len(sections)} типов разделов")
        
        # Получить категории изображений
        categories = client.get_image_categories()
        print(f"✅ Получено {len(categories)} категорий изображений")
        
        return True
        
    except Exception as e:
        print(f"❌ Ошибка Tree API: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_storage_operations():
    """Тест 3: Операции с хранилищем"""
    print("\n=== Тест 3: Storage Operations ===")
    client = UnifiedClient()
    
    try:
        # Тестовый ключ (должен не существовать)
        test_key = "test/nonexistent.txt"
        
        # Проверка существования
        exists = client.exists(test_key)
        print(f"✅ Проверка существования: {test_key} -> {exists}")
        
        # Создание тестового файла
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            f.write("Test content")
            temp_path = f.name
        
        try:
            # Загрузка файла
            test_upload_key = "test/upload_test.txt"
            if client.upload_file(temp_path, test_upload_key):
                print(f"✅ Файл загружен: {test_upload_key}")
                
                # Проверка существования после загрузки
                if client.exists(test_upload_key):
                    print(f"✅ Файл существует после загрузки")
                    
                    # Скачивание файла
                    download_path = temp_path + ".downloaded"
                    if client.download_file(test_upload_key, download_path):
                        print(f"✅ Файл скачан: {download_path}")
                        
                        # Проверка содержимого
                        with open(download_path, 'r') as f:
                            content = f.read()
                            if content == "Test content":
                                print(f"✅ Содержимое совпадает")
                            else:
                                print(f"❌ Содержимое не совпадает")
                        
                        os.unlink(download_path)
                    
                    # Удаление тестового файла
                    if client.delete_object(test_upload_key):
                        print(f"✅ Файл удален: {test_upload_key}")
                
            else:
                print(f"❌ Не удалось загрузить файл")
        
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
        
        # Тест загрузки текста
        test_text_key = "test/text_test.json"
        test_content = '{"test": "data"}'
        
        if client.upload_text(test_content, test_text_key):
            print(f"✅ Текст загружен: {test_text_key}")
            
            # Скачивание текста
            downloaded_text = client.download_text(test_text_key)
            if downloaded_text == test_content:
                print(f"✅ Текст совпадает")
            else:
                print(f"❌ Текст не совпадает")
            
            # Удаление
            client.delete_object(test_text_key)
            print(f"✅ Текстовый файл удален")
        
        return True
        
    except Exception as e:
        print(f"❌ Ошибка Storage API: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_batch_operations():
    """Тест 4: Батчевые операции"""
    print("\n=== Тест 4: Batch Operations ===")
    client = UnifiedClient()
    
    try:
        # Создание нескольких тестовых файлов
        test_keys = [f"test/batch_{i}.txt" for i in range(3)]
        
        for key in test_keys:
            client.upload_text(f"Content for {key}", key)
        
        print(f"✅ Созданы тестовые файлы: {len(test_keys)}")
        
        # Получение списка файлов
        files = client.list_files("test/batch_")
        print(f"✅ Найдено файлов: {len(files)}")
        
        # Батчевое удаление
        deleted, errors = client.delete_objects_batch(test_keys)
        print(f"✅ Удалено: {len(deleted)}, ошибок: {len(errors)}")
        
        return True
        
    except Exception as e:
        print(f"❌ Ошибка Batch API: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Запуск всех тестов"""
    print("=" * 60)
    print("Тестирование UnifiedClient (новая архитектура)")
    print("=" * 60)
    
    # Проверка переменных окружения
    base_url = os.getenv("REMOTE_OCR_BASE_URL")
    api_key = os.getenv("REMOTE_OCR_API_KEY")
    
    print(f"\nКонфигурация:")
    print(f"  REMOTE_OCR_BASE_URL: {base_url or '❌ НЕ ЗАДАН'}")
    print(f"  REMOTE_OCR_API_KEY: {'✅ ЗАДАН' if api_key else '❌ НЕ ЗАДАН'}")
    
    if not base_url:
        print("\n❌ Ошибка: REMOTE_OCR_BASE_URL не задан в .env")
        return False
    
    # Запуск тестов
    results = []
    
    results.append(("Health Check", test_health()))
    results.append(("Tree Operations", test_tree_operations()))
    results.append(("Storage Operations", test_storage_operations()))
    results.append(("Batch Operations", test_batch_operations()))
    
    # Итоги
    print("\n" + "=" * 60)
    print("Итоги тестирования:")
    print("=" * 60)
    
    for name, passed in results:
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{name:.<40} {status}")
    
    total = len(results)
    passed_count = sum(1 for _, p in results if p)
    
    print("=" * 60)
    print(f"Всего тестов: {total}, Пройдено: {passed_count}, Провалено: {total - passed_count}")
    
    if passed_count == total:
        print("\n🎉 Все тесты пройдены успешно!")
        return True
    else:
        print(f"\n⚠️  Провалено {total - passed_count} тест(ов)")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
