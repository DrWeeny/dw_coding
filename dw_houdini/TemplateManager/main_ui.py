"""
Template Manager UI Module

This module implements the main interface for managing a structured collection of Houdini templates
organized by categories. It allows users to browse, add, delete, rename, and archive templates, as well
as approve versions and leave comments or metadata.

Core Features:
- Dual-view interface: one for categories, one for templates within each category.
- Persistent storage of data in JSON, with support for archiving and user tracking.
- Dynamic model updates and UI transitions with smooth animations.
- Contextual actions through right-click menus tailored to categories or templates.
- Custom user-based filtering for personalized views in the "user" category.
- Integration with Houdini for loading `.hip` or `.otl` template files.

Designed for use within a PyQt5 or PySide2-based Houdini pipeline tool.

Author: drweeny
"""

from PySide6 import QtCore, QtGui, QtWidgets
from .wgt_action_separator import ActionTextSeparator
import hou
from . import template_path, template_json_path
from .template_cmds import (load_assets_from_json, save_assets_to_json, get_latest_approved_file, get_archived_assets_data,
                            get_archived_json_path, safe_move_on_disk, safe_delete_on_disk, get_current_time, get_iter, get_user,
                            create_backup_folder, save_archived_entry, create_json_templates)
from .otl_io import merge_file, write_otl, load_otl
from .wgt_comment_panel import CommentPanel
from .wgt_model_files import FileModel, VersionSortFilterProxyModel
from .wgt_model_categories import CustomStringListModel
from .wgt_confirm_dialogs import TemplateConfirmationDialog, DeleteConfirmationDialog, NewCategoryDialog
from functools import partial
from pathlib import Path
import os, re
from .wgt_user_token_filter import LineEditToken


def getHoudiniWindow():
    win = hou.ui.mainQtWindow()
    return win

class Template_Importer(QtWidgets.QMainWindow):
    """
    Main window for the Template Importer tool.

    This class provides a UI to manage and import templates. It displays a list
    of available categories and templates, allows users to filter by user,
    and handle actions like importing templates or viewing comments.

    Attributes:
        data (list): Loaded assets from the JSON template.
        model_category (CustomStringListModel): Model to hold and display template categories.
        model_files (FileModel): Model for files associated with templates.
        proxy_model (VersionSortFilterProxyModel): Proxy model for sorting and filtering templates.
        _user_filter (str): Current user filter applied.
        _current_file_sel (str): Currently selected file for import.
    """

    def __init__(self, parent=None):
        super(Template_Importer, self).__init__(parent)
        self.setGeometry(579, 515, 647, 181)
        self._width=647
        self._height=181

        # ensure there is a json empty if it was deleted
        if not os.path.isfile(template_json_path) or not os.path.isfile(get_archived_json_path()):
            create_json_templates()

        self.data = load_assets_from_json(template_json_path)
        self._focus_index=0
        self.model_category = None
        self.model_files=None
        self.proxy_model=None
        self.data_category=[]
        self._current_file_sel=None
        self._user_filter = get_user()

        self.setWindowTitle('Template Importer')
        self.initUI()
        self.signal_init()

    def initUI(self):
        """
        Initialize the user interface components: layout, widgets, models, etc.

        Sets up the main layout, category selection view, filter input, and
        sub-template selection view. Also connects various UI components
        to the appropriate event handlers (e.g., button clicks, list item selections).
        """
        self.centralwidget = QtWidgets.QWidget(self)
        self.setCentralWidget(self.centralwidget)
        self.mainLayout = QtWidgets.QVBoxLayout()
        self.centralwidget.setLayout(self.mainLayout)
        self.setMaximumWidth(self._width)
        self.view_layout_main = QtWidgets.QHBoxLayout()
        self.mainLayout.addLayout(self.view_layout_main)
        self.setFixedWidth(self._width)

        #========================FIRST WIDGET =========================#
        # Label
        # ListView - general templates

        self.widget_general = QtWidgets.QWidget()
        self.widget_general.setMaximumSize(QtCore.QSize(self._width, self._height))
        self.widget_layout = QtWidgets.QVBoxLayout()

        self.label = QtWidgets.QLabel("CFX Templates")
        self.label.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)

        #list view general templates
        self.data_category = self.get_categories()
        # List View to list the templates :
        self.model_category = CustomStringListModel(self.data_category)
        self.list_view = QtWidgets.QListView()
        self.list_view.setModel(self.model_category)
        self.list_view.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)

        # Add context menu event to the list view
        self.list_view.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.list_view.customContextMenuRequested.connect(self.show_context_menu)

        self.widget_general.setLayout(self.widget_layout)
        self.widget_layout.addWidget(self.label)
        self.widget_layout.addWidget(self.list_view)


        #========================SCND WIDGET =========================#
        # Return Button
        # ListView - all templates
        self.widget_sub = QtWidgets.QWidget()
        self.widget_sub.setMaximumSize(QtCore.QSize(self._width, self._height+80))
        self.widget_sub.resize(QtCore.QSize(0, self._height))
        self.widget_sub_layout = QtWidgets.QVBoxLayout()

        # the button allow to go back select a category
        self.btn_previous = QtWidgets.QPushButton('<<<<')
        # only visible in user category, you can filter per user, rig/snippet
        self.filter_token = LineEditToken()
        # de
        self.set_token_filter_visibility(False)

        # the main part, it shows all files
        self.sub_list_view = QtWidgets.QListView()
        self.sub_list_view.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.sub_list_view.setMinimumHeight(self._height)
        # Add context menu event to the list view
        self.sub_list_view.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.sub_list_view.customContextMenuRequested.connect(self.show_hip_context_menu)

        self.widget_sub.setLayout(self.widget_sub_layout)
        self.widget_sub_layout.addWidget(self.btn_previous)
        self.widget_sub_layout.addWidget(self.filter_token)
        self.widget_sub_layout.addWidget(self.sub_list_view, stretch=1)
        # widget has a visibility animation, it starts invisible
        self.widget_sub.setVisible(False)

        #========================SCND WIDGET =========================#
        self.view_layout_main.addWidget(self.widget_general)
        self.view_layout_main.addWidget(self.widget_sub)

        #========================IMPORT BUTTON =========================#
        self.button_import = QtWidgets.QPushButton("Import Template")
        # Add to main layout
        self.mainLayout.addWidget(self.button_import)
        self.comment_widget = CommentPanel(self)
        self.mainLayout.addWidget(self.comment_widget)

    def signal_init(self):
        """
        Initialize all the signal-slot connections for the UI components.

        This method connects UI actions (e.g., button clicks, list selections)
        to their respective handlers (e.g., importing a template, navigating between categories).
        """

        self.button_import.clicked.connect(self.import_template)
        self.btn_previous.clicked.connect(partial(self.slide_menu, 1))
        self.list_view.doubleClicked.connect(partial(self.slide_menu, 0))
        self.sub_list_view.doubleClicked.connect(partial(self.comment_toggle, False))
        self.comment_widget.comment_saved.connect(self.save_comment_action)
        self.filter_token.filterChanged.connect(self.update_proxy_file_model)

    def select_category_by_text(self, text:str):
        """
        Selects a category in the category list view by matching its name.

        Args:
            category_name (str): The name of the category to select.
        """
        # Iterate through the model and find the index of the item
        for row in range(self.model_category.rowCount()):
            index = self.model_category.index(row)
            if self.model_category.data(index) == text:
                # Select the item at the found index
                self.list_view.selectionModel().select(index, QtCore.QItemSelectionModel.Select)
                self.list_view.scrollTo(index)
                break

    def force_window_size_refresh(self):
        self.setMinimumWidth(self._width)
        self.adjustSize()

    def set_token_filter_visibility(self, state:bool):
        self.filter_token.setVisible(state)

    def get_users(self):
        return self.data[2]

    def get_user_prefix(self):
        return get_user().lower().replace("-", "")

    def save_comment_action(self, text:str):
        # Get the currently selected template name using the FileModel
        selection_model = self.sub_list_view.selectionModel()

        # Get the index of the selected item in the proxy model
        selected_index = selection_model.currentIndex()
        # because we use a proxy model to sort the model, we need to compare the index against the original one
        source_index = self.proxy_model.mapToSource(selected_index)

        if source_index.isValid() and 0 <= source_index.row() < self.model_files.rowCount(QtCore.QModelIndex()):
            # Get the source model (FileModel) from the proxy model
            source_model = self.proxy_model.sourceModel()
            source_model.save_comment(source_index.row(), text)

            data_model = self.model_files.get_data()
            save_assets_to_json(file_path=template_json_path,
                                folders=data_model[0],
                                version=data_model[1])


    def comment_toggle(self, *args):
        """
        Control the comment widget visibility, update its contents, or toggle its visibility.
        :return: None
        """
        current_template = self.get_selected_template()

        if self.comment_widget.isVisible():
            # If the widget is visible and the selected item has changed, update its contents
            if self._current_file_sel != current_template:
                self._update_comment_widget()
            else:
                # If the item is the same, just toggle the visibility
                self.comment_widget.setVisible(False)
        else:
            # If the widget is not visible, show it and fill it with data
            self.comment_widget.setVisible(True)
            self._update_comment_widget()

        # Refresh the window size if the widget is closed
        if not self.comment_widget.isVisible():
            QtCore.QTimer.singleShot(0, self.force_window_size_refresh)
        else:
            # Allow the user to resize the widget by removing any fixed size constraint
            self.setMaximumHeight(10000)
            self.setMaximumWidth(10000)
            self.comment_widget.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)

        # Update the current selected file
        self._current_file_sel = current_template

    def _update_comment_widget(self):
        """
        Update the comment widget fields with the current selected item's data.
        """
        extra_data = self.get_commentary_data()
        if extra_data:
            comment, user, creation, weblink = extra_data
            self.comment_widget.set_all_fields(comment, user, creation, weblink)

    def close_comment_widget(self):
        """
        Force the comment widget to close, resetting its visibility and clearing the fields.
        """
        self.comment_widget.setVisible(False)
        QtCore.QTimer.singleShot(0, self.force_window_size_refresh)
        self._current_file_sel = None  # Optionally reset the selected file

    def refresh_category_listview(self):
        """
        Refreshes the list view displaying the available categories.
        Updates the model with current data from self.data.
        """
        #list view general templates
        self.data_category = self.get_categories()
        # List View to list the templates :
        self.model_category = QtCore.QStringListModel(self.data_category)
        self.list_view.setModel(self.model_category)

    def get_categories(self)->list:
        """
        Returns a list of available category names from the JSON data.

        Returns:
            list: A list of category names.
        """
        # Ensure "User" key exists (without overwriting anything)
        self.data[0].setdefault("user", [])

        #list view general templates
        data_categories = [cat for cat in self.data[0] if cat != "user"]
        data_categories.append("user")

        return data_categories

    def get_selected_category(self):
        """
        Retrieves the currently selected category from the list view.

        Returns:
            str: The name of the selected category.
        """
        return self.data_category[self.list_view.currentIndex().row()]

    def get_selected_template(self):
        """
        Retrieves the currently selected template name from the sub list view.

        Returns:
            str or None: The name of the selected template, or None if no valid selection is made.
        """
        # Get the currently selected template name using the FileModel
        selection_model = self.sub_list_view.selectionModel()

        # Get the index of the selected item in the proxy model
        selected_index = selection_model.currentIndex()
        # because we use a proxy model to sort the model, we need to compare the index against the original one
        source_index = self.proxy_model.mapToSource(selected_index)

        if source_index.isValid() and 0 <= source_index.row() < self.model_files.rowCount(QtCore.QModelIndex()):
            # Get the source model (FileModel) from the proxy model
            source_model = self.proxy_model.sourceModel()

            # Retrieve the template name from the source model's data method
            selected_template_name = source_model.data(source_index, QtCore.Qt.DisplayRole)

            return selected_template_name
        else:
            return None  # No selection, return None

    def get_commentary_data(self)->list:
        """
        Retrieves commentary metadata (comment, user, creation date, weblink) for the selected template.

        Returns:
            list: A list containing [comment, user, creation, weblink], or None if not found.
        """
        # Get the currently selected template name using the FileModel
        selection_model = self.sub_list_view.selectionModel()

        # Get the index of the selected item in the proxy model
        selected_index = selection_model.currentIndex()
        # because we use a proxy model to sort the model, we need to compare the index against the original one
        source_index = self.proxy_model.mapToSource(selected_index)

        if source_index.isValid() and 0 <= source_index.row() < self.model_files.rowCount(QtCore.QModelIndex()):
            # Get the source model (FileModel) from the proxy model
            source_model = self.proxy_model.sourceModel()
            # Retrieve the template name from the source model's data method
            selected_template_extras = source_model.data(source_index, QtCore.Qt.UserRole + 2)

            return selected_template_extras

    def import_template(self):
        """
        Imports a template based on the current selection:
        - If no template is selected, imports the latest approved template in the current category.
        - If a template is selected in the sub-list, imports that specific file.
        """

        selected_category = self.get_selected_category()

        if not self._focus_index:
            latest_approved_file = get_latest_approved_file(selected_category)

            if latest_approved_file:
                # If there's a valid latest approved file, you can perform your import action
                _file=latest_approved_file['name']
                _filepath=os.path.join(template_path, selected_category, _file)
                _filepath=Path(_filepath).as_posix()
                print(f"Importing template: {_filepath}")
                if ".hip" in _filepath:
                    merge_file(_filepath)
                else:
                    load_otl(_filepath)
        else:
            # We're in the second QListView (showing files for the selected category)
            current_model = self.sub_list_view.selectionModel()
            selected_index = current_model.currentIndex()

            if selected_index:
                # Get the selected file from the second QListView
                source_index = self.proxy_model.mapToSource(selected_index)
                file_name = self.model_files.get_selected_file(source_index.row())

                # Ensure the file exists before proceeding
                selected_file_path = os.path.join(template_path, selected_category, file_name)
                if os.path.exists(selected_file_path):
                    # Import the selected file
                    print(f"Importing template: {selected_file_path}")
                    if ".hip" in selected_file_path:
                        merge_file(selected_file_path)
                    else:
                        load_otl(selected_file_path)
                else:
                    print(f"File does not exist: {selected_file_path}")
            else:
                print("No file selected in the second QListView.")

    def set_selection_to_first_item(self):
        # Try selecting the first item if it exists
        index = self.proxy_model.index(0, 0)  # First row, first column
        if index.isValid():
            self.sub_list_view.selectionModel().select(index, QtCore.QItemSelectionModel.Select)

    def get_sublist_index(self):
        """
        Retrieves the currently selected index in the sublist view.
        """
        current_model = self.sub_list_view.selectionModel()
        selected_index = current_model.currentIndex()

        if selected_index.isValid():
            source_index = self.proxy_model.mapToSource(selected_index)
            if source_index.isValid():
                return source_index.row()
        return None

    def file_model_init(self, selected_category:str):
        """
        Initializes the model for the category list view.
        Connects the selection changed signal to the handler.
        """
        self.model_files = FileModel(self.data, selected_category)

        # Apply sorting
        self.proxy_model = VersionSortFilterProxyModel()
        self.proxy_model.setSourceModel(self.model_files)  # Set the source model
        self.proxy_model.sort(0, QtCore.Qt.DescendingOrder)

        # Set the proxy model to the list view
        self.sub_list_view.setModel(self.proxy_model)

        # init token by default with current user
        self.filter_token.set_user_list(self.get_users())
        self.filter_token.add_token(get_user() ,clear_input=False)


    def update_proxy_file_model(self, users_filter:list):
        """
        Updates the proxy model with a list of user-based filters.

        Args:
            users_filter (list): A list of usernames to filter templates by.
        """
        self._user_filter = users_filter
        if self.proxy_model:
            self.proxy_model.set_user_filter(users_filter)
            self.proxy_model.invalidateFilter()

    def set_current_category(self, category_name):
        """
        Updates the file model to show files from the specified category
        without rebuilding the entire model.
        """
        if self.model_files._current_category != category_name:
            self.model_files.set_current_category(category_name)

    def slide_menu(self, state=0, *args):
        """
        Slides the UI between the main category view and the sub-list (template) view.

        Args:
            state (int): If 0, slide to sub list; if 1, slide to main category list.
        """
        # Order of widgets
        order = [self.widget_general, self.widget_sub]

        if not state:
            # Update the list of files for the selected category
            selected_category = self.get_selected_category()

            # self.file_model_init(selected_category)
            if not self.model_files:
                self.file_model_init(selected_category)
            else:
                self.sub_list_view.selectionModel().clearSelection()
                self.model_files.set_current_category(selected_category)
                self.proxy_model.invalidate()  # ensure the proxy refilters/sorts based on new data

            if selected_category == "user":
                self.set_token_filter_visibility(True)
                tokens = [name for name in self.filter_token.get_tokens()]
                self.update_proxy_file_model(tokens)
            else:
                self.set_token_filter_visibility(False)
                self.update_proxy_file_model([])

            self._focus_index=1

        if state:
            order = order[::-1]
            self._focus_index=0
            # if the comment widget was opened, we can close it
            self.close_comment_widget()
            self.sub_list_view.selectionModel().clearSelection()

        # Animating widget_general (hide it by animating size to 0)
        self.anim = QtCore.QPropertyAnimation(order[0], b"size")
        self.anim.setDuration(250)
        self.anim.setStartValue(QtCore.QSize(self._width, self._height))
        self.anim.setEndValue(QtCore.QSize(0, self._height))
        self.anim.setEasingCurve(QtCore.QEasingCurve.InOutQuart)

        # Animating widget_sub (show it by animating size to full size)
        self.anim_2 = QtCore.QPropertyAnimation(order[1], b"size")
        self.anim_2.setDuration(350)
        self.anim_2.setStartValue(QtCore.QSize(0, self._height))
        self.anim_2.setEndValue(QtCore.QSize(self._width, self._height))
        self.anim_2.setEasingCurve(QtCore.QEasingCurve.InOutQuart)

        # Group animations and start
        self.anim_group = QtCore.QParallelAnimationGroup()
        self.anim_group.addAnimation(self.anim)
        self.anim_group.addAnimation(self.anim_2)

        # Make the second widget visible after starting the animation
        if state == 0:
            self.widget_sub.setVisible(True)
            self.widget_general.setVisible(False)
        else:
            self.widget_sub.setVisible(False)
            self.widget_general.setVisible(True)

        self.anim_group.start()

    def show_context_menu(self, pos):
        """
        Displays a context menu with actions related to categories and templates.

        Args:
            pos (QPoint): Position to display the context menu.
        """
        # Create context menu
        context_menu = QtWidgets.QMenu(self)

        # Add actions to the context menu

        # Add actions to the context menu
        separator = ActionTextSeparator("category actions", self)
        context_menu.addAction(separator)  # Add the separator

        # user category is a permanent category, nor actions should be done :
        category = self.get_selected_category()

        if category != "user":
            action_new = context_menu.addAction("Add New Category")
            action_rename = context_menu.addAction("Rename Category")
            action_delete = context_menu.addAction("Delete Category")

            # Connect actions to their respective methods
            action_rename.triggered.connect(self.rename_category)
            action_delete.triggered.connect(self.delete_category)
            action_new.triggered.connect(self.add_new_category)

        separator = ActionTextSeparator("template actions", self)
        context_menu.addAction(separator)  # Add the separator

        action_add_template = context_menu.addAction("Add Template")

        # Show the context menu at the clicked position
        context_menu.exec_(self.list_view.mapToGlobal(pos))

    def rename_category(self):
        """
        Renames the currently selected category, updates folder names and JSON accordingly.
        Ensures the name is unique and valid before proceeding.
        """
        # Step 1: Open a dialog for the user to input a category name
        dialog = NewCategoryDialog(self)
        if dialog.exec_() == QtWidgets.QDialog.Accepted:
            new_category_name = dialog.category_name
            current_category = self.get_selected_category()

            if new_category_name in self.data[0]:
                print("category already exists")
                return None

            # Two cases :
            # A - We just have created the category with new category action, so the folder doesnt exists yet
            #     and it is not registered in json, if it doesnt exists lets just rename
            folder_path = os.path.join(template_path, current_category)
            if not os.path.exists(folder_path):
                # Step 2: Add an empty entry to the JSON
                self.data[0][new_category_name] = []

                self.data_category.append(new_category_name)
                self.model_category.setStringList(self.data_category)
            else:
                # B -
                # 1 - we need to update the json with the new category
                # 2 - we need to also update the archived json
                # 3 - we need to rename the folder
                # 4 - we need to refresh the model

                #jsons :
                self.data[0][new_category_name]=self.data[0].pop(current_category)
                archived_data = get_archived_assets_data()
                if current_category in archived_data[0]:
                    archived_data[0][new_category_name] = archived_data[0][current_category]
                    del archived_data[0][current_category]
                #save main json
                save_assets_to_json(file_path=template_json_path,
                                    folders=self.data[0],
                                    version=None)
                #save archived
                save_assets_to_json(file_path=get_archived_json_path(),
                                    folders=self.data[0],
                                    version=None)

                # Rename the folder
                old_name = os.path.join(template_path, current_category)
                new_name = os.path.join(template_path, new_category_name)
                os.rename(old_name, new_name)

                # model
                list_index = self.data_category.index(current_category)
                self.data_category[list_index] = new_category_name
                self.model_category.setStringList(self.data_category)
                self.select_category_by_text(new_category_name)


    def delete_category(self):
        """
        Deletes a category, either by archiving or directly removing it based on certain conditions:
        - If the category is empty, it's deleted from both the filesystem and the JSON data.
        - If the category contains templates, it checks if it has been archived.
          - If archived, it asks the user if they want to merge, override, or cancel.
          - If not archived, the category is archived before deletion.

        Updates the category list view after deletion or archiving.
        """
        category = self.get_selected_category()
        folder_path = os.path.join(template_path, category)
        archive_path = os.path.join(template_path, ".backup", category)

        # Case 1: If the category folder is empty, we can delete it.
        if not os.path.exists(folder_path) or len(os.listdir(folder_path)) == 0:
            # No templates, proceed with deletion
            self._delete_category_from_json(category)
            self._delete_category_folder(folder_path)
            # refresh category list
            self.refresh_category_listview()
            print(f"Category {category} deleted.")
            return

        # Case 2: If the category has templates , check for archived data.
        archived_data = get_archived_assets_data(True)

        if category in archived_data["archived_cfx_categories"]:
            # Show confirmation dialog for the user
            result = self.confirm_archive_dialog(category)

            if result == 'merge':
                # update archived json with the new file entries
                self._merge_category_with_archived(category, archived_data)
                # list all the new files in the folder
                files = os.listdir(folder_path)
                matched_files = [
                    file for file in files
                    if file.lower().endswith(tuple(['.hip', '.otl']))
                ]
                # list files in the backup
                files = os.listdir(archive_path)
                matched_archived_files = [
                    file for file in files
                    if file.lower().endswith(tuple(['.hip', '.otl']))
                ]

                # substract files that already exists and then join the path
                files_to_move =  set(matched_files)-set(matched_archived_files)
                files_to_move = list(files_to_move)
                files_to_move_fullpath = [os.path.join(folder_path, file) for file in files_to_move]
                # move the files into archive
                for f in files_to_move_fullpath:
                    safe_move_on_disk(f, archive_path)
                    # shutil.move(f, archive_path)
                # delete the folder
                self._delete_category_folder(folder_path)

                print(f"Category {category} merged with archive.")
            elif result == 'override':
                # update the json data
                self._merge_category_with_archived(category, archived_data, True)
                # delete the .backup/category folder
                self._delete_category_folder(archive_path)
                # move the folder
                safe_move_on_disk(folder_path, archive_path)
                # shutil.move(folder_path, archive_path)
                print(f"Category {category} overridden with new data.")
            elif result == 'cancel':
                print("Category deletion cancelled.")
                return
        else:
            # If not archived yet, simply archive the category
            result = self.delete_confirmation_dialog(category)
            if result:
                if not os.path.exists(os.path.dirname(archive_path)):
                    # make the .backup folder
                    os.makedirs(os.path.dirname(archive_path))

                # Move the category folder to an archive location
                if os.path.exists(folder_path):
                    safe_move_on_disk(folder_path, archive_path)

                # update archived data :
                self._merge_category_with_archived(category, archived_data, True)

                print(f"Category {category} archived.")
            else:
                return

        # Now that we've handled the templates, proceed with deletion (if needed)
        self._delete_category_from_json(category)
        self.refresh_category_listview()


    def _delete_category_folder(self, folder_path):
        """
        Deletes the specified category folder from the filesystem if it is empty.

        Args:
            folder_path (str): Path to the category folder to be deleted.
        """
        # Remove the category folder if it's empty (we already checked this above)
        if os.path.exists(folder_path) and len(os.listdir(folder_path)) == 0:
            safe_delete_on_disk(folder_path)
            # shutil.rmtree(folder_path)

    def _delete_category_from_json(self, category):
        """
        Removes the specified category from the internal data structure (JSON).

        Args:
            category (str): Name of the category to be removed from the JSON data.
        """
        if category in self.data[0]:
            del self.data[0][category]
            save_assets_to_json(file_path=template_json_path,
                                folders=self.data[0],
                                version=None)
            print(f"Category {category} deleted from JSON.")

    def _merge_category_with_archived(self, category, archived_data, override=False):
        """
        Merges the current category's data with the archived data.

        If `override` is False, new files from the current category are appended to the archive.
        If `override` is True, the current category overwrites the archived data.

        Args:
            category (str): Name of the category to be merged.
            archived_data (dict): The current archived data.
            override (bool): Whether to override the archived data (default is False).
        """
        # Merge the current category's data with the archived data.
        current_data = self.data[0].get(category, [])
        if not override:
            archived_data["archived_cfx_categories"][category]["files"].extend(current_data)
        else:
            archived_data["archived_cfx_categories"][category] = current_data

        archived_data["archived_cfx_categories"][category]["archived_time"] = get_current_time()
        archived_data["archived_cfx_categories"][category]["deleted_by"] = get_current_time()

        # Save merged data back to the archived JSON
        save_assets_to_json(file_path=get_archived_json_path(),
                            folders=archived_data,
                            version=None,
                            fulldata=True)

    def add_new_category(self):
        """
        Opens a dialog for the user to input a new category name.
        If the name is unique, it adds the new category to the internal data structure
        and updates the JSON file and the list view.

        """
        # Step 1: Open a dialog for the user to input a category name
        dialog = NewCategoryDialog(self)
        if dialog.exec_() == QtWidgets.QDialog.Accepted:
            new_category_name = dialog.category_name

            # check if category already exists :
            if new_category_name in self.get_categories():
                print(f"{new_category_name} already in category")
                return

            # Step 2: Add an empty entry to the JSON
            self.data[0][new_category_name] = {"files":[]}

            # Step 4: Update the list view to reflect the new category
            self.data_category.append(new_category_name)
            self.model_category.setStringList(self.data_category)

    def show_hip_context_menu(self, pos):
        """
        Displays a context menu for managing templates in the selected category.

        Options include:
        - Set or remove approval for a template
        - Add template from Houdini
        - Remove selected template

        Args:
            pos (QPoint): The position where the context menu is triggered.
        """
        # Get the selected index from the view
        current_model=self.sub_list_view.selectionModel()
        selected_index = current_model.currentIndex()
        approved=None

        if selected_index.isValid():
            # Get the current item from the model
            source_index = self.proxy_model.mapToSource(selected_index)

            # Check if the index is valid and within the row count
            if source_index.isValid() and 0 <= source_index.row() < self.model_files.rowCount(QtCore.QModelIndex()):
                approved = self.model_files.data(source_index, QtCore.Qt.UserRole + 1)

        # Create context menu
        context_menu = QtWidgets.QMenu(self)

        if isinstance(approved, bool):
            if approved:
                # If the template is already approved, show "Remove Approval"
                remove_action = context_menu.addAction("Remove Approval")
                remove_action.triggered.connect(lambda: self.set_app_template(False))  # Set state to False for removal
            else:
                # If the template is not approved, show "Set Approved"
                action_app_template = context_menu.addAction("Set Approved")
                action_app_template.triggered.connect(lambda: self.set_app_template(True))  # Set state to True for approval

        action_add_houdini = context_menu.addAction("Add Template from Houdini")
        if selected_index.isValid():
            action_rm_template = context_menu.addAction("Remove Template")
            action_rm_template.triggered.connect(self.action_remove_template)

        # Connect actions to their respective methods
        action_add_houdini.triggered.connect(self.add_template)

        # Show the context menu at the clicked position
        context_menu.exec_(self.sub_list_view.mapToGlobal(pos))

    def set_app_template(self, state: bool):
        """
        Sets the approval state for the selected template.

        Args:
            state (bool): True to approve the template, False to remove approval.
        """
        # Get the selected index from the view
        current_model = self.sub_list_view.selectionModel()
        selected_index = current_model.currentIndex()

        if selected_index.isValid():
            # Map the selected index from the proxy model to the source model
            source_index = self.proxy_model.mapToSource(selected_index)

            self.model_files.set_approved(source_index.row(), state)
            data_model = self.model_files.get_data()
            save_assets_to_json(file_path=template_json_path,
                                folders=data_model[0],
                                version=data_model[1])


    def add_template(self, confirmation=True):
        """
        Adds a new template to the selected category, generating a unique filename and updating the JSON data.

        Args:
            confirmation (bool): Whether to show a confirmation dialog before adding the template (default is True).
        """
        # category currently selected
        selected_category = self.get_selected_category()

        # if we are on the first widget, the second model might not be initialized
        # so in this occurence we would get the version from json
        if self._focus_index:
            next_iter = self.model_files.get_iter(next=True)
        else:
            next_iter = get_iter(selected_category)

        # a confirmation window is prompted so you can change the category but also
        # you can make a comment
        confirmed = self.open_confirmation_dialog(selected_category, next_iter)
        _cat_changed = False

        # if we have changed the category, we change the selection in the model
        # but also if we are in the second panel, we need to update the file model
        if confirmed:
            confirmed_category, next_iter, comment, weblink, template_name = confirmed
            if confirmed_category != selected_category:
                selected_category=confirmed_category
                self.select_category_by_text(selected_category)
                _cat_changed = True

            # You can adjust the file name or path based on the source type if needed
            if selected_category != "user":
                file_name = f"{template_name}_v{next_iter:03}.otl"
            else:
                current_user = self.get_user_prefix()
                file_name = f"{current_user}_{template_name}_v{next_iter:03}.otl"

            # Write the template to the target path (could be more logic here based on source_type)
            target_path = os.path.join(template_path, selected_category)

            # if we are on the second qlistview, we need to update it
            # otherwise we need to update the data
            if self._focus_index:
                tmp_data = self.model_files.add_file(file_name,
                                                     approved=False,
                                                     comment=comment,
                                                     weblink=weblink)
            else:
                tmp_data=self.data

                new_file = {
                    "name": file_name,
                    "approved": False,
                    "user": get_user(),
                    "comment": comment,
                    "creation_time": get_current_time(),
                    "weblink":weblink
                }

                # # Update the category files list in the JSON structure
                tmp_data[0][selected_category]["files"].append(new_file)

            # write otl/hip on disk
            write_otl(target_path, file_name)

            # Save the updated JSON to disk
            save_assets_to_json(file_path=template_json_path,
                                folders=tmp_data[0],
                                version=tmp_data[1],
                                user_registration=get_user())

            # if second view is focused
            if self._focus_index:
                # Avoid race condition by ensuring the model is fully updated before sorting
                QtCore.QTimer.singleShot(0, lambda: self.proxy_model.sort(0, QtCore.Qt.DescendingOrder))

    def action_remove_template(self):
        """
        Removes the selected template from the current category, after archiving it to a backup location.
        Updates the internal data structure and JSON file accordingly.
        """

        # get main data entry to be copied to archive data
        index_selected = self.get_sublist_index()
        file_entry = self.model_files.get_selected_entry(index_selected)
        if file_entry:

            # ensure there is a backup folder in the category
            category = self.get_selected_category()
            path = create_backup_folder(category)

            # we need to move the file in the backup
            # get selected template name, methods has the extension
            selected_template_name = file_entry["name"]
            approved_status = file_entry["approved"]

            # prompt a confirm window
            result = self.delete_confirmation_dialog(category, selected_template_name, approved_status)

            if result:
                # store current time
                file_entry["archived_time"] = get_current_time()
                file_entry["deleted_by"] = get_user()

                # pop the entry from the current data model
                self.model_files.delete_selected_file(index_selected)

                # udpate the current json
                # todo should store the minimum increment value to the data, ie if we delete file v002, and it was the
                # maximum, we store this value so next saved template would be v003
                # in this case if we delete v002 but it is under v003, we dont care
                data_model = self.model_files.get_data()
                save_assets_to_json(file_path=template_json_path,
                                    folders=data_model[0],
                                    version=data_model[1])

                # lets get current path :
                current_path = os.path.join(template_path, category, selected_template_name)
                target_path = os.path.join(path, selected_template_name)

                if os.path.exists(target_path):
                    # todo if a file has already been stored, lets put .xxxx to the name
                    pass

                # lets move to the backup file
                if os.path.exists(current_path):
                    safe_move_on_disk(current_path, target_path)

                # update the archived json:
                save_archived_entry(category, file_entry)
                self.refresh_model_and_proxy()

    def refresh_model_and_proxy(self):
        self.model_files.layoutChanged.emit()
        # important because otherwise it keep a random selection and it crashes
        self.sub_list_view.selectionModel().clearSelection()
        self.proxy_model.invalidateFilter()
        self.proxy_model.layoutChanged.emit()


    def refresh_sub_list_view(self, index=False):
        """
        Refreshes the sublist view of templates. If a specific index is provided,
        it only refreshes that item; otherwise, it refreshes the entire view.

        Args:
            index (int or bool): The index of the item to refresh, or False to refresh the entire view.
        """
        if index == False:
            # If no specific selection is provided, refresh the entire view
            self.model_files.layoutChanged.emit() # Emit layoutChanged to force a full refresh
        else:
            idx = self.model_files.index(index, 0)  # Providing both row and column (e.g., 0 for the first column)

            if idx.isValid():
                # Emit dataChanged or layoutChanged signal as needed
                self.model_files.dataChanged.emit(idx, idx)  # Refresh the specific item

    def open_confirmation_dialog(self, category_name, next_version):
        """
        Opens a confirmation dialog to confirm adding a new template.

        Args:
            category_name (str): The name of the selected category.
            next_version (int): The next version number for the template.

        Returns:
            tuple: The confirmed values (category_name, next_version, comment, weblink, template_name),
                   or None if canceled.
        """
        # Create the confirmation dialog
        # model_category is used for populating the combobox
        dialog = TemplateConfirmationDialog(self, category_name, next_version, self.model_category)

        if dialog.exec_() == QtWidgets.QDialog.Accepted:
            # If the user clicks OK in the dialog, process the files
            result = dialog.result()
            return result
        else:
            return None

    def delete_confirmation_dialog(self, category, filename=None, approved=None):
        dialog = DeleteConfirmationDialog(self, category, filename, approved)
        result = dialog.exec_()

        if result == QtWidgets.QDialog.Accepted:
            # print(f"File {filename} from category {category} has been confirmed for deletion.")
            return True
        else:
            # print(f"File {filename} from category {category} was not deleted.")
            return False

    def confirm_archive_dialog(self, category, *args):
        # Create a simple confirmation dialog with options: "merge", "override", "cancel"
        dialog = QtWidgets.QMessageBox(self)
        dialog.setIcon(QtWidgets.QMessageBox.Question)
        dialog.setText(f"Category {category} has already been archived. What would you like to do?")
        dialog.setWindowTitle("Confirm Archive Action")

        # Add buttons directly using standard button constants
        # dialog.setStandardButtons(QtWidgets.QMessageBox.Cancel | QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)

        # Add custom buttons
        merge_button = dialog.addButton("Merge anyway", QtWidgets.QMessageBox.AcceptRole)
        override_button = dialog.addButton("Override", QtWidgets.QMessageBox.HelpRole)

        # Set the default button (Merge anyway in this case)
        dialog.setDefaultButton(merge_button)

        # Now add Cancel button at the end with DestructiveRole
        cancel_button = dialog.addButton("Cancel", QtWidgets.QMessageBox.RejectRole)

        # Execute the dialog and get the result
        dialog.exec_()

        # Handle the result based on which button was clicked
        if dialog.clickedButton() == merge_button:
            return 'merge'
        elif dialog.clickedButton() == override_button:
            return 'override'
        else:
            return 'cancel'

    def closeEvent(self, event):
        self.setParent(None)
