import logging
logging.basicConfig(level=logging.DEBUG)

from pathlib import Path
from services.remote_ocr.server.ocr_result_merger import merge_ocr_results
import json

ann_path = Path(r'C:\Users\svarovsky\Desktop\PROJECTS\cache\17fb1ec8-13aa-4077-9d75-e796930c0b82\165-1-2024-РД-АР6.1_annotation.json')
html_path = Path(r'C:\Users\svarovsky\Desktop\PROJECTS\cache\17fb1ec8-13aa-4077-9d75-e796930c0b82\165-1-2024-РД-АР6.1_ocr.html')
out_path = Path(r'C:\Users\svarovsky\Desktop\PROJECTS\cache\17fb1ec8-13aa-4077-9d75-e796930c0b82\165-1-2024-РД-АР6.1_result_fixed.json')

result = merge_ocr_results(ann_path, html_path, out_path, project_name='17fb1ec8-13aa-4077-9d75-e796930c0b82')
print(f'\nSuccess: {result}')

# Проверим статистику
with open(out_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

total = 0
found = 0
methods = {}
for page in data['pages']:
    for blk in page['blocks']:
        total += 1
        ocr_html = blk.get('ocr_html', '')
        meta = blk.get('ocr_meta', {})
        method = tuple(meta.get('method', []))
        methods[method] = methods.get(method, 0) + 1
        if ocr_html:
            found += 1

print(f"\nTotal: {total}, Found: {found}, Missing: {total - found}")
print(f"Methods: {methods}")
