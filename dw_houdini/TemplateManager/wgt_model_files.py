"""
This module contains the data models and proxy models used to manage file and template information

Key Components:
    - `VersionSortFilterProxyModel`: A custom proxy model used to sort file items based on version numbers
      extracted from their names (e.g., v001, v002, etc.). It ensures that files are ordered correctly by their version.
    - `FileModel`: A table model that handles the display, modification, and management of file entries.
      It supports adding new files, deleting files, saving comments, changing approval status, and retrieving selected files.

Functional Overview:
    - Sorting of file versions based on version number (in ascending order).
    - Adding, updating, and deleting files in a category.
    - Managing approval status and comments associated with files.
    - Providing a mechanism to retrieve data associated with selected files and templates.

The models are designed to work with Qt-based views (`QTableView`, `QListView`, etc.) and
integrate into a larger UI application, facilitating interaction with file data.

Author: drweeny
"""

from PySide2 import QtCore, QtGui, QtWidgets
import re
from .template_cmds import get_user, get_current_time
from typing import Optional

class VersionSortFilterProxyModel(QtCore.QSortFilterProxyModel):
    """
    A proxy model that supports:
        - Sorting files by version numbers in their names (e.g., v001, v002)
        - Filtering files by usernames associated with them (used in user category)

    TODO:
        - Add support for filtering by data type (e.g., snippets vs templates)
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._user_filter = []  # list of usernames

    def set_user_filter(self, user_list: list[str]):
        """Set a list of usernames to filter by."""

        self._user_filter = user_list
        self.invalidateFilter()  # refresh the view

    def filterAcceptsRow(self, source_row: int, source_parent: QtCore.QModelIndex) -> bool:
        """
        Filters out rows whose user is not in the current user filter.

        Args:
            source_row: Row index in the source model
            source_parent: Parent index

        Returns:
            True if the row should be visible; False otherwise
        """
        if not self._user_filter:
            return True  # show all if no filters

        index = self.sourceModel().index(source_row, 0, source_parent)
        user_data = self.sourceModel().data(index, FileModel.ROLE_METADATA)

        if isinstance(user_data, list) and len(user_data) > 1:
            username = user_data[1].lower()
            return any(partial.lower() in username for partial in self._user_filter)

        return False

    def lessThan(self, left: QtCore.QModelIndex, right: QtCore.QModelIndex) -> bool:
        """
        Compares two items based on version numbers in their names.

        Args:
            left (QModelIndex): The left index for comparison.
            right (QModelIndex): The right index for comparison.

        Returns:
            bool: True if the left item should come before the right item (i.e., left < right),
                  False otherwise.

        Notes:
            If the version number is not found in either of the file names, the method
            falls back to the default sorting behavior provided by `QSortFilterProxyModel`.
        """
        # Extract version numbers using a regular expression (v001, v002, etc.)
        left_name = left.data()
        right_name = right.data()

        # Regular expression to extract version from file name (e.g., v001, v002, etc.)
        version_regex = r"v(\d+)"
        left_version_match = re.search(version_regex, left_name)
        right_version_match = re.search(version_regex, right_name)

        if left_version_match and right_version_match:
            left_version = int(left_version_match.group(1))  # Get the version number (as an integer)
            right_version = int(right_version_match.group(1))
            return left_version < right_version  # Sort by the version number
        return super().lessThan(left, right)  # Fallback to default if no version found

class FileModel(QtCore.QAbstractTableModel):
    """
    Table model for managing a list of categorized files.

        Attributes:
        _data (dict):
            Stores the current data representing the files for a particular category.

        _key (str):
            The key identifying the category of data being managed (e.g., category name).
    """

    ROLE_APPROVED = QtCore.Qt.UserRole + 1
    ROLE_METADATA = QtCore.Qt.UserRole + 2
    GREEN_CIRCLE_SIZE = 20

    def __init__(self, data: list[dict], key:str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # there is in the model one special case to handle which is if category = "user"
        # then there is a prefix username_ in the filename
        self._data = data
        self._key = key
        self._cached_green_circle = None  # Initialize cache for green circle
        self._current_category= None


    def data(self, index: QtCore.QModelIndex, role: int):
        """Return data for a given role at the specified index."""

        # find all the files associated to the category
        files = self._data[0].get(self._key, {}).get("files", [])
        if index.row() >= len(files):
            return None

        # current file
        file = files[index.row()]

        # display text in the ui with a nice name
        if role == QtCore.Qt.DisplayRole:
            if "name" not in file:
                print(f"[Warning] File entry at row {index.row()} missing 'name': {file}")
                return f"error_name{index.row()}"
            file_name = file["name"].rsplit(".", 1)[0]
            if self._key == "user":
                file_name = "_".join(file_name.split("_")[1:])
            return file_name

        # files which are approved have a green circle
        if role == QtCore.Qt.DecorationRole and file.get("approved"):
            return self.create_green_circle()

        # we store the approved status in a variable so when the row is selected we can retrieve it easily
        if role == self.ROLE_APPROVED:
            return file.get("approved", False)

        # we store all other variables in another user role variable
        if role == self.ROLE_METADATA:
            return [
                file.get("comment", ""),
                file.get("user", ""),
                file.get("creation_time", ""),
                file.get("weblink", "")
            ]

        return None

    def rowCount(self, index)-> int:
        """Return number of files in the current category."""
        files = self._data[0].get(self._key, {}).get("files", [])
        return len(files)

    def columnCount(self, index)-> int:
        """Model contains only one column."""
        return 1

    def get_iter(self, next:bool=True) -> int:
        """
        Return the next version number or the current max version.

        Uses regex to extract version patterns (e.g., _v001).
        """
        # Regex pattern for extracting _v### (e.g., _v001, _v002, etc.)
        version_pattern = re.compile(r"_v(\d{3})")

        max_version = 0
        for row in range(self.rowCount(QtCore.QModelIndex())):  # Pass QModelIndex() as argument to rowCount
            # Get the QModelIndex for the current row
            index = self.index(row, 0)  # (row, column) where column is 0 (since it's a single column model)

            # Get the display role text for the current row
            file_name = self.data(index, QtCore.Qt.DisplayRole)

            # Search for version pattern
            match = version_pattern.search(file_name)
            if match:
                version_number = int(match.group(1))  # Extract the version number as integer
                max_version = max(max_version, version_number)

        # Return the next version number (if `next` is True) or the max version found
        return max_version + 1 if next else max_version

    def create_green_circle(self) -> QtGui.QPixmap:
        """Generate and cache a green circular pixmap to indicate approval."""
        if self._cached_green_circle is not None:
            return self._cached_green_circle  # Return cached pixmap

        # Create a pixmap to draw on
        pixmap = QtGui.QPixmap(self.GREEN_CIRCLE_SIZE, self.GREEN_CIRCLE_SIZE)  # Size of the circle
        pixmap.fill(QtCore.Qt.transparent)  # Start with a transparent background

        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)  # For smooth curves
        painter.setBrush(QtGui.QBrush(QtCore.Qt.green))  # Fill the circle with green
        painter.setPen(QtCore.Qt.NoPen)  # No border
        painter.drawEllipse(0, 0, self.GREEN_CIRCLE_SIZE, self.GREEN_CIRCLE_SIZE)  # Draw a circle (x, y, width, height)
        painter.end()

        self._cached_green_circle = pixmap  # Cache the pixmap
        return pixmap

    def add_file(self,
                 file_name:str,
                 approved:bool=False,
                 comment:str=None,
                 weblink:str=None,
                 ):
        """
        Adds a new file to the model's data and notifies the view to refresh.
        :param file_name: The name of the file to be added.
        :param approved: Approval status of the file.
        :param comment: Optional comment for the file.
        :param weblink: Optional web link for the file.
        """
        # Prepare the new file's data
        new_file = {
            "name": file_name,
            "approved": approved,
            "user": get_user(),
            "comment": comment,
            "creation_time": get_current_time(),
            "weblink": weblink,
        }

        self.layoutAboutToBeChanged.emit()

        # check if data is empty
        category_data = self._data[0].setdefault(self._key, {})
        category_data.setdefault("files", [])
        category_data["files"].append(new_file)
        # Emit the layoutChanged signal to notify the view to refresh
        self.layoutChanged.emit()
        return self._data

    def _safe_file(self, index: int) -> Optional[dict]:
        try:
            return self._data[0][self._key]["files"][index]
        except (IndexError, KeyError, TypeError):
            return None

    def save_comment(self, index, text:str):
        """Save a comment for the file at a given index."""
        if isinstance(index, int):
            file = self._safe_file(index)
            if file:
                file["comment"] = text

    def set_approved(self, index, state: bool):
        """
        Sets the approval status for a file at the given index.
        Args:
            index: int
            state: bool
        """
        if isinstance(index, int):
            # Assuming single selection; for multiple selections, you can iterate over the indexes
            self._data[0][self._key]["files"][index]["approved"]=state

    def get_selected_file(self, index: int) -> Optional[str]:
        """Retrieve the name of the file at the specified index."""
        if isinstance(index, int):
            # Assuming single selection; for multiple selections, you can iterate over the indexes
            return self._data[0][self._key]["files"][index]["name"]

    def get_selected_entry(self, index: int) -> Optional[dict]:
        """Retrieve the full entry (data) of the selected file at the specified index."""
        if isinstance(index, int):
            return self._data[0][self._key]["files"][index]

    def delete_selected_file(self, index):
        """
        Deletes the file at the specified index and refreshes the view.

        Returns:
            dict: The removed file entry.
        """
        if isinstance(index, int):
            entry = self._data[0][self._key]["files"][index]
            self._data[0][self._key]["files"].pop(index)
            self.layoutChanged.emit()
            return entry

    def get_selected_template_name(self, selection_model, proxy_model=None):
        """Return the name of the selected file in the view."""

        selected_indexes = selection_model.selectedIndexes()
        if selected_indexes:
            index = selected_indexes[0]
            if proxy_model:
                index = proxy_model.mapToSource(index)
            file = self._safe_file(index.row())
            if file and "name" in file:
                return file["name"]

    def get_data(self)->list[dict]:
        """Return the model's current data."""
        return self._data

    def clear(self):
        if self._data:
            self._data = []
            self.layoutChanged.emit()

    def reset_model(self, new_data=None):
        """
        For refresh button
        """
        self.layoutAboutToBeChanged.emit()
        if new_data is not None:
            self._data = new_data
        self.layoutChanged.emit()

    def set_current_category(self, category_name):
        """
        Change the view's focus to a different category's data.
        """
        if self._current_category != category_name:
            self.beginResetModel()
            self._current_category = category_name
            self._key = category_name
            self.endResetModel()

    def get_user_list(self) -> list:
        """
        functions to get all people contributing in the json, might hit perf over amount of file
        """
        return list({file.get("user", "") for file in self._data[0].get(self._key, {}).get("files", [])})

