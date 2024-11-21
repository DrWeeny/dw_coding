from PySide6 import QtWidgets, QtCore

class TreeBuildProgress(QtWidgets.QDialog):
    """Custom progress dialog for tree building."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Building Tree")
        self.setModal(True)
        self._setup_ui()

    def _setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        # Progress bar
        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 100)
        layout.addWidget(self.progress)

        # Status label
        self.status_label = QtWidgets.QLabel()
        self.status_label.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(self.status_label)

        # Detailed status
        self.detail_text = QtWidgets.QTextEdit()
        self.detail_text.setReadOnly(True)
        self.detail_text.setMaximumHeight(100)
        layout.addWidget(self.detail_text)

        # Cancel button
        self.cancel_btn = QtWidgets.QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        layout.addWidget(self.cancel_btn)

    def update_progress(self, value: int, status: str):
        """Update progress bar and status."""
        self.progress.setValue(value)
        self.status_label.setText(status)

    def add_detail(self, text: str):
        """Add detailed status message."""
        self.detail_text.append(text)
        # Auto-scroll to bottom
        scrollbar = self.detail_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())