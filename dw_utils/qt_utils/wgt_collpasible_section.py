from Qt import QtWidgets, QtCore

class CollapsibleSection(QtWidgets.QWidget):
    """
    used to click on the section and display new widgets
    """
    def __init__(self, title="Section Name", has_cb=False, parent=None):
        super().__init__(parent)

        self.has_cb = has_cb

        # Header layout
        self.header_widget = QtWidgets.QWidget()
        header_layout = QtWidgets.QHBoxLayout(self.header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)

        # Toggle button (expands/collapses)
        self.toggle_button = QtWidgets.QToolButton(text=title, checkable=True, checked=False)
        self.toggle_button.setStyleSheet("QToolButton { border: none; }")
        self.toggle_button.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.toggle_button.setArrowType(QtCore.Qt.RightArrow)
        self.toggle_button.clicked.connect(self.toggle)

        header_layout.addWidget(self.toggle_button)

        # Optional checkbox (e.g. to "Enable Task")
        self.checkbox = None
        if has_cb:
            self.checkbox = QtWidgets.QCheckBox()
            self.checkbox.setChecked(True)
            self.checkbox.setToolTip("Enable")
            header_layout.addWidget(self.checkbox)

        # Content area (initially hidden)
        self.content_area = QtWidgets.QWidget()
        self.content_area.setVisible(False)
        self.content_layout = QtWidgets.QVBoxLayout(self.content_area)
        self.content_layout.setContentsMargins(0, 0, 0, 0)

        # Main layout
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self.header_widget)
        main_layout.addWidget(self.content_area)

    def toggle(self):
        checked = self.toggle_button.isChecked()
        self.content_area.setVisible(checked)
        self.toggle_button.setArrowType(QtCore.Qt.DownArrow if checked else QtCore.Qt.RightArrow)

        # self.animation = QtCore.QPropertyAnimation(self.content_area, b"maximumHeight")
        # self.animation.setDuration(200)
        # self.animation.setStartValue(0)
        # self.animation.setEndValue(300)  # Adjust depending on content
        # self.animation.start()

    def add_widget(self, widget, insert_id:int=None):
        if isinstance(insert_id, int):
            self.content_layout.insertWidget(insert_id, widget)
        else:
            self.content_layout.addWidget(widget)

    def is_enabled(self):
        """
        Returns if the tab should be processed
        """
        return self.checkbox.isChecked() if self.checkbox else True


class CollapsibleBlueSection(CollapsibleSection):
    """
    In our data, each take is a collapsible item.
    The header will have a blue background, and the content will have a light gray background.
    """
    def __init__(self, title="Take 1", has_cb=False, parent=None):
        super().__init__(title, has_cb, parent)

        # Set the toggle button (header) to span the full width
        self.toggle_button.setStyleSheet("""
            QToolButton {
                border: none;
                background-color: #3498db;  /* Blue background for the header */
                color: white;
                padding: 10px;
                font-weight: bold;
                text-align: left;
            }
            QToolButton::checked {
                background-color: #2980b9;  /* Darker blue when expanded */
            }
        """)

        # Ensure that the button takes up the full width available in the layout
        self.toggle_button.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)

        # Optional: If you want to make the layout even more responsive, you could use stretch factors
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
