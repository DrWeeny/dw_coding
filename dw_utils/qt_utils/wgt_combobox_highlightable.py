from Qt import QtWidgets, QtGui, QtCore

class HighlightableComboBox(QtWidgets.QWidget):

    rightClicked = QtCore.Signal(QtWidgets.QWidget)
    currentTextChanged = QtCore.Signal(str)
    currentIndexChanged = QtCore.Signal(int)

    def __init__(self):
        super().__init__()

        self.tokens = {}
        self.proj = None

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)  # So the border has space

        self.frame = QtWidgets.QFrame()
        self.frame.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.frame.setStyleSheet("QFrame { border: 2px solid transparent; border-radius: 4px; }")

        self.combo = QtWidgets.QComboBox()
        self.combo.installEventFilter(self)
        self.combo.currentTextChanged.connect(self.currentTextChanged)
        self.combo.currentIndexChanged.connect(self.currentIndexChanged)

        frame_layout = QtWidgets.QVBoxLayout(self.frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.addWidget(self.combo)

        layout.addWidget(self.frame)

    def set_text(self, text:str):
        self.combo.setCurrentText(text)

    def currentText(self):
        return self.combo.currentText()

    def set_highlight(self, on=True, color="#90ee90"):
        if on:
            self.frame.setStyleSheet(f"""
                QFrame {{
                    border: 2px solid {color};
                    border-radius: 4px;
                    background-color: rgba(144, 238, 144, 0.1);
                }}
            """)
        else:
            self.frame.setStyleSheet("QFrame { border: 2px solid transparent; border-radius: 4px; }")

    def eventFilter(self, obj, event):
        if isinstance(obj, QtWidgets.QComboBox):
            if event.type() == QtCore.QEvent.MouseButtonPress:
                if event.button() == QtCore.Qt.RightButton:
                    self.rightClicked.emit(self)
                    return True  # Optional: swallow event
        return super().eventFilter(obj, event)

    def addItem(self, *args, **kwargs):
        return self.combo.addItem(*args, **kwargs)

    def addItems(self, *args, **kwargs):
        return self.combo.addItems(*args, **kwargs)

    def setItemData(self, *args, **kwargs):
        return self.combo.setItemData(*args, **kwargs)

    def count(self):
        return self.combo.count()

    def itemText(self, index):
        return self.combo.itemText(index)