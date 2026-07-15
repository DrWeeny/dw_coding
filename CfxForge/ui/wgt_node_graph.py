"""Node graph widget: QGraphics view of a recipe's task graph.

Summary:
    Read/render/edit layer over Recipe.nodes. Nodes are movable rects
    colored by op type, input ports on the left (one per wired or
    declared input), one output port on the right. Edges follow the
    ``inputs`` dict ('node' or 'node.key' refs). Structural edits are
    *requested* through signals - the main window owns the Recipe and
    rebuilds the scene, so the document stays the single source of truth.

Classes:
    NodeGraphWidget, GraphScene, GraphView, NodeItem, PortItem, EdgeItem

Author:
    DrWeeny
"""

from PySide6 import QtWidgets, QtCore, QtGui

from CfxForge.taxonomy import OP_INPUTS


TYPE_COLORS = {
    'file': '#3f6f9f',
    'group': '#4e8a5a',
    'hierarchy': '#2e7d7d',
    'step': '#6a7d2e',
    'solver': '#b06a30',
    'cloth': '#c29438',
    'collider': '#8a4a3a',
    'constraint': '#9a4a7a',
    'preset': '#6a5aa0',
    'deformer': '#7a4aa0',
    'script': '#666666',
}
DEFAULT_COLOR = '#555555'

NODE_WIDTH = 170
HEADER_H = 26
PORT_ROW_H = 18
PORT_RADIUS = 5


class PortItem(QtWidgets.QGraphicsEllipseItem):
    """Connection dot. role 'in' ports carry their port name; a declared
    but unwired port renders dimmed."""

    def __init__(self, role: str, name: str, wired: bool = True,
                 parent=None):
        super().__init__(-PORT_RADIUS, -PORT_RADIUS,
                         PORT_RADIUS * 2, PORT_RADIUS * 2, parent)
        self.role = role
        self.name = name
        color = '#d8d8d8' if wired else '#5a5a5a'
        self.setBrush(QtGui.QBrush(QtGui.QColor(color)))
        self.setPen(QtGui.QPen(QtGui.QColor('#222222'), 1))
        self.setAcceptedMouseButtons(QtCore.Qt.MouseButton.NoButton)

    @property
    def node_item(self):
        return self.parentItem()


class NodeItem(QtWidgets.QGraphicsRectItem):
    """One recipe node entry."""

    #: default named outputs drawn per op type (only where keyed refs are
    #: the natural wiring; every node also keeps its whole-node out port)
    HIERARCHY_KEYS = ('presim', 'utils', 'collider', 'sim', 'postsim',
                      'exp')

    def _named_outputs(self, entry) -> list:
        if entry.get('type') != 'hierarchy':
            return []
        groups = entry.get('params', {}).get('groups')
        if isinstance(groups, str):
            groups = [groups]
        return ['rig_grp'] + list(groups or self.HIERARCHY_KEYS)

    def __init__(self, node_id: str, entry: dict):
        self.node_id = node_id
        self.entry = entry
        wired = set(entry.get('inputs', {}))
        declared = list(OP_INPUTS.get(entry.get('type', ''), ()))
        ports = declared + sorted(wired - set(declared))
        out_names = self._named_outputs(entry)
        height = (HEADER_H
                  + max(len(ports), len(out_names), 1) * PORT_ROW_H + 6)
        super().__init__(0, 0, NODE_WIDTH, height)
        self.setFlags(
            QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setBrush(QtGui.QBrush(QtGui.QColor('#3a3a3a')))
        self.setPen(QtGui.QPen(QtGui.QColor('#1e1e1e'), 1))

        self.in_ports = {}
        for row, name in enumerate(ports):
            is_wired = name in wired
            port = PortItem('in', name, is_wired, self)
            port.setPos(0, HEADER_H + (row + 0.5) * PORT_ROW_H)
            self.in_ports[name] = port
            label = QtWidgets.QGraphicsSimpleTextItem(name, self)
            label.setBrush(QtGui.QBrush(QtGui.QColor(
                '#cccccc' if is_wired else '#7a7a7a')))
            label.setFont(QtGui.QFont('Segoe UI', 7))
            label.setPos(PORT_RADIUS + 3,
                         HEADER_H + (row + 0.5) * PORT_ROW_H - 7)
        self.out_port = PortItem('out', '', True, self)
        if out_names:
            # whole-node port rides the header; named outputs stack below
            self.out_port.setPos(NODE_WIDTH, HEADER_H * 0.5)
        else:
            self.out_port.setPos(NODE_WIDTH, HEADER_H + height * 0.35)
        self.out_ports = {}
        font = QtGui.QFont('Segoe UI', 7)
        metrics = QtGui.QFontMetricsF(font)
        for row, name in enumerate(out_names):
            port = PortItem('out', name, True, self)
            port.setPos(NODE_WIDTH, HEADER_H + (row + 0.5) * PORT_ROW_H)
            self.out_ports[name] = port
            label = QtWidgets.QGraphicsSimpleTextItem(name, self)
            label.setBrush(QtGui.QBrush(QtGui.QColor('#cccccc')))
            label.setFont(font)
            label.setPos(NODE_WIDTH - PORT_RADIUS - 3
                         - metrics.horizontalAdvance(name),
                         HEADER_H + (row + 0.5) * PORT_ROW_H - 7)

    def paint(self, painter, option, widget=None):
        rect = self.rect()
        color = QtGui.QColor(TYPE_COLORS.get(self.entry.get('type', ''),
                                             DEFAULT_COLOR))
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setPen(QtGui.QPen(QtGui.QColor('#141414'), 1))
        painter.setBrush(QtGui.QBrush(QtGui.QColor('#333333')))
        painter.drawRoundedRect(rect, 4, 4)
        header = QtCore.QRectF(rect.x(), rect.y(), rect.width(), HEADER_H)
        painter.setBrush(QtGui.QBrush(color))
        painter.drawRoundedRect(header, 4, 4)
        painter.setPen(QtGui.QPen(QtGui.QColor('#f0f0f0')))
        painter.setFont(QtGui.QFont('Segoe UI', 8, QtGui.QFont.Weight.Bold))
        painter.drawText(header.adjusted(6, 1, -4, -HEADER_H * 0.45),
                         QtCore.Qt.AlignmentFlag.AlignVCenter, self.node_id)
        painter.setFont(QtGui.QFont('Segoe UI', 7))
        painter.setPen(QtGui.QPen(QtGui.QColor('#e6e6e6')))
        painter.drawText(header.adjusted(6, HEADER_H * 0.45, -4, 0),
                         QtCore.Qt.AlignmentFlag.AlignVCenter,
                         self.entry.get('type', '?'))
        if self.isSelected():
            painter.setPen(QtGui.QPen(QtGui.QColor('#e8b93f'), 2))
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect, 4, 4)

    def in_pos(self, port_name: str) -> QtCore.QPointF:
        port = self.in_ports.get(port_name)
        if port is None:
            return self.scenePos() + QtCore.QPointF(0, HEADER_H)
        return port.scenePos()

    def out_pos(self, key: str = '') -> QtCore.QPointF:
        port = self.out_ports.get(key) if key else None
        return (port or self.out_port).scenePos()

    def itemChange(self, change, value):
        flag = QtWidgets.QGraphicsItem.GraphicsItemChange
        if change == flag.ItemPositionHasChanged and self.scene():
            self.scene().update_edges()
        return super().itemChange(change, value)


class EdgeItem(QtWidgets.QGraphicsPathItem):
    """One wired input: src node output -> dst node input port."""

    def __init__(self, src_item, dst_item, port: str, ref: str):
        super().__init__()
        self.src_item = src_item
        self.dst_item = dst_item
        self.port = port
        self.ref = ref
        self.setZValue(-1)
        self.setFlag(
            QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setPen(QtGui.QPen(QtGui.QColor('#9a9a9a'), 1.6))
        self.update_path()

    def update_path(self):
        key = self.ref.split('.', 1)[1] if '.' in self.ref else ''
        source = self.src_item.out_pos(key)
        target = self.dst_item.in_pos(self.port)
        path = QtGui.QPainterPath(source)
        dx = max(abs(target.x() - source.x()) * 0.5, 40.0)
        path.cubicTo(source + QtCore.QPointF(dx, 0),
                     target - QtCore.QPointF(dx, 0),
                     target)
        self.setPath(path)

    def paint(self, painter, option, widget=None):
        pen = QtGui.QPen(QtGui.QColor('#e8b93f') if self.isSelected()
                         else QtGui.QColor('#9a9a9a'), 1.6)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setPen(pen)
        painter.drawPath(self.path())
        # label keyed refs ('node.key') at the edge midpoint
        if '.' in self.ref:
            key = self.ref.split('.', 1)[1]
            mid = self.path().pointAtPercent(0.5)
            painter.setFont(QtGui.QFont('Segoe UI', 7))
            painter.setPen(QtGui.QPen(QtGui.QColor('#b8b8b8')))
            painter.drawText(mid + QtCore.QPointF(4, -4), f'.{key}')


class GraphScene(QtWidgets.QGraphicsScene):

    node_selected = QtCore.Signal(str)          # '' = nothing selected
    #: src ref ('node' or 'node.key'), dst node id, dst input port
    connection_requested = QtCore.Signal(str, str, str)
    edge_delete_requested = QtCore.Signal(str, str)      # dst, port
    nodes_delete_requested = QtCore.Signal(list)
    create_requested = QtCore.Signal(str, float, float)  # op, scene x, y

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setBackgroundBrush(QtGui.QBrush(QtGui.QColor('#262626')))
        self.node_items = {}
        self.edge_items = []
        self.selectionChanged.connect(self._on_selection)

    # ------------------------------------------------------------------
    def load(self, nodes: dict, positions: dict):
        # clear() deletes the C++ items and fires selectionChanged
        # mid-rebuild - keep the scene silent until the dicts are valid
        self._loading = True
        self.blockSignals(True)
        try:
            self.clear()
            self.node_items = {}
            self.edge_items = []
            auto = _auto_layout(nodes)
            for node_id, entry in nodes.items():
                item = NodeItem(node_id, entry)
                pos = positions.get(node_id) or auto.get(node_id, (0, 0))
                item.setPos(pos[0], pos[1])
                self.addItem(item)
                self.node_items[node_id] = item
            for node_id, entry in nodes.items():
                for port, ref in entry.get('inputs', {}).items():
                    src_id = str(ref).split('.')[0]
                    src = self.node_items.get(src_id)
                    dst = self.node_items.get(node_id)
                    if src and dst:
                        edge = EdgeItem(src, dst, port, str(ref))
                        self.addItem(edge)
                        self.edge_items.append(edge)
        finally:
            self.blockSignals(False)
            self._loading = False

    def positions(self) -> dict:
        result = {}
        for node_id, item in self.node_items.items():
            try:
                pos = item.pos()
            except RuntimeError:      # C++ side already deleted
                continue
            result[node_id] = (pos.x(), pos.y())
        return result

    def update_edges(self):
        for edge in self.edge_items:
            try:
                edge.update_path()
            except RuntimeError:      # C++ side already deleted
                continue

    # ------------------------------------------------------------------
    def _on_selection(self):
        if getattr(self, '_loading', False):
            return
        for item in self.selectedItems():
            if isinstance(item, NodeItem):
                self.node_selected.emit(item.node_id)
                return
        self.node_selected.emit('')

    def request_deletion(self):
        node_ids = []
        for item in self.selectedItems():
            if isinstance(item, NodeItem):
                node_ids.append(item.node_id)
            elif isinstance(item, EdgeItem):
                self.edge_delete_requested.emit(item.dst_item.node_id,
                                                item.port)
        if node_ids:
            self.nodes_delete_requested.emit(node_ids)


class TabCreatePopup(QtWidgets.QFrame):
    """Nuke-style Tab menu: type an op name, Enter creates it."""

    def __init__(self, view, op_types, scene_pos):
        super().__init__(view, QtCore.Qt.WindowType.Popup)
        self._view = view
        self._scene_pos = scene_pos
        self.edit = QtWidgets.QLineEdit(self)
        self.edit.setPlaceholderText('op type...')
        completer = QtWidgets.QCompleter(list(op_types), self.edit)
        completer.setCaseSensitivity(
            QtCore.Qt.CaseSensitivity.CaseInsensitive)
        completer.setCompletionMode(
            QtWidgets.QCompleter.CompletionMode.PopupCompletion)
        self.edit.setCompleter(completer)
        self._op_types = list(op_types)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.addWidget(self.edit)
        self.edit.returnPressed.connect(self._on_return)
        self.setFixedWidth(180)

    def _on_return(self):
        text = self.edit.text().strip()
        matches = [op for op in self._op_types
                   if op.lower().startswith(text.lower())] if text else []
        if matches:
            self._view.scene().create_requested.emit(
                matches[0], self._scene_pos.x(), self._scene_pos.y())
        self.close()


class GraphView(QtWidgets.QGraphicsView):

    def __init__(self, scene, op_types=(), parent=None):
        super().__init__(scene, parent)
        self.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        self.setDragMode(
            QtWidgets.QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(
            QtWidgets.QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.op_types = list(op_types)
        self._drag_src = None
        self._drag_key = ''
        self._temp_edge = None

    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)

    def event(self, event):
        # Tab is grabbed by focus handling before keyPressEvent sees it
        if (event.type() == QtCore.QEvent.Type.KeyPress
                and event.key() == QtCore.Qt.Key.Key_Tab):
            self.show_tab_create()
            return True
        return super().event(event)

    def show_tab_create(self):
        cursor = QtGui.QCursor.pos()
        view_pos = self.mapFromGlobal(cursor)
        if not self.rect().contains(view_pos):
            view_pos = self.rect().center()
            cursor = self.mapToGlobal(view_pos)
        popup = TabCreatePopup(self, self.op_types,
                               self.mapToScene(view_pos))
        popup.move(cursor)
        popup.show()
        popup.edit.setFocus()

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key.Key_Delete:
            self.scene().request_deletion()
            return
        if event.key() == QtCore.Qt.Key.Key_F:
            self.fit_all()
            return
        super().keyPressEvent(event)

    def fit_all(self):
        rect = self.scene().itemsBoundingRect().adjusted(-40, -40, 40, 40)
        if not rect.isEmpty():
            self.fitInView(rect, QtCore.Qt.AspectRatioMode.KeepAspectRatio)

    # --------------------------------------------------------------
    # drag from an output port to wire a connection
    # --------------------------------------------------------------
    def _port_at(self, view_pos, role: str):
        for item in self.items(view_pos):
            if isinstance(item, PortItem) and item.role == role:
                return item
        return None

    def _node_at(self, view_pos):
        for item in self.items(view_pos):
            if isinstance(item, NodeItem):
                return item
        return None

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            port = self._port_at(event.pos(), 'out')
            if port is not None:
                self._drag_src = port.node_item
                self._drag_key = port.name
                self._temp_edge = QtWidgets.QGraphicsPathItem()
                pen = QtGui.QPen(QtGui.QColor('#e8b93f'), 1.4,
                                 QtCore.Qt.PenStyle.DashLine)
                self._temp_edge.setPen(pen)
                self.scene().addItem(self._temp_edge)
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._temp_edge is not None:
            source = self._drag_src.out_pos(self._drag_key)
            target = self.mapToScene(event.pos())
            path = QtGui.QPainterPath(source)
            path.lineTo(target)
            self._temp_edge.setPath(path)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._temp_edge is not None:
            self.scene().removeItem(self._temp_edge)
            self._temp_edge = None
            src = self._drag_src
            src_key = getattr(self, '_drag_key', '')
            self._drag_src = None
            self._drag_key = ''
            port = self._port_at(event.pos(), 'in')
            dst = port.node_item if port else self._node_at(event.pos())
            if dst is not None and dst is not src:
                name = port.name if port else None
                if not name:
                    name, ok = QtWidgets.QInputDialog.getText(
                        self, 'Connect', 'Input port name:', text='in')
                    if not ok or not name:
                        return
                ref = f'{src.node_id}.{src_key}' if src_key else src.node_id
                self.scene().connection_requested.emit(
                    ref, dst.node_id, name)
            return
        super().mouseReleaseEvent(event)


class NodeGraphWidget(QtWidgets.QWidget):
    """View+scene bundle the main window embeds."""

    def __init__(self, op_types=(), parent=None):
        super().__init__(parent)
        self.scene = GraphScene(self)
        self.view = GraphView(self.scene, op_types, self)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)

    def load(self, nodes: dict, positions: dict = None):
        self.scene.load(nodes, positions or {})

    def positions(self) -> dict:
        return self.scene.positions()


def _auto_layout(nodes: dict) -> dict:
    """Column per dependency depth, rows stacked per column."""
    depths = {}

    def depth(node_id, seen=()):
        if node_id in depths:
            return depths[node_id]
        if node_id in seen:                      # cycle: park at 0
            return 0
        entry = nodes.get(node_id) or {}
        deps = [str(r).split('.')[0] for r in entry.get('inputs', {}).values()]
        deps = [d for d in deps if d in nodes]
        value = max((depth(d, seen + (node_id,)) for d in deps),
                    default=-1) + 1
        depths[node_id] = value
        return value

    columns = {}
    for node_id in nodes:
        columns.setdefault(depth(node_id), []).append(node_id)
    positions = {}
    for col, ids in sorted(columns.items()):
        for row, node_id in enumerate(ids):
            positions[node_id] = (col * (NODE_WIDTH + 70), row * 110)
    return positions