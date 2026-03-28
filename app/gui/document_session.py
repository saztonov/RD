"""Управление временными сессиями документов из дерева проектов."""
import logging
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class DocumentSession:
    """Runtime-сессия открытого документа из дерева."""

    session_id: str
    node_id: str
    r2_key: str
    temp_dir: Path
    pdf_path: Path
    is_tree_temp: bool = True

    def get_sibling_path(self, suffix: str) -> Path:
        """Путь к файлу рядом с PDF (_result.json, _ocr.html и т.д.)."""
        return self.pdf_path.parent / f"{self.pdf_path.stem}{suffix}"

    def cleanup(self):
        """Idempotent удаление temp_dir."""
        if self.is_tree_temp and self.temp_dir and self.temp_dir.exists():
            try:
                shutil.rmtree(self.temp_dir, ignore_errors=True)
                logger.debug(f"Temp session cleaned up: {self.temp_dir}")
            except Exception as e:
                logger.warning(f"Failed to cleanup temp session: {e}")


class DocumentSessionManager:
    """Управление текущей сессией документа."""

    def __init__(self):
        self._current: Optional[DocumentSession] = None

    def create_session(self, node_id: str, r2_key: str) -> DocumentSession:
        """Закрыть предыдущую сессию, создать новую temp-папку."""
        self.close_current()

        temp_dir = Path(tempfile.mkdtemp(prefix="rd_doc_"))
        rel = r2_key[len("tree_docs/"):] if r2_key.startswith("tree_docs/") else r2_key
        pdf_path = temp_dir / rel
        pdf_path.parent.mkdir(parents=True, exist_ok=True)

        session = DocumentSession(
            session_id=str(uuid.uuid4()),
            node_id=node_id,
            r2_key=r2_key,
            temp_dir=temp_dir,
            pdf_path=pdf_path,
            is_tree_temp=True,
        )
        self._current = session
        logger.info(f"Document session created: {session.session_id} -> {temp_dir}")
        return session

    def close_current(self):
        """Cleanup текущей сессии."""
        if self._current:
            self._current.cleanup()
            self._current = None

    @property
    def current(self) -> Optional[DocumentSession]:
        return self._current
