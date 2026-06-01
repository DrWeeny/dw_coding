try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:
    # Fallback for older Maya versions shipping PySide2
    from PySide2 import QtCore, QtGui, QtWidgets

from typing import Optional

# ---------------------------------------------------------------------------
# Reusable collapsible section widget
# ---------------------------------------------------------------------------

class CollapsibleSection(QtWidgets.QWidget):
    """A titled toggle button that shows/hides a content widget.

    Args:
        title:    Label shown on the toggle button.
        parent:   Optional parent widget.

    Example::

        section = CollapsibleSection('▶  Advanced ops')
        section.content_layout.addWidget(some_widget)
    """

    def __init__(self, title: str = '', parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)

        self._toggle_btn = QtWidgets.QToolButton()
        self._toggle_btn.setStyleSheet(
            'QToolButton { border: none; color: #aaaaaa; font-weight: bold; '
            'text-align: left; padding: 2px 4px; }'
            'QToolButton:hover { color: #dddddd; }'
        )
        self._toggle_btn.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self._toggle_btn.setArrowType(QtCore.Qt.RightArrow)
        self._toggle_btn.setText(title)
        self._toggle_btn.setCheckable(True)
        self._toggle_btn.setChecked(False)

        # Horizontal rule beside the button
        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.HLine)
        line.setFrameShadow(QtWidgets.QFrame.Sunken)
        line.setStyleSheet('color: #555555;')

        header = QtWidgets.QHBoxLayout()
        header.setContentsMargins(0, 2, 0, 2)
        header.setSpacing(4)
        header.addWidget(self._toggle_btn)
        header.addWidget(line, stretch=1)

        self._content = QtWidgets.QWidget()
        self._content.setVisible(False)
        self.content_layout = QtWidgets.QVBoxLayout(self._content)
        self.content_layout.setContentsMargins(8, 4, 0, 4)
        self.content_layout.setSpacing(4)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addLayout(header)
        root.addWidget(self._content)

        self._toggle_btn.toggled.connect(self._on_toggled)

    def _on_toggled(self, checked: bool) -> None:
        self._toggle_btn.setArrowType(QtCore.Qt.DownArrow if checked else QtCore.Qt.RightArrow)
        self._content.setVisible(checked)