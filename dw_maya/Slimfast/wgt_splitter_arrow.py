try:
    from PySide6 import QtCore, QtGui, QtWidgets, QtPositioning
    from PySide6.QtCore import Qt
    from shiboken6 import wrapInstance
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets
    from PySide2.QtCore import Qt
    from shiboken2 import wrapInstance

# PySide6 nests style enums; the flat name still resolves on both bindings,
# with the nested form as a fallback.
_PE_ARROW_RIGHT = getattr(QtWidgets.QStyle, "PE_IndicatorArrowRight", None)
if _PE_ARROW_RIGHT is None:
    _PE_ARROW_RIGHT = QtWidgets.QStyle.PrimitiveElement.PE_IndicatorArrowRight


class _ArrowSplitterHandle(QtWidgets.QSplitterHandle):
    """Wide splitter handle drawing a source->target arrow instead of dots.

    Uses the style's native arrow primitive so it matches Maya's theme
    without needing an icon file; the row of grip dots is not drawn at all
    (we skip the default paintEvent).
    """

    _ARROW_SIZE = 12

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QtGui.QPainter(self)
        if self.underMouse():
            painter.fillRect(self.rect(), QtGui.QColor(255, 255, 255, 25))
        opt = QtWidgets.QStyleOption()
        opt.initFrom(self)
        center = self.rect().center()
        half = self._ARROW_SIZE // 2
        opt.rect = QtCore.QRect(center.x() - half,
                                center.y() - half,
                                self._ARROW_SIZE,
                                self._ARROW_SIZE)
        self.style().drawPrimitive(_PE_ARROW_RIGHT, opt, painter, self)


class ArrowSplitter(QtWidgets.QSplitter):
    """QSplitter producing _ArrowSplitterHandle handles."""

    def createHandle(self) -> QtWidgets.QSplitterHandle:
        return _ArrowSplitterHandle(self.orientation(), self)