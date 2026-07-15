"""File hierarchy dialog: inspect what a file node reads.

Summary:
    Shows the transform hierarchy of an .abc/.ma/.mb via file_probe
    (PyAlembic walk for abc, cached). Double-click an item to send its
    short name back to the caller (filter authoring).

Classes:
    SceneTreeDialog

Author:
    DrWeeny
"""

from PySide6 import QtWidgets, QtCore, QtGui

from CfxForge.ui import file_probe


class SceneTreeDialog(QtWidgets.QDialog):

    picked = QtCore.Signal(str)

    def __init__(self, file_path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f'Hierarchy - {file_path}')
        self.resize(460, 520)
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderLabels(['node', 'type', 'verts'])
        self.tree.setColumnWidth(0, 240)
        self.status = QtWidgets.QLabel('')
        self.status.setWordWrap(True)
        hint = QtWidgets.QLabel('double-click = use as filter pattern')
        hint.setStyleSheet('color: #888888;')
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.tree, stretch=1)
        layout.addWidget(hint)
        layout.addWidget(self.status)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        self._populate(file_path)

    def _populate(self, file_path: str):
        QtWidgets.QApplication.setOverrideCursor(
            QtCore.Qt.CursorShape.WaitCursor)
        try:
            data = file_probe.probe(file_path)
        except Exception as e:
            self.status.setText(str(e))
            return
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        by_path = {}
        for entry in data.get('entries', []):
            parts = entry['path'].strip('/').split('/')
            parent_path = '/'.join(parts[:-1])
            parent_item = by_path.get(parent_path,
                                      self.tree.invisibleRootItem())
            item = QtWidgets.QTreeWidgetItem(
                parent_item,
                [parts[-1], entry.get('type', ''),
                 str(entry.get('verts', ''))])
            by_path['/'.join(parts)] = item
        self.tree.expandAll()
        self.status.setText(f"{len(data.get('entries', []))} node(s)")

    def _on_double_click(self, item, column):
        self.picked.emit(item.text(0))