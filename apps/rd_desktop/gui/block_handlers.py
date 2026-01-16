"""
Миксин для обработки блоков и событий
Комбинированный миксин из модулей: block_crud, block_groups, block_events
"""

from apps.rd_desktop.gui.blocks import BlockCRUDMixin
from apps.rd_desktop.gui.block_events import BlockEventsMixin
from apps.rd_desktop.gui.block_groups import BlockGroupsMixin


class BlockHandlersMixin(BlockCRUDMixin, BlockGroupsMixin, BlockEventsMixin):
    """Комбинированный миксин для обработки блоков"""

    pass
