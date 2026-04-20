try:
    from PySide6 import QtCore, QtGui, QtWidgets
    from PySide6.QtCore import Qt, Signal, Slot
    from shiboken6 import wrapInstance
except ImportError:
    # Fallback for older Maya versions shipping PySide2
    from PySide2 import QtCore, QtGui, QtWidgets
    from PySide2.QtCore import Qt, Signal, Slot
    from shiboken2 import wrapInstance

from typing import List, Optional, Dict, Any
from dw_logger import get_logger
from dw_maya.dw_maya_utils import extract_id, component_in_list, create_maya_ranges
from maya import cmds
from dw_maya.dw_paint import get_current_artisan_map
from dw_maya.dw_decorators.dw_undo import singleUndoChunk
import numpy as np

logger = get_logger()


def _resolve_source_for_node(node: str, attr: str):
    """Build a WeightSource for *node* using resolve_weight_sources.

    Tries deformers first, then nucleus maps.  Returns ``None`` when
    the node cannot be wrapped.
    """
    from dw_maya.dw_paint.weight_source import resolve_weight_sources

    # We need the mesh connected to this node to call resolve_weight_sources
    node_type = cmds.nodeType(node)

    # Deformer path — query the geometry driven by this deformer
    if node_type in ("nCloth", "nRigid"):
        mode = "nucleus"  # type: str
    else:
        mode = "deformer"  # type: str

    meshes = []
    if mode == "deformer":
        shapes = cmds.deformer(node, query=True, geometry=True) or []
        for sh in shapes:
            parents = cmds.listRelatives(sh, parent=True, fullPath=True)
            meshes.append(parents[0] if parents else sh)
    else:
        # nucleus — try to find the mesh via inputMesh
        from dw_maya.dw_nucleus_utils.dw_core import get_mesh_from_nucx_node
        mesh = get_mesh_from_nucx_node(node)
        if mesh:
            meshes = [mesh]

    for mesh in meshes:
        sources = resolve_weight_sources(mesh, mode=mode)
        for src in sources:
            if src.node_name == node:
                # Activate the right map
                available = src.available_maps()
                if attr in available:
                    src.use_map(attr)
                elif len(available) == 1:
                    src.use_map(available[0])
                logger.debug(f"_resolve_source_for_node: resolved {node}.{attr} -> {src}")
                return src

    logger.debug(f"_resolve_source_for_node: could not resolve {node}.{attr}")
    return None


class VtxStorageButton(QtWidgets.QPushButton):
    """A button that can store and restore vertex weights and selections.

    Signals:
        remove_requested(): Emitted when the user chooses "Remove this slot"
                            from the right-click context menu.
    """

    remove_requested = QtCore.Signal()

    # Zone constants
    ZONE_WEIGHTS = "weights"
    ZONE_SELECTION = "selection"
    ZONE_BOTH = "both"
    ZONE_NONE = "none"

    def __init__(self):
        """Initialize the storage button."""
        super().__init__()
        self.btn_type = None
        self._current_weight_node = None
        # Optional WeightSource — bypasses cmds.getAttr for complex attr paths
        self.weight_source = None
        self.storage: Dict[str, Any] = {
            'weights': [],
            'selection': {},
            'weight_node': None,
            'weight_type': None,
            'component_type': None,
        }
        self._hovered_zone = self.ZONE_NONE
        self.setMouseTracking(True)
        self._setup_ui()

    # ------------------------------------------------------------------
    # Public accessors for stored data
    # ------------------------------------------------------------------

    @property
    def stored_weights(self) -> list:
        """Return the list of stored vertex weights (empty if none stored)."""
        return self.storage.get('weights') or []

    @property
    def stored_selection(self) -> dict:
        """Return the stored selection dict (empty if none stored)."""
        return self.storage.get('selection') or {}

    def _setup_ui(self):
        """Setup the button's UI."""
        self.setStyleSheet(self._make_stylesheet(False, False))

    # ------------------------------------------------------------------
    # Zone helpers
    # ------------------------------------------------------------------

    def get_click_zone(self, pos: QtCore.QPoint, tolerance: float = 0.5) -> str:
        """Return which zone a position falls into on the diagonal-split button.

        Args:
            pos: Position relative to the button.
            tolerance: Size of the middle zone around the diagonal.

        Returns:
            One of ZONE_WEIGHTS, ZONE_SELECTION, or ZONE_BOTH.
        """
        if not (self.storage["weights"] and self.storage["selection"]):
            return self.ZONE_BOTH

        norm_x = pos.x() / self.width()
        norm_y = pos.y() / self.height()

        if abs((1 - norm_x) - norm_y) < tolerance:
            return self.ZONE_BOTH
        elif norm_y < (1 - norm_x):
            return self.ZONE_WEIGHTS
        else:
            return self.ZONE_SELECTION

    # ------------------------------------------------------------------
    # Mouse / paint events
    # ------------------------------------------------------------------

    def mousePressEvent(self, event: QtCore.QEvent):
        """Handle mouse press events based on diagonal zone."""
        if event.button() == QtCore.Qt.LeftButton:
            zone = self.get_click_zone(event.pos())
            logger.debug(f"mousePressEvent: zone={zone}")
            if zone == self.ZONE_BOTH:
                self.restore_data(selection=True)
            elif zone == self.ZONE_WEIGHTS:
                self.restore_data(selection=False)
            elif zone == self.ZONE_SELECTION:
                self.restore_data(selection=True, weights=False)

        elif event.button() == QtCore.Qt.RightButton:
            self._handle_right_click(event)

    def mouseMoveEvent(self, event: QtCore.QEvent):
        """Update tooltip and hover zone based on mouse position."""
        zone = self.get_click_zone(event.pos(), tolerance=0.1)
        if self.storage["weights"] and self.storage["selection"]:
            tooltip_map = {
                self.ZONE_BOTH: "Restore Both",
                self.ZONE_WEIGHTS: "Restore Weights Only",
                self.ZONE_SELECTION: "Restore Selection Only",
            }
            self.setToolTip(tooltip_map.get(zone, ""))
            self.setCursor(QtCore.Qt.PointingHandCursor)
        else:
            self.setCursor(QtCore.Qt.ArrowCursor)
            self.setToolTip("")

        if zone != self._hovered_zone:
            self._hovered_zone = zone
            self.update()

    def enterEvent(self, event: QtCore.QEvent):
        """Show zone tooltips when mouse enters button."""
        if self.storage["weights"] and self.storage["selection"]:
            self.setToolTip(
                "Top-left: Restore Weights Only\n"
                "Middle: Restore Both\n"
                "Bottom-right: Restore Selection Only"
            )

    def leaveEvent(self, event: QtCore.QEvent):
        """Reset tooltip and hover highlight when mouse leaves."""
        self.setToolTip("")
        if self._hovered_zone != self.ZONE_NONE:
            self._hovered_zone = self.ZONE_NONE
            self.update()

    def paintEvent(self, event):
        """Draw the button then overlay a translucent highlight on the hovered zone.

        The highlight is painted *on top* of the stylesheet-rendered background
        so the diagonal gradient is preserved.
        """
        # Let Qt draw the stylesheet background first
        super().paintEvent(event)

        # Only draw highlight when we have a dual-zone button
        if self._hovered_zone == self.ZONE_NONE:
            return
        if not (self.storage["weights"] and self.storage["selection"]):
            return

        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        # Outline pen — white works on both green and ochre backgrounds
        pen = QtGui.QPen(QtGui.QColor(255, 255, 255, 180))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.setBrush(QtCore.Qt.NoBrush)

        w = self.width()
        h = self.height()

        if self._hovered_zone == self.ZONE_WEIGHTS:
            # Top-left triangle (green zone)
            poly = QtGui.QPolygonF([
                QtCore.QPointF(0, 0),
                QtCore.QPointF(w, 0),
                QtCore.QPointF(0, h),
            ])
            painter.drawPolygon(poly)
        elif self._hovered_zone == self.ZONE_SELECTION:
            # Bottom-right triangle (tan zone)
            poly = QtGui.QPolygonF([
                QtCore.QPointF(w, 0),
                QtCore.QPointF(w, h),
                QtCore.QPointF(0, h),
            ])
            painter.drawPolygon(poly)
        elif self._hovered_zone == self.ZONE_BOTH:
            # Slight fill + border for the "restore both" case
            painter.setBrush(QtGui.QColor(255, 255, 255, 25))
            painter.drawRect(1, 1, w - 2, h - 2)

        painter.end()

    # ------------------------------------------------------------------
    # Right-click menu
    # ------------------------------------------------------------------

    def _handle_left_click(self):
        """Handle left click - restore stored data"""
        if self.storage['weights'] or self.storage['selection']:
            self.restore_data()

    def _handle_right_click(self, event):
        """Handle right click - show context menu"""
        # init actions
        add_action, sub_action, intersect = None, None, None
        mult_action, div_action = None, None

        # Create Menu
        menu = QtWidgets.QMenu(self)

        # Header shows the detected context
        cur_node = self.current_weight_node
        if cur_node:
            header_text = f"[{cur_node}]"
        else:
            header_text = "storage (no map detected)"
        header = menu.addAction(header_text)
        header.setEnabled(False)

        # Show stored data info if any
        if self.storage.get('weight_node'):
            stored_info = menu.addAction(f"stored: {self.storage['weight_node']}")
            stored_info.setEnabled(False)

        menu.addSeparator()

        # Add actions
        store_action = menu.addAction("Store Current Data")
        only_selection = menu.addAction("Store Only Selection")
        only_weights = menu.addAction("Store Only Weights")
        clear_action = menu.addAction("Clear Storage")
        if self.storage['weights'] or self.storage['selection']:
            menu.addSeparator()
            add_action = menu.addAction("Add Op")
            sub_action = menu.addAction("Remove Op")
            intersect = menu.addAction("Intersect Op")
        if self.storage['weights']:
            menu.addSeparator()
            mult_action = menu.addAction("Mult Op Weight")
            div_action = menu.addAction("Divide Op Weight")

        clear_action.setEnabled(bool(self.storage['weights'] or self.storage['selection']))

        menu.addSeparator()
        remove_action = menu.addAction("Remove this slot")

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
        elif action == mult_action:
            self.combine_data(mode="multiply")
        elif action == div_action:
            self.combine_data(mode="divide")
        elif action == remove_action:
            self.remove_requested.emit()

    # ------------------------------------------------------------------
    # Store
    # ------------------------------------------------------------------

    def store_current_data(self, weight_node: str = None, weight_source=None, sel_store=True, weight_store=True):
        """Store current weights and selection.

        Args:
            weight_node: Optional explicit node.attr string.
            weight_source: Optional WeightSource instance.
            sel_store: Whether to capture the current vertex selection.
            weight_store: Whether to capture the current weights.
        """
        if weight_source is not None:
            self.weight_source = weight_source
        if not weight_node:
            # Try artisan context first (active paint session)
            node, _attr, _type = get_current_artisan_map()
            if node:
                weight_node = f"{node}.{_attr}"
            else:
                # Fallback to the node set by the parent UI (e.g. bq_slimfast)
                weight_node = self.current_weight_node
        logger.debug(f"store_current_data: weight_node={weight_node}, "
                     f"weight_source={self.weight_source}, "
                     f"sel_store={sel_store}, weight_store={weight_store}")
        try:
            if sel_store:
                logger.debug("store_current_data: capturing selection...")
                self._get_selection_for_storage(weight_node)
                logger.debug(f"store_current_data: selection={self.storage['selection']}, "
                             f"component_type={self.storage.get('component_type')}")
            if weight_node and weight_store:
                logger.debug("store_current_data: capturing weights...")
                self._get_weights_for_storage(weight_node)
                n = len(self.storage['weights']) if self.storage['weights'] else 0
                logger.debug(f"store_current_data: stored {n} weights, "
                             f"weight_type={self.storage['weight_type']}")

            self._update_button_state(True)
            logger.info(f"Data stored successfully — node={self.storage.get('weight_node')}, "
                        f"weights={len(self.storage.get('weights') or [])}, "
                        f"selection keys={list(self.storage.get('selection', {}).keys())}")
        except Exception as e:
            logger.error(f"Failed to store data: {e}", exc_info=True)

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

        # Try the explicit weight_source first
        if self.weight_source is not None:
            logger.debug(f"_get_weights_for_storage: using existing weight_source {self.weight_source}")
            weights = self.weight_source.get_weights()
        else:
            # Auto-resolve a WeightSource via resolve_weight_sources
            logger.debug(f"_get_weights_for_storage: auto-resolving WeightSource for {node}.{attr}")
            source = _resolve_source_for_node(node, attr)
            if source is not None:
                self.weight_source = source
                weights = source.get_weights()
                logger.debug(f"_get_weights_for_storage: resolved -> {source}, got {len(weights)} weights")
            else:
                # Last resort — direct getAttr (works for simple attrs like nCloth maps)
                logger.debug(f"_get_weights_for_storage: fallback cmds.getAttr({weight_node})")
                weights = cmds.getAttr(weight_node)

        self.storage["weight_node"] = weight_node
        self.storage["weight_type"] = _type
        self.storage["weights"] = weights if isinstance(weights, list) else list(weights or [])

    # ------------------------------------------------------------------
    # Combine
    # ------------------------------------------------------------------

    def _get_current_weights(self):
        """Read weights from the current context using WeightSource when available."""
        if self.weight_source is not None:
            logger.debug(f"_get_current_weights: using weight_source {self.weight_source}")
            return self.weight_source.get_weights()

        weight_node = self.current_weight_node
        if weight_node:
            node, attr = weight_node.rsplit('.', 1)
            source = _resolve_source_for_node(node, attr)
            if source is not None:
                logger.debug(f"_get_current_weights: auto-resolved {source}")
                return source.get_weights()
            logger.debug(f"_get_current_weights: fallback cmds.getAttr({weight_node})")
            return cmds.getAttr(weight_node)
        return []

    def combine_data(self, mode="add"):
        logger.debug(f"combine_data: mode={mode}")
        if self.storage['weights']:
            new_weights = self._get_current_weights()
            logger.debug(f"combine_data: stored={len(self.storage['weights'])}, "
                         f"current={len(new_weights) if new_weights else 0}")
            if mode == "add":
                self.storage["weights"] = (
                    np.array(self.storage["weights"]) + np.array(new_weights)).tolist()
            elif mode == "sub":
                self.storage["weights"] = (
                    np.array(self.storage["weights"]) - np.array(new_weights)).tolist()
            elif mode == "intersect":
                self.storage["weights"] = np.minimum(
                    np.array(self.storage["weights"]), np.array(new_weights)).tolist()
            elif mode == "multiply":
                self.storage["weights"] = (
                    np.array(self.storage["weights"]) * np.array(new_weights)).tolist()
            elif mode == "divide":
                stored = np.array(self.storage["weights"])
                current = np.array(new_weights)
                self.storage["weights"] = np.where(
                    current != 0, stored / current, stored).tolist()

        if self.storage['selection']:
            sel = cmds.ls(sl=True)
            _compo_type = component_in_list(sel)
            if _compo_type != self.storage["component_type"]:
                sel = cmds.polyListComponentConversion(sel, tv=True)
            obj_list = list(set([o.split(".")[0] for o in sel]))
            for o in obj_list:
                if o in self.storage["selection"]:
                    new_ids = extract_id([s for s in sel if s.startswith(o)])
                    if mode == "add":
                        self.storage["selection"][o] = list(
                            set(self.storage["selection"][o]) | set(new_ids))
                    elif mode == "sub":
                        self.storage["selection"][o] = list(
                            set(self.storage["selection"][o]) - set(new_ids))
                    elif mode == "intersect":
                        self.storage["selection"][o] = list(
                            set(self.storage["selection"][o]) & set(new_ids))
                else:
                    if mode == "add":
                        self.storage["selection"][o] = extract_id(
                            [s for s in sel if s.startswith(o)])
                    elif mode == "intersect":
                        self.storage["selection"][o] = []

            self._set_selection()

    # ------------------------------------------------------------------
    # Restore
    # ------------------------------------------------------------------

    @singleUndoChunk
    def restore_data(self, selection=True, weights=True):
        """Restore stored weights and selection."""
        logger.debug(f"restore_data: selection={selection}, weights={weights}, "
                     f"has_weights={bool(self.storage['weights'])}, "
                     f"has_selection={bool(self.storage['selection'])}, "
                     f"current_weight_node={self.current_weight_node}")
        try:
            if self.storage['weights'] or self.storage['selection']:
                if selection and self.storage['selection']:
                    logger.debug(f"restore_data: restoring selection...")
                    self._set_selection()

                if weights and self.storage['weights']:
                    logger.debug(f"restore_data: restoring weights ({len(self.storage['weights'])} values)...")
                    self._set_weights()
                logger.info("Data restored successfully")
            else:
                logger.debug("restore_data: nothing to restore (empty storage)")
        except Exception as e:
            logger.error(f"Failed to restore data: {e}", exc_info=True)

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
        logger.debug(f"_set_selection: selecting {len(rsel)} items")
        if rsel:
            cmds.select(rsel, r=True)
        else:
            cmds.select(clear=True)

    def _set_weights(self, restore=False):
        """Write stored weights back to Maya.

        Uses the stored ``weight_source`` (WeightSource) when available
        for a unified code path that works for deformers AND nucleus.
        Falls back to the legacy set_nucx_map_data / set_deformer_weights
        helpers only when no WeightSource is available.
        """
        weight_node = self.storage["weight_node"]
        _cur_node = self.current_weight_node
        if not restore and _cur_node:
            weight_node = _cur_node

        logger.debug(f"_set_weights: target={weight_node}, restore={restore}, "
                     f"weight_source={self.weight_source}")

        if not weight_node:
            logger.warning("_set_weights: no weight_node resolved — skipping")
            return

        node, attr = weight_node.rsplit('.', 1)
        stored_weights = self.storage["weights"]

        # Prefer WeightSource for a unified write path
        if self.weight_source is not None:
            # If we are writing to the current context (not original),
            # make sure the source map matches
            source = self.weight_source
            available = source.available_maps()
            if attr in available:
                source.use_map(attr)
            logger.debug(f"_set_weights: using weight_source.set_weights ({len(stored_weights)} values)")
            source.set_weights(stored_weights)
            return

        # Fallback — try to auto-resolve
        source = _resolve_source_for_node(node, attr)
        if source is not None:
            logger.debug(f"_set_weights: auto-resolved {source}, setting weights")
            source.set_weights(stored_weights)
            return

        # Legacy path
        logger.debug(f"_set_weights: legacy path for {node}.{attr}")
        _type = self.storage["weight_type"]
        if _type in ("nCloth", "nRigid"):
            from dw_maya.dw_nucleus_utils.dw_core import set_nucx_map_data
            set_nucx_map_data(node, attr, stored_weights)
        else:
            from dw_maya.dw_deformers.dw_core import set_deformer_weights
            if attr:
                _type = attr
            else:
                _type = "deformer" if _type != "blendshape" else _type
            set_deformer_weights(node, stored_weights, _type)

    # ------------------------------------------------------------------
    # Clear / properties
    # ------------------------------------------------------------------

    def clear_storage(self):
        """Clear stored data."""
        logger.debug("clear_storage: clearing all data")
        self.storage = {
            'weights': [],
            'selection': {},
            'weight_node': "",
            "weight_type": "",
            'component_type': None,
        }
        self.weight_source = None
        self._update_button_state(False)

    @property
    def current_weight_node(self):
        if not self._current_weight_node:
            _node, _attr, _type = get_current_artisan_map()
            if _node and _attr:
                return f"{_node}.{_attr}"
            return None
        return self._current_weight_node

    @current_weight_node.setter
    def current_weight_node(self, node: str):
        """Set the current weight node (node.attr or just node)."""
        self._current_weight_node = node

    # ------------------------------------------------------------------
    # Visual state — stylesheet constants
    # ------------------------------------------------------------------

    # Base CSS template — fill {bg} and {bg_hover}
    _CSS_SOLID = (
        "QPushButton {{ background-color: {bg}; border: none; border-radius: 2px; "
        "padding: 5px; color: white; }}"
        "QPushButton:hover {{ background-color: {bg_hover}; }}"
    )
    _CSS_GRADIENT = (
        "QPushButton {{ background: qlineargradient("
        "spread:pad, x1:0, y1:0, x2:1, y2:1, "
        "stop:0 {c0}, stop:0.5 {c0}, stop:0.51 {c1}, stop:1 {c1}"
        "); border: none; border-radius: 2px; padding: 5px; color: white; }}"
    )

    # Named colour tokens
    _C_EMPTY    = ("rgb(128, 128, 128)", "rgb(140, 140, 140)")
    _C_WEIGHTS  = ("rgb(70, 110, 85)",   "rgb(80, 120, 95)")
    _C_SEL      = ("rgb(194, 177, 109)", "rgb(204, 187, 119)")

    def _make_stylesheet(self, has_w: bool, has_s: bool) -> str:
        """Return the appropriate stylesheet string for the current state.

        Args:
            has_w: Button has stored weights.
            has_s: Button has stored selection.
        """
        if has_w and has_s:
            return self._CSS_GRADIENT.format(c0=self._C_WEIGHTS[0], c1=self._C_SEL[0])
        if has_w:
            return self._CSS_SOLID.format(bg=self._C_WEIGHTS[0], bg_hover=self._C_WEIGHTS[1])
        if has_s:
            return self._CSS_SOLID.format(bg=self._C_SEL[0], bg_hover=self._C_SEL[1])
        return self._CSS_SOLID.format(bg=self._C_EMPTY[0], bg_hover=self._C_EMPTY[1])

    def _update_button_state(self, has_data: bool):
        """Update button appearance and label based on storage state."""
        has_w = has_data and bool(self.storage["weights"])
        has_s = has_data and bool(self.storage["selection"])

        if has_data:
            weight_node = self.storage.get('weight_node') or ''
            if weight_node:
                label = weight_node.split('.')[0]
                self.setText(label[:14] + '…' if len(label) > 14 else label)
        else:
            self.setText('')

        self.setStyleSheet(self._make_stylesheet(has_w, has_s))
