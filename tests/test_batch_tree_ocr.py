import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QAbstractItemView, QTreeWidget, QTreeWidgetItem

from app.gui.main_window import MainWindow
from app.gui.project_tree.widget import ProjectTreeWidget
from app.tree_client import NodeType, TreeNode


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _node(node_id: str, name: str, node_type: NodeType) -> TreeNode:
    attrs = {}
    if node_type == NodeType.DOCUMENT:
        attrs["r2_key"] = f"tree_docs/root/{name}.pdf"
    return TreeNode(
        id=node_id,
        parent_id=None,
        node_type=node_type,
        name=name,
        attributes=attrs,
    )


def test_get_selected_document_nodes_filters_and_sorts_tree_selection(qapp):
    tree = QTreeWidget()
    tree.setSelectionMode(QAbstractItemView.ExtendedSelection)

    folder_item = QTreeWidgetItem(["Folder"])
    folder_item.setData(0, Qt.UserRole, _node("folder-1", "Folder", NodeType.FOLDER))
    tree.addTopLevelItem(folder_item)

    child_b = QTreeWidgetItem(["Doc B"])
    child_b.setData(0, Qt.UserRole, _node("doc-b", "Doc B", NodeType.DOCUMENT))
    folder_item.addChild(child_b)

    child_a = QTreeWidgetItem(["Doc A"])
    child_a.setData(0, Qt.UserRole, _node("doc-a", "Doc A", NodeType.DOCUMENT))
    folder_item.addChild(child_a)

    root_doc = QTreeWidgetItem(["Root Doc"])
    root_doc.setData(0, Qt.UserRole, _node("doc-root", "Root Doc", NodeType.DOCUMENT))
    tree.addTopLevelItem(root_doc)

    folder_item.setSelected(True)
    child_a.setSelected(True)
    root_doc.setSelected(True)
    child_b.setSelected(True)

    widget = SimpleNamespace(tree=tree)
    widget._tree_item_order_key = lambda item: ProjectTreeWidget._tree_item_order_key(
        widget, item
    )

    nodes = ProjectTreeWidget.get_selected_document_nodes(widget)

    assert [node.id for node in nodes] == ["doc-b", "doc-a", "doc-root"]


def test_send_to_remote_ocr_prefers_tree_selection():
    calls = []
    selected_nodes = [SimpleNamespace(id="node-1")]

    controller = SimpleNamespace(
        create_job=lambda: calls.append(("single", None)),
        create_jobs_for_tree_selection=lambda nodes: calls.append(("batch", nodes)),
    )
    main_window = SimpleNamespace(
        remote_ocr_panel=SimpleNamespace(
            show=lambda: calls.append(("show", None)),
            controller=controller,
        ),
        project_tree_widget=SimpleNamespace(
            get_selected_document_nodes=lambda: selected_nodes
        ),
    )

    MainWindow._send_to_remote_ocr(main_window)

    assert calls == [("show", None), ("batch", selected_nodes)]


def test_send_to_remote_ocr_falls_back_to_single_job():
    calls = []

    controller = SimpleNamespace(
        create_job=lambda: calls.append(("single", None)),
        create_jobs_for_tree_selection=lambda nodes: calls.append(("batch", nodes)),
    )
    main_window = SimpleNamespace(
        remote_ocr_panel=SimpleNamespace(
            show=lambda: calls.append(("show", None)),
            controller=controller,
        ),
        project_tree_widget=SimpleNamespace(get_selected_document_nodes=lambda: []),
    )

    MainWindow._send_to_remote_ocr(main_window)

    assert calls == [("show", None), ("single", None)]
