from PySide6 import QtWidgets, QtCore, QtGui
from typing import List, Optional, Dict, Any
from dw_logger import get_logger
from dw_maya.dw_maya_utils import extract_id, component_in_list, create_maya_ranges
from maya import cmds
from dw_maya.dw_nucleus_utils.dw_core import set_nucx_map_data
from dw_maya.dw_deformers.dw_core import set_deformer_weights
from dw_maya.dw_paint import get_current_artisan_map
import numpy as np

logger = get_logger()


class VtxStorageButton(QtWidgets.QPushButton):
    """A button that can store and restore vertex weights and selections"""

    def __init__(self):
        """
        Initialize the storage button

        Args:
            btn_type: Type of storage ('weights' or 'selection')
        """
        super().__init__()
        self.btn_type = None
        self._current_weight_node = None
        self.storage: Dict[str, Any] = {
            'weights': [],
            'selection': {},
            'weight_node': None,
            'weight_type': None
        }
        self._setup_ui()

    def _setup_ui(self):
        """Setup the button's UI"""
        self.setStyleSheet("""
            QPushButton {
                background-color: rgb(128, 128, 128);
                border: none;
                border-radius: 2px;
                padding: 5px;
                color: white;
            }
            QPushButton:hover {
                background-color: rgb(140, 140, 140);
            }
        """)

    def mousePressEvent(self, event: QtCore.QEvent):
        """Handle mouse press events based on position and button state
        For dual-colored buttons with diagonal split:
        - Upper-right area (green): Restore only weights
        - Lower-left area (tan): Restore only selection
        - Middle near diagonal: Restore both
        """
        if event.button() == QtCore.Qt.LeftButton:
            # Only do position check if we have both weights and selection
            if self.storage["weights"] and self.storage["selection"]:
                # Get click position relative to button
                x = event.pos().x()
                y = event.pos().y()

                # Convert to normalized coordinates (0-1)
                norm_x = x / self.width()
                norm_y = y / self.height()

                # Define tolerance for middle zone
                tolerance = 0.1  # Adjust this value to make middle zone larger/smaller

                # Check if click is near diagonal (y = -x + 1)
                if abs((1 - norm_x) - norm_y) < tolerance:
                    # Click is near diagonal - restore both
                    self.restore_data(selection=True, weight_node=self.current_weight_node)
                # Check if click is above diagonal (green area - top right)
                elif norm_y < (1 - norm_x):
                    # Upper-right area - restore only weights
                    self.restore_data(selection=False, weight_node=self.current_weight_node)
                else:
                    # Lower-left area - restore only selection
                    self.restore_data(selection=True, weight_node=None)
            else:
                # Single color button - normal restore
                self.restore_data()

        elif event.button() == QtCore.Qt.RightButton:
            self._handle_right_click()

    def mouseMoveEvent(self, event: QtCore.QEvent):
        """Update tooltip based on which diagonal area mouse is over"""
        if self.storage["weights"] and self.storage["selection"]:
            # Calculate normalized positions
            norm_x = event.pos().x() / self.width()
            norm_y = event.pos().y() / self.height()
            tolerance = 0.1

            # Update tooltip based on position
            if abs((1 - norm_x) - norm_y) < tolerance:
                self.setToolTip("Restore Both")
                self.setCursor(QtCore.Qt.PointingHandCursor)
            elif norm_y < (1 - norm_x):
                self.setToolTip("Restore Weights Only")
                self.setCursor(QtCore.Qt.PointingHandCursor)
            else:
                self.setToolTip("Restore Selection Only")
                self.setCursor(QtCore.Qt.PointingHandCursor)
        else:
            self.setCursor(QtCore.Qt.ArrowCursor)
            self.setToolTip("")

    def enterEvent(self, event: QtCore.QEvent):
        """Show zone tooltips when mouse enters button"""
        if self.storage["weights"] and self.storage["selection"]:
            self.setToolTip(
                "Left: Restore Selection Only\n"
                "Middle: Restore Both\n"
                "Right: Restore Weights Only"
            )

    def leaveEvent(self, event: QtCore.QEvent):
        """Reset tooltip when mouse leaves"""
        self.setToolTip("")

    def _handle_left_click(self):
        """Handle left click - restore stored data"""
        if self.storage['weights'] or self.storage['selection']:
            self.restore_data()

    def _handle_right_click(self):
        """Handle right click - show context menu"""
        # init actions
        add_action, sub_action, intersect = None, None, None
        mult_action, div_action = None, None

        # Create Menu
        menu = QtWidgets.QMenu(self)

        # Add actions
        store_action = menu.addAction("Store Current Data")
        only_selection = menu.addAction("Store Only Selection")
        only_weights = menu.addAction("Store Only Weights")
        clear_action = menu.addAction("Clear Storage")
        # TODO add a separator for operations : add, intersect, substract
        if self.storage['weights'] or self.storage['selection']:
            menu.addSeparator()
            add_action = menu.addAction("Add Op")
            sub_action = menu.addAction("Substract Op")
            intersect = menu.addAction("Intersect Op")
        if self.storage['weights']:
            mult_action = menu.addAction("Mult Op")
            div_action = menu.addAction("Divide Op")

        # Enable/disable actions based on state
        clear_action.setEnabled(bool(self.storage['weights'] or self.storage['selection']))

        # Show menu and handle selection
        action = menu.exec_(QtGui.QCursor.pos())
        if action == store_action:
            self.store_current_data()

        elif action == clear_action:
            self.clear_storage()

        elif action == only_selection:
            self.store_current_data(weight_store=False)
        elif action == only_weights:
            self.store_current_data(sel_store=False)

        elif action == add_action:
            self.combine_data(mode="add")
        elif action == sub_action:
            self.combine_data(mode="sub")
        elif action == intersect:
            self.combine_data(mode="intersect")

    def store_current_data(self, weight_node:str=None, sel_store = True, weight_store=True):
        """Store current weights and selection"""
        if not weight_node:
            node, _attr, _type = get_current_artisan_map()
            if node:
                weight_node = f"{node}.{_attr}"
        logger.debug(f"Storing the node data :  {weight_node}")
        try:
            if sel_store:
                logger.debug(f"Storing : Get the selection")
                self._get_selection_for_storage(weight_node)
            if weight_node and weight_store:
                logger.debug(f"Storing : Get the Weight")
                self._get_weights_for_storage(weight_node)

            self._update_button_state(True)
            logger.info("Data stored successfully")
        except Exception as e:
            logger.error(f"Failed to store data: {e}")

    def _get_selection_for_storage(self, weight_node=None):
        sel = cmds.ls(sl=True)
        _compo_type = component_in_list(sel)
        if _compo_type != "vtx" and weight_node:
            sel = cmds.polyListComponentConversion(sel, tv=True)
            _compo_type = "vtx"
        obj_list = list(set([o.split(".")[0] for o in sel]))
        self.storage["selection"] = {}
        if not _compo_type:
            obj_list = sel[:]
        for o in obj_list:
            self.storage["selection"][o] = extract_id([s for s in sel if s.startswith(o)])
        self.storage["component_type"] = _compo_type

    def _get_weights_for_storage(self, weight_node):
        node, attr = weight_node.rsplit('.', 1)
        _type = cmds.nodeType(node)
        weights = cmds.getAttr(weight_node)
        self.storage["weight_node"] = weight_node
        self.storage["weight_type"] = _type
        self.storage["weights"] = weights

    def combine_data(self, mode="add"):
        if self.storage['weights']:
            weight_node = self.current_weight_node
            new_weights = cmds.getAttr(weight_node)
            if mode == "add":
                self.storage["weights"] = list(
                                            set(self.storage["weights"]) | set(new_weights)
                                            )
            if mode == "sub":
                self.storage["weights"] = list(
                                            set(self.storage["weights"]) - set(new_weights)
                                            )
            if mode == "intersect":
                self.storage["weights"] = list(
                                            set(self.storage["weights"]) & set(new_weights)
                                            )
            if mode == "multiply":
                self.storage["weights"] = (np.array(self.storage["weights"]) * np.array(new_weights)).tolist()

            if mode == "divide":
                self.storage["weights"] = (np.array(self.storage["weights"]) / np.array(new_weights)).tolist()

        if self.storage['selection']:
            sel = cmds.ls(sl=True)
            _compo_type = component_in_list(sel)
            if _compo_type != self.storage["component_type"]:
                sel = cmds.polyListComponentConversion(sel, tv=True)
            obj_list = list(set([o.split(".")[0] for o in sel]))
            for o in obj_list:
                if o in self.storage["selection"]:
                    # Update existing selection using set union
                    new_ids = extract_id([s for s in sel if s.startswith(o)])
                    if mode == "add":
                        self.storage["selection"][o] = list(
                                                            set(self.storage["selection"][o]) | set(new_ids)
                                                            )
                    if mode == "sub":
                        self.storage["selection"][o] = list(
                                                            set(self.storage["selection"][o]) - set(new_ids)
                                                            )
                    if mode == "intersect":
                        self.storage["selection"][o] = list(
                                                            set(self.storage["selection"][o]) & set(new_ids)
                                                            )
                else:
                    if mode =="add":
                        self.storage["selection"][o] = extract_id([s for s in sel if s.startswith(o)])
                    if mode == "intersect":
                        self.storage["selection"][o] = []

            self._set_selection()

    def restore_data(self, selection=True):
        """Restore stored weights and selection
        selection is always the same meshes
        weight_node, the weight list can be retargeted on the current selected maps/weightList"""
        try:
            if self.storage['weights'] or self.storage['selection']:
                if selection:
                    self._set_selection()

                if self.current_weight_node:
                    self._set_weights()
                logger.info("Data restored successfully")
        except Exception as e:
            logger.error(f"Failed to restore data: {e}")

    def _set_selection(self):
        rsel = []
        for mesh, ids in self.storage["selection"].items():
            if self.storage["component_type"]:
                if ids:
                    cmpnt_type = self.storage["component_type"]
                    rsel += [f"{mesh}.{cmpnt_type}[{id}]" for id in create_maya_ranges(ids)]
                else:
                    rsel.append(mesh)
            else:
                rsel.append(mesh)
        cmds.select(rsel, r=True)

    def _set_weights(self, restore=False):
        # In case of restore : let's use the original map
        weight_node = self.storage["weight_node"]
        # The general case is to set the weights in the "current context"
        # which is set with self._current_weight_node
        # first case : it is not None because the ui set it
        # second case, it is None and we get the current Artisan edit
        _cur_node = self.current_weight_node
        if not restore and _cur_node:
            weight_node = _cur_node


        _type = self.storage["weight_type"]
        if weight_node:
            node, attr = weight_node.rsplit('.', 1)
            if _type in ["nCloth", "nRigid"]:
                set_nucx_map_data(node, attr, self.storage["weights"])
            else:
                if attr:
                    _type = attr
                else:
                    _type = "deformer" if _type != "blendshape" else _type
                set_deformer_weights(node, self.storage["weights"], _type)

    def clear_storage(self):
        """Clear stored data"""
        self.storage = {
            'weights': [],
            'selection': {},
            'weight_node': "",
            "weight_type": "",
        }
        self._update_button_state(False)

    @property
    def current_weight_node(self):
        if not self._current_weight_node:
            _node, _attr, _type = get_current_artisan_map()
            return f"{_node}.{_attr}"
        else:
            return self._current_weight_node

    @current_weight_node.setter
    def current_weight_node(self, node:str):
        """should be a deformer or a ncloth map type
        can handle node.attr or just the node"""
        self._current_weight_node = node




    def _update_button_state(self, has_data: bool):
        """Update button appearance based on storage state"""
        if has_data:
            if self.storage["weights"] == 'weights':
                self.setStyleSheet("""
                    QPushButton {
                        background-color: rgb(70, 110, 85);
                        border: none;
                        border-radius: 2px;
                        padding: 5px;
                        color: white;
                    }
                    QPushButton:hover {
                        background-color: rgb(80, 120, 95);
                    }
                """)
            elif self.storage["weights"] and self.storage["selection"]:
                self.setStyleSheet("""
                    QPushButton {
                        background: qlineargradient(
                            spread:pad, 
                            x1:0, y1:0,      /* Start point (top-left) */
                            x2:1, y2:1,      /* End point (bottom-right) */
                            stop:0 rgb(70, 110, 85),    /* First color */
                            stop:0.5 rgb(70, 110, 85),  /* First color extends to middle */
                            stop:0.51 rgb(194, 177, 109), /* Second color starts */
                            stop:1 rgb(194, 177, 109)   /* Second color */
                        );
                        border: none;
                        border-radius: 2px;
                        padding: 5px;
                        color: white;
                    }
                    QPushButton:hover {
                        background: qlineargradient(
                            spread:pad,
                            x1:0, y1:0,
                            x2:1, y2:1,
                            stop:0 rgb(80, 120, 95),
                            stop:0.5 rgb(80, 120, 95),
                            stop:0.51 rgb(204, 187, 119),
                            stop:1 rgb(204, 187, 119)
                        );
                    }
                """)
            else:
                self.setStyleSheet("""
                    QPushButton {
                        background-color: rgb(194, 177, 109);
                        border: none;
                        border-radius: 2px;
                        padding: 5px;
                        color: white;
                    }
                    QPushButton:hover {
                        background-color: rgb(204, 187, 119);
                    }
                """)
        else:
            self.setStyleSheet("""
                QPushButton {
                    background-color: rgb(128, 128, 128);
                    border: none;
                    border-radius: 2px;
                    padding: 5px;
                    color: white;
                }
                QPushButton:hover {
                    background-color: rgb(140, 140, 140);
                }
            """)