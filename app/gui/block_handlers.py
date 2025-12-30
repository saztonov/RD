"""
Миксин для обработки блоков и событий
Комбинированный миксин из модулей: block_crud, block_groups, block_events
"""

from app.gui.block_crud import BlockCRUDMixin
from app.gui.block_groups import BlockGroupsMixin
from app.gui.block_events import BlockEventsMixin


class BlockHandlersMixin(BlockCRUDMixin, BlockGroupsMixin, BlockEventsMixin):
    """Комбинированный миксин для обработки блоков"""
    pass
