"""Менеджер состояния просмотра (zoom, scroll) для PageViewer."""

from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtWidgets import QGraphicsView


@dataclass
class ViewState:
    """Состояние просмотра."""
    transform: object  # QTransform
    zoom_factor: float
    h_scroll: int
    v_scroll: int


class ViewStateManager:
    """Менеджер для сохранения и восстановления состояния PageViewer."""

    def __init__(self, page_viewer: "QGraphicsView"):
        self.page_viewer = page_viewer

    def save(self) -> ViewState:
        """Сохранить текущее состояние просмотра."""
        return ViewState(
            transform=self.page_viewer.transform(),
            zoom_factor=self.page_viewer.zoom_factor,
            h_scroll=self.page_viewer.horizontalScrollBar().value(),
            v_scroll=self.page_viewer.verticalScrollBar().value(),
        )

    def restore(self, state: ViewState) -> None:
        """Восстановить состояние просмотра."""
        self.page_viewer.setTransform(state.transform)
        self.page_viewer.zoom_factor = state.zoom_factor
        self.page_viewer.horizontalScrollBar().setValue(state.h_scroll)
        self.page_viewer.verticalScrollBar().setValue(state.v_scroll)

    @contextmanager
    def preserve(self):
        """Context manager для автоматического сохранения и восстановления состояния.

        Использование:
            with view_state_manager.preserve():
                # операции, которые могут сбросить zoom/scroll
                self.parent._render_current_page()
        """
        state = self.save()
        try:
            yield state
        finally:
            self.restore(state)
