"""
Тестовый скрипт для проверки API
"""
import httpx
import json

url = "https://louvred-madie-gigglier.ngrok-free.dev/api/v1/segment"

# Создаем минимальный PDF для теста
pdf_content = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\nxref\n0 4\n0000000000 65535 f\n0000000009 00000 n\n0000000058 00000 n\n0000000115 00000 n\ntrailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n190\n%%EOF"

files = {"file": ("test.pdf", pdf_content, "application/pdf")}

print("Отправка запроса...")
with httpx.Client(timeout=60.0) as client:
    response = client.post(url, files=files)
    print(f"Status: {response.status_code}")
    print(f"Headers: {response.headers}")
    
    result = response.json()
    print(f"\nОтвет (форматированный):")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    
    print(f"\nКлючи верхнего уровня: {list(result.keys())}")
    if 'pages' in result:
        print(f"Количество страниц: {len(result['pages'])}")
        if result['pages']:
            print(f"Ключи первой страницы: {list(result['pages'][0].keys())}")


