"""
wgt_attr_editor.py - DynForge guide attribute editor (right panel, "Attributes" tab).

Shown only when a guide is selected (otherwise a placeholder is displayed). Every
widget edits the selected guide in place and the values live on the guide, so
swapping selection restores them. Editing also emits params_edited so the main
window can remember the last-used settings as the default for the next guide.

Guide points group - one way to build every guide, whatever the artist picks
(edges, an edge loop, faces, verts or an object: the point lands on the centroid
of the selection, which is also recorded as the point's source):
- "Create as" combo: new points are locators or joints
- a (Point | Snap | Del) tree of the guide points, reorderable with Move up/down;
  each row's "snap" button snaps that point to the current selection centroid
- a template "add ..." row whose "target" button creates a new point at the
  current selection centroid (points one by one)
- "From edge/face strip": replace the points with one per edge midpoint / face
  centroid of the selected edge column / face strip (a whole curve at once)
"""

from __future__ import annotations

from functools import partial

from dw_maya.DynForge.forge_cmds.compat import (
    QtWidgets, Qt, Signal,
)
from dw_maya.DynForge.wgt_base import DynForgeWidgetBase
from dw_logger import get_logger

logger = get_logger()


_UP_AXES = ("y", "x", "z", "-y", "-x", "-z")
_POINT_TYPES = ("locator", "joint")
_MIN_CV = 4   # a degree-3 curve needs at least 4 CVs
_LOC_ROLE = Qt.UserRole + 1


class GuideAttrEditor(DynForgeWidgetBase):
    """Attribute editor for the selected guide."""

    # Emitted whenever the loaded guide's parameters are edited.
    params_edited = Signal(object)

    def __init__(self,
                 hub,
                 parent=None,) -> None:
        super().__init__(hub, parent)
        self._guide = None
        self._build_ui()

    # -- UI ---------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._stack = QtWidgets.QStackedWidget()
        outer.addWidget(self._stack)

        # Page 0: placeholder shown when nothing is selected.
        placeholder = QtWidgets.QLabel("Select or create a guide to edit it.")
        placeholder.setAlignment(Qt.AlignCenter)
        placeholder.setWordWrap(True)
        placeholder.setStyleSheet("color: #888;")
        self._stack.addWidget(placeholder)

        # Page 1: the actual editor.
        self._stack.addWidget(self._build_content())

    def _build_content(self) -> QtWidgets.QWidget:
        content = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(content)

        # Common build parameters
        params_box = QtWidgets.QGroupBox("Parameters")
        form = QtWidgets.QFormLayout(params_box)

        self._n_joints = QtWidgets.QSpinBox()
        self._n_joints.setRange(2, 200)
        self._n_joints.setValue(10)
        form.addRow("Joints", self._n_joints)

        # One joint per guide point, placed exactly on it.
        self._exact = QtWidgets.QCheckBox("Exact number of guide points")
        self._exact.setToolTip(
            "Build one joint per guide point, exactly on it. "
            "The joint count follows the points and the curve becomes data-only.")
        form.addRow("", self._exact)

        self._up_axis = QtWidgets.QComboBox()
        self._up_axis.addItems(_UP_AXES)
        form.addRow("Up axis", self._up_axis)

        self._flip = QtWidgets.QCheckBox("Flip direction (root <-> tip)")
        form.addRow("", self._flip)
        layout.addWidget(params_box)

        # Guide points
        self._loc_box = QtWidgets.QGroupBox("Guide points")
        loc_layout = QtWidgets.QVBoxLayout(self._loc_box)

        type_pick = QtWidgets.QHBoxLayout()
        type_pick.addWidget(QtWidgets.QLabel("Create as"))
        self._point_type = QtWidgets.QComboBox()
        self._point_type.addItems([t.capitalize() for t in _POINT_TYPES])
        type_pick.addWidget(self._point_type)
        type_pick.addSpacing(12)
        type_pick.addWidget(QtWidgets.QLabel("Curve CVs"))
        self._cv_count = QtWidgets.QSpinBox()
        self._cv_count.setRange(_MIN_CV, 200)
        self._cv_count.setValue(6)
        self._cv_count.setToolTip(
            "Minimum CV count of the curve built through the points: a few points are "
            "resampled up to it so the curve stays editable, a dense edge column keeps "
            "one CV per point. Follows the joint count by default.")
        type_pick.addWidget(self._cv_count)
        type_pick.addStretch(1)
        loc_layout.addLayout(type_pick)

        self._loc_tree = QtWidgets.QTreeWidget()
        self._loc_tree.setColumnCount(3)
        self._loc_tree.setHeaderLabels(["Point", "Snap", "Del"])
        self._loc_tree.setRootIsDecorated(False)
        self._loc_tree.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self._loc_tree.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        header = self._loc_tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        loc_layout.addWidget(self._loc_tree, stretch=1)
        self._count_label = QtWidgets.QLabel("")
        self._count_label.setStyleSheet("color: #888;")
        loc_layout.addWidget(self._count_label)

        order_row = QtWidgets.QHBoxLayout()
        self._strip_btn = QtWidgets.QPushButton("From edge/face strip")
        self._strip_btn.setToolTip(
            "Replace the points with one per edge midpoint / face centroid of the selected "
            "edge column (or loop) / face strip, ordered along it. Every point is registered, "
            "only the Handles get a locator.")
        order_row.addWidget(self._strip_btn)
        order_row.addWidget(QtWidgets.QLabel("Handles"))
        self._handles = QtWidgets.QSpinBox()
        self._handles.setRange(0, 99)
        self._handles.setValue(3)
        self._handles.setSpecialValueText("all")
        self._handles.setToolTip(
            "How many strip points get a locator: 3 = first / middle / last, spread by index; "
            "all = one locator per point. Moving a handle drags the hidden points around it.")
        order_row.addWidget(self._handles)
        self._up_btn   = QtWidgets.QPushButton("Move up")
        self._down_btn = QtWidgets.QPushButton("Move down")
        order_row.addWidget(self._up_btn)
        order_row.addWidget(self._down_btn)
        order_row.addStretch(1)
        loc_layout.addLayout(order_row)

        layout.addWidget(self._loc_box, stretch=1)
        layout.addStretch(0)

        # Connections
        self._n_joints.valueChanged.connect(self._sync_cv_to_joints)
        self._n_joints.valueChanged.connect(self._apply_to_guide)
        self._up_axis.currentIndexChanged.connect(self._apply_to_guide)
        self._flip.toggled.connect(self._apply_to_guide)
        self._cv_count.valueChanged.connect(self._apply_to_guide)
        self._exact.toggled.connect(self._on_exact_toggled)
        self._point_type.currentIndexChanged.connect(self._on_point_type_changed)

        self._strip_btn.clicked.connect(self._on_points_from_strip)
        self._handles.valueChanged.connect(self._on_handles_changed)
        self._up_btn.clicked.connect(partial(self._move_selected, -1))
        self._down_btn.clicked.connect(partial(self._move_selected, +1))

        return content

    # -- Public -----------------------------------------------------------

    def apply_defaults(self,
                       defaults: dict,) -> None:
        """
        Seed the editor widgets from a saved-defaults dict (used so a freshly
        created blank guide inherits the last-used settings). No guide is loaded.
        """
        self._guide = None
        self._n_joints.setValue(defaults.get("n_joints", 10))
        idx = self._up_axis.findText(defaults.get("up_axis", "y"))
        if idx >= 0:
            self._up_axis.setCurrentIndex(idx)
        self._flip.setChecked(False)   # flip is a per-fix correction, never default-on
        self._set_point_type(defaults.get("point_type", "locator"))
        self._cv_count.setValue(defaults.get("cv_count", 6))   # after joints (joints auto-syncs it)
        self._exact.setChecked(bool(defaults.get("exact_points", False)))
        self._handles.setValue(int(defaults.get("strip_handles", 3)))
        self._update_exact_enabled()

    def load_guide(self,
                   guide,) -> None:
        """Populate from the selected guide, or show the placeholder if None."""
        self._guide = None   # mute change handlers while we set widgets
        if guide is None:
            self._loc_tree.clear()
            self._stack.setCurrentIndex(0)
            return

        self._n_joints.setValue(getattr(guide, "n_joints", 10))
        idx = self._up_axis.findText(getattr(guide, "up_axis", "y"))
        if idx >= 0:
            self._up_axis.setCurrentIndex(idx)
        self._flip.setChecked(bool(getattr(guide, "flip", False)))
        self._set_point_type(getattr(guide, "point_type", "locator"))
        # Set CVs last: changing joints above auto-syncs it, so restore the
        # guide's own value afterwards.
        self._cv_count.setValue(getattr(guide, "cv_count", 6))
        self._exact.setChecked(bool(getattr(guide, "exact_points", False)))
        self._handles.setValue(int(getattr(guide, "strip_handles", 3)))

        self._guide = guide
        self._refresh_locator_list()
        self._update_exact_enabled()
        self._stack.setCurrentIndex(1)

    def reload_if_current(self,
                          guide,) -> None:
        """Re-read `guide` into the editor if it is the one currently shown."""
        if guide is self._guide:
            self.load_guide(guide)

    # -- Point type / exact -----------------------------------------------

    def _set_point_type(self,
                        point_type: str,) -> None:
        idx = self._point_type.findText(point_type.capitalize())
        if idx >= 0:
            self._point_type.setCurrentIndex(idx)

    def _update_exact_enabled(self) -> None:
        """In exact mode the count follows the points, so lock Joints and CVs."""
        exact = self._exact.isChecked()
        self._n_joints.setEnabled(not exact)
        self._cv_count.setEnabled(not exact)

    def _on_exact_toggled(self,
                          *args,) -> None:
        self._update_exact_enabled()
        if self._guide is not None and hasattr(self._guide, "set_build_params"):
            self._guide.set_build_params(exact_points=self._exact.isChecked())
            self.params_edited.emit(self._guide)

    def _on_point_type_changed(self,
                               *args,) -> None:
        if self._guide is None:
            return
        if hasattr(self._guide, "set_point_type"):
            self._guide.set_point_type(self._point_type.currentText().lower())
        self._refresh_locator_list()   # template label follows the type
        self.params_edited.emit(self._guide)

    # -- Parameter edits --------------------------------------------------

    def _sync_cv_to_joints(self,
                           joints: int,) -> None:
        """Curve CVs follow the joint count by default (>= 6); user can re-tweak."""
        self._cv_count.setValue(max(joints, 6))

    def _apply_to_guide(self,
                        *args,) -> None:
        """Live-apply parameter widgets to the loaded guide (no rebuild)."""
        if self._guide is None:
            return
        if hasattr(self._guide, "set_build_params"):
            self._guide.set_build_params(
                n_joints = self._n_joints.value(),
                up_axis  = self._up_axis.currentText(),
                flip     = self._flip.isChecked(),
                cv_count = self._cv_count.value(),
            )
        self.params_edited.emit(self._guide)

    def _on_handles_changed(self,
                            value: int,) -> None:
        """Handle count for the next 'From edge/face strip' (the current strip is kept)."""
        if self._guide is not None and hasattr(self._guide, "set_build_params"):
            self._guide.set_build_params(strip_handles=value)
            self.params_edited.emit(self._guide)

    # -- Locator tree -----------------------------------------------------

    def _refresh_locator_list(self) -> None:
        self._loc_tree.clear()
        self._count_label.setText("")
        if self._guide is None:
            return
        n_points = len(getattr(self._guide, "point_records", []) or [])
        n_nodes = len(getattr(self._guide, "points", []) or [])
        if n_points and n_points != n_nodes:
            self._count_label.setText(f"{n_points} points, {n_nodes} locator handle(s) - "
                                      "moving a handle drags the hidden points around it")

        for node in getattr(self._guide, "points", []) or []:
            item = QtWidgets.QTreeWidgetItem([node.split("|")[-1], ""])
            item.setData(0, _LOC_ROLE, node)
            self._loc_tree.addTopLevelItem(item)
            snap_btn = QtWidgets.QPushButton("snap")
            snap_btn.setMaximumWidth(56)
            snap_btn.setToolTip("Snap this point to the current selection center.")
            snap_btn.clicked.connect(partial(self._on_snap_row, node))
            self._loc_tree.setItemWidget(item, 1, snap_btn)
            del_btn = QtWidgets.QPushButton("x")
            del_btn.setMaximumWidth(28)
            del_btn.setToolTip("Delete this point.")
            del_btn.clicked.connect(partial(self._on_delete_row, node))
            self._loc_tree.setItemWidget(item, 2, del_btn)

        # Template "add ..." row: its target button creates a point at selection.
        type_label = self._point_type.currentText().lower()
        template = QtWidgets.QTreeWidgetItem([f"add {type_label}", ""])
        template.setData(0, _LOC_ROLE, None)
        font = template.font(0)
        font.setItalic(True)
        template.setFont(0, font)
        self._loc_tree.addTopLevelItem(template)
        target_btn = QtWidgets.QPushButton("target")
        target_btn.setMaximumWidth(56)
        target_btn.setToolTip("Create a new point at the current selection center.")
        target_btn.clicked.connect(self._on_add_point)
        self._loc_tree.setItemWidget(template, 1, target_btn)

    def _select_locator_row(self,
                            index: int,) -> None:
        item = self._loc_tree.topLevelItem(index)
        if item is not None:
            self._loc_tree.setCurrentItem(item)

    def _move_selected(self,
                       offset: int,) -> None:
        item = self._loc_tree.currentItem()
        if item is None or self._guide is None:
            return
        node = item.data(0, _LOC_ROLE)
        if node is None:   # the template row, not movable
            return
        locators = list(getattr(self._guide, "points", []))
        if node not in locators:
            return
        src = locators.index(node)
        dst = src + offset
        if dst < 0 or dst >= len(locators):
            return
        locators[src], locators[dst] = locators[dst], locators[src]
        if hasattr(self._guide, "reorder_points"):
            try:
                self._guide.reorder_points(locators)
            except ValueError as e:
                QtWidgets.QMessageBox.information(self, "DynForge", str(e))
                return
        self._refresh_locator_list()
        self._select_locator_row(dst)

    def _on_add_point(self) -> None:
        if self._guide is None or not hasattr(self._guide, "add_point"):
            return
        try:
            self._guide.add_point()
        except Exception as e:
            logger.warning(f"DynForge: add point failed: {e}")
            QtWidgets.QMessageBox.warning(self, "DynForge", f"Add point failed:\n{e}")
            return
        self._reflect_joint_count()
        self._refresh_locator_list()
        self.params_edited.emit(self._guide)   # the point may have pre-registered a skin

    def _on_points_from_strip(self) -> None:
        if self._guide is None or not hasattr(self._guide, "points_from_strip"):
            return
        if self._guide.points or self._guide.status.value == "built":
            reply = QtWidgets.QMessageBox.question(
                self, "DynForge",
                f"Replace the points of {self._guide.name!r}? Its curve and chain are removed "
                "too, Build again afterwards.",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
            if reply != QtWidgets.QMessageBox.Yes:
                return
        try:
            self._guide.points_from_strip()
        except Exception as e:
            logger.warning(f"DynForge: points from strip failed: {e}")
            QtWidgets.QMessageBox.warning(self, "DynForge", f"Points from strip failed:\n{e}")
            return
        self._refresh_locator_list()
        self.params_edited.emit(self._guide)

    def _reflect_joint_count(self) -> None:
        """
        Mirror the guide's n_joints into the spin (joint points drive it) without
        firing the joints->CVs auto-sync, which would overwrite a tweaked CV.
        """
        if self._guide is None:
            return
        self._n_joints.blockSignals(True)
        self._n_joints.setValue(getattr(self._guide, "n_joints", self._n_joints.value()))
        self._n_joints.blockSignals(False)

    def _on_snap_row(self,
                     node: str,) -> None:
        if self._guide is None or not hasattr(self._guide, "snap_point"):
            return
        try:
            self._guide.snap_point(node)
        except Exception as e:
            logger.warning(f"DynForge: snap point failed: {e}")
            QtWidgets.QMessageBox.warning(self, "DynForge", f"Snap failed:\n{e}")
            return
        self.params_edited.emit(self._guide)   # the snap may have pre-registered a skin

    def _on_delete_row(self,
                       node: str,) -> None:
        if self._guide is None or not hasattr(self._guide, "delete_point"):
            return
        try:
            self._guide.delete_point(node)
        except Exception as e:
            logger.warning(f"DynForge: delete point failed: {e}")
            QtWidgets.QMessageBox.warning(self, "DynForge", f"Delete failed:\n{e}")
            return
        self._reflect_joint_count()
        self._refresh_locator_list()