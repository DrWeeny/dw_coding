"""
This module contains several dialog classes that provide confirmation and input forms for various tasks in a graphical user interface (GUI) application. These dialogs are implemented using the PySide2 library and serve as part of a larger UI system for managing categories, templates, and deletion processes. Each dialog offers different user interactions, including creating a new category, confirming template details, and deleting categories or files.

Classes:
    - NewCategoryDialog: A dialog for creating a new category name. It validates the name to ensure it only contains letters and underscores. It provides a simple input field and a model to auto-complete based on predefined category names.
    - TemplateConfirmationDialog: A dialog for confirming the details of a template, including category name, version, a comment field, and a weblink input. It also provides a display of the number of selected nodes in the environment.
    - DeleteConfirmationDialog: A dialog for confirming the deletion of a category or template file. It shows information about the selected category and filename (if applicable), and allows the user to confirm or cancel the deletion.

The dialogs include basic validation for user input, such as ensuring only valid category names are accepted in the `NewCategoryDialog`, and providing an overview of the selected category and version in the `TemplateConfirmationDialog`. The `DeleteConfirmationDialog` ensures that the user confirms their intention to delete items.

todo:
    - Add to TemplateConfirmationDialog a field to change the default name of the template (default is {category}_template)

author: drweeny
"""

from PySide2 import QtCore, QtGui, QtWidgets
import re
from typing import Optional
from .template_cmds import get_iter
from.otl_io import get_hou_selection_length

class NewCategoryDialog(QtWidgets.QDialog):
    """
    Dialog for entering a new category name with validation.

    Ensures the category name contains only letters and underscores.
    The category name is validated as the user types it.

    Attributes:
        category_name (str): The valid category name entered by the user.
    """

    def __init__(self, parent=None):
        super(NewCategoryDialog, self).__init__(parent)

        self.setWindowTitle("Category Naming")

        # Create layout and widgets
        self.layout = QtWidgets.QVBoxLayout(self)
        self.label = QtWidgets.QLabel("Enter the new category name:")
        self.layout.addWidget(self.label)

        self.initial_list = ["cfx", "cloth", "hair", "fur", "feather",
                             "prop", "muscle", "character",
                             "chara", "vehicle", "animal", "creature", "water",
                             "underwater"]

        # Define the second list for completions after '_'
        self.second_list = ["template", "rig", "model", "asset", "shot", "sequence"]

        self.model = QtCore.QStringListModel(self.initial_list)
        self.completer = QtWidgets.QCompleter(self.model)
        self.completer.setCaseSensitivity(QtCore.Qt.CaseInsensitive)

        self.category_name_edit = QtWidgets.QLineEdit(self)
        self.category_name_edit.setPlaceholderText("Only letters and underscores allowed")
        self.category_name_edit.setCompleter(self.completer)

        # Create the regex for only letters and underscores
        regex = QtCore.QRegExp("[a-zA-Z_]+")  # Matches only letters (A-Z, a-z) and underscores (_)
        validator = QtGui.QRegExpValidator(regex, self.category_name_edit)

        # Apply the validator to the QLineEdit
        self.category_name_edit.setValidator(validator)

        # Monitor the input to switch models when '_' is typed
        self.category_name_edit.textChanged.connect(self.on_text_changed)

        self.layout.addWidget(self.category_name_edit)

        self.button_box = QtWidgets.QHBoxLayout()
        self.ok_button = QtWidgets.QPushButton("OK", self)
        self.cancel_button = QtWidgets.QPushButton("Cancel", self)

        self.button_box.addWidget(self.ok_button)
        self.button_box.addWidget(self.cancel_button)
        self.layout.addLayout(self.button_box)

        self.ok_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)

        # Store the category name after validation
        self.category_name = ""

    def on_text_changed(self):
        """Monitor text changes to switch completer lists based on underscore ('_').
        todo switch doesnt work"""
        if '_' in self.category_name_edit.text():
            # Switch to the second list if '_' is typed
            self.model.setStringList(self.second_list)
        else:
            # Revert back to the initial list if '_' is not typed
            self.model.setStringList(self.initial_list)

    def accept(self):
        """Validate the category name and accept the dialog."""
        name = self.category_name_edit.text()
        if re.match(r'^[A-Za-z_]+$', name):
            self.category_name = name
            super().accept()  # Accept the dialog
        else:
            QtWidgets.QMessageBox.warning(self, "Invalid Name",
                                          "Category name must only contain letters and underscores.")

    def reject(self):
        super().reject()  # Close the dialog without accepting


class TemplateConfirmationDialog(QtWidgets.QDialog):
    """
    Dialog for confirming the template details, including category, version, comment, and web link.

    Attributes:
        category_name (str): The selected category name.
        version (int): The version number.
    """
    def __init__(self, parent, category_name, version, model_category):
        super(TemplateConfirmationDialog, self).__init__(parent)
        self.setWindowTitle("Confirm Template Details")

        # Layout for the dialog
        layout = QtWidgets.QFormLayout(self)

        # Create the QComboBox
        self.category_name = category_name
        self.combo_box = QtWidgets.QComboBox(self)
        self.combo_box.setModel(model_category)
        layout.addRow(self.combo_box)
        self.combo_box.setCurrentText(category_name)

        # Set the name of the template :
        self.lb_template_name = QtWidgets.QLabel("Template Name:", self)
        self.le_template_name = QtWidgets.QLineEdit(category_name, self)
        layout.addRow(self.lb_template_name ,self.le_template_name)

        # Add label and field for version
        self.version = version
        self.version_label = QtWidgets.QLabel(f"Version: v{version:03}", self)
        layout.addRow(self.version_label)

        # Add lineedit for a website
        self.weblink_le = QtWidgets.QLineEdit(self)
        self.weblink_le.setPlaceholderText("weblink:")
        layout.addRow(self.weblink_le)

        # Add label and field for comment
        self.comment_label = QtWidgets.QLabel("Comment:", self)
        self.comment_line_edit = QtWidgets.QTextEdit(self)
        self.comment_line_edit.setFixedSize(587, 181)
        self.comment_line_edit.setPlaceholderText("(Optionnal) Enter your comment here...")
        layout.addRow(self.comment_label, self.comment_line_edit)

        # label giving number of nodes selected :
        self.non = QtWidgets.QLabel(f"Number of Nodes: {self.number_of_nodes()}", self)
        layout.addRow(self.non)

        # Add OK and Cancel buttons
        self.ok_button = QtWidgets.QPushButton("OK", self)
        self.cancel_button = QtWidgets.QPushButton("Cancel", self)

        button_layout = QtWidgets.QHBoxLayout()
        button_layout.addWidget(self.ok_button)
        button_layout.addWidget(self.cancel_button)

        layout.addRow(button_layout)

        # Connect buttons
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)

        # You can connect to the selection change if needed
        self.combo_box.currentIndexChanged.connect(self.on_category_selected)

    def number_of_nodes(self)->int:
        """Return the number of selected nodes in Houdini."""
        return get_hou_selection_length()

    def result(self)-> tuple:
        """
        Return the selected template details including category, version, comment, and web link.
        """
        category_name = self.combo_box.currentText()
        version = self.version
        comment = self.comment_line_edit.toPlainText()
        weblink = self.weblink_le.text()
        template_name = self.le_template_name.text()
        return category_name, version, comment, weblink, template_name

    def on_category_selected(self, index: int):
        """
        Callback when a category is selected in the combo box.
        """
        category_name = self.combo_box.currentText()
        # if name of the template was default, lets change also that
        if category_name != self.category_name and self.le_template_name.text() == f"{self.category_name}_template":
            self.le_template_name.setText(f"{category_name}_template")
            self.category_name = category_name

        version = get_iter(category_name)
        self.version_label.setText(f"Version: {version:03}")

class DeleteConfirmationDialog(QtWidgets.QDialog):
    """
    Dialog for confirming the deletion of a category or template file.

    Attributes:
        category (str): The category being deleted.
        filename (Optional[str]): The filename being deleted, if applicable.
    """
    def __init__(self, parent, category, filename=None, approved=None):
        super(DeleteConfirmationDialog, self).__init__(parent)


        # Set up the dialog
        self.setWindowTitle("Confirm Deletion")

        # Create labels to display the category and filename
        self.category_label = QtWidgets.QLabel(f"Category: {category}")
        if filename:
            self.filename_label = QtWidgets.QLabel(f"File: {filename}")
            self.approval_label = QtWidgets.QLabel("Are you sure you want to delete this file?")
        else:
            self.approval_label = QtWidgets.QLabel("Are you sure you want to delete this category?")

        # Create the Confirm and Cancel buttons
        self.confirm_button = QtWidgets.QPushButton("Confirm")
        self.cancel_button = QtWidgets.QPushButton("Cancel")

        # Connect buttons to actions
        self.confirm_button.clicked.connect(self.on_confirm)
        self.cancel_button.clicked.connect(self.on_cancel)

        # If approved is passed, show the status
        if approved:
            self.approved_label = QtWidgets.QLabel("Status: Approved")
        else:
            self.approved_label = QtWidgets.QLabel("")

        # Layout for the dialog
        v_layout = QtWidgets.QVBoxLayout()
        v_layout.addWidget(self.category_label)
        if filename:
            v_layout.addWidget(self.filename_label)
        v_layout.addWidget(self.approved_label)
        v_layout.addWidget(self.approval_label)

        # HLayout for buttons (Confirm and Cancel)
        h_layout = QtWidgets.QHBoxLayout()
        h_layout.addWidget(self.confirm_button)
        h_layout.addWidget(self.cancel_button)

        v_layout.addLayout(h_layout)

        self.setLayout(v_layout)

        # Optional: Ensure the window resizes to fit its content
        self.setMinimumSize(300, 150)  # Set a minimum size
        self.adjustSize()  # Let the layout adjust the window size based on its content.

    def on_confirm(self):
        """Handle the confirmation of deletion."""
        self.accept()  # Close the dialog with accepted status

    def on_cancel(self):
        """Handle the cancellation of deletion."""
        self.reject()  # Close the dialog with rejected status