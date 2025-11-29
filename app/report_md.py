"""
Генерация Markdown-отчётов
Сбор результатов OCR в один MD-файл по каждой категории (text/table/image)
"""

from pathlib import Path
from typing import List
from app.models import Document, BlockType


class MarkdownReporter:
    """
    Генератор Markdown-отчётов по результатам OCR
    """
    
    def __init__(self, output_dir: str):
        """
        Args:
            output_dir: директория для сохранения MD-файлов
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def generate_reports(self, document: Document) -> bool:
        """
        Генерировать отчёты для всех категорий блоков
        
        Args:
            document: документ с разметкой и результатами OCR
        
        Returns:
            True если успешно сгенерировано
        """
        try:
            # Группируем блоки по типам
            blocks_by_type = {block_type: [] for block_type in BlockType}
            
            for page in document.pages:
                for block in page.blocks:
                    blocks_by_type[block.block_type].append({
                        'page': page.page_number + 1,
                        'block': block
                    })
            
            # Генерируем отчёт для каждого типа
            for block_type, blocks in blocks_by_type.items():
                if blocks:
                    self._generate_report_for_type(block_type, blocks)
            
            return True
        except Exception as e:
            print(f"Ошибка генерации отчётов: {e}")
            return False
    
    def _generate_report_for_type(self, block_type: BlockType, blocks: List[dict]):
        """
        Генерировать отчёт для одного типа блоков
        
        Args:
            block_type: тип блоков
            blocks: список словарей с информацией о блоках
        """
        filename = f"{block_type.value}_report.md"
        filepath = self.output_dir / filename
        
        with open(filepath, 'w', encoding='utf-8') as f:
            # Заголовок
            f.write(f"# {block_type.value.upper()} Report\n\n")
            f.write(f"Total blocks: {len(blocks)}\n\n")
            f.write("---\n\n")
            
            # Блоки
            for idx, item in enumerate(blocks, 1):
                page_num = item['page']
                block = item['block']
                
                f.write(f"## Block {idx} (Page {page_num})\n\n")
                
                if block.description:
                    f.write(f"**Description:** {block.description}\n\n")
                
                f.write(f"**Coordinates:** x={block.x}, y={block.y}, "
                       f"w={block.width}, h={block.height}\n\n")
                
                if block.ocr_text:
                    f.write(f"**OCR Result:**\n\n")
                    f.write("```\n")
                    f.write(block.ocr_text)
                    f.write("\n```\n\n")
                else:
                    f.write("*No OCR result*\n\n")
                
                # Ссылка на изображение (относительный путь)
                image_path = f"{block_type.value}/src/page_{page_num}_block_{idx}.png"
                f.write(f"![Block Image]({image_path})\n\n")
                f.write("---\n\n")

