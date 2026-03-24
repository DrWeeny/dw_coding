"""
MindMapScene — QGraphicsScene managing nodes and edges for the CFX Mind Map.

Classes

- MindMapScene: Manages NodeItem / EdgeItem collections, undo/redo, clipboard,
  auto-layout, serialization, and snap-to-grid.

"""

import math
from typing import Optional

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QPen, QColor, QPainter, QBrush, QUndoStack, QUndoCommand
from PySide6.QtWidgets import (
    QGraphicsScene, QGraphicsItem,
)

from dw_utils.mindmap.constants import (
    SCENE_BG_COLOR, SCENE_SIZE, GRID_SIZE, GRID_LINE_COLOR,
    DEFAULT_NODE_WIDTH, DEFAULT_NODE_HEIGHT,
    DEFAULT_BG_COLOR, DEFAULT_BORDER_COLOR, DEFAULT_TEXT_COLOR,
    DEFAULT_FONT_SIZE, DEFAULT_OPACITY, DEFAULT_BORDER_WIDTH,
    DEFAULT_EDGE_COLOR, DEFAULT_EDGE_WIDTH, DEFAULT_EDGE_STYLE,
    DEFAULT_EDGE_DIRECTED, DEFAULT_EDGE_LABEL, SHAPE_ROUNDED_RECT,
)
from dw_utils.mindmap.items import NodeItem, EdgeItem

from dw_logger import get_logger
log = get_logger()


# ──────────────────────────────────────────────────────────────────────────────
# Undo commands
# ──────────────────────────────────────────────────────────────────────────────

class _AddNodeCmd(QUndoCommand):
    def __init__(self, scene: "MindMapScene", node: NodeItem):
        super().__init__(f"Add node '{node.label}'")
        self._scene = scene
        self._node  = node

    def redo(self):
        self._scene._add_node_item(self._node)

    def undo(self):
        self._scene._remove_node_item(self._node, remove_edges=True)


class _RemoveNodesCmd(QUndoCommand):
    def __init__(self, scene: "MindMapScene", nodes: list, edges: list):
        super().__init__("Delete selection")
        self._scene = scene
        self._nodes = nodes
        self._edges = edges

    def redo(self):
        for e in self._edges:
            self._scene._remove_edge_item(e)
        for n in self._nodes:
            self._scene._remove_node_item(n, remove_edges=False)

    def undo(self):
        for n in self._nodes:
            self._scene._add_node_item(n)
        for e in self._edges:
            self._scene._add_edge_item(e)


class _AddEdgeCmd(QUndoCommand):
    def __init__(self, scene: "MindMapScene", edge: EdgeItem):
        super().__init__(f"Add edge")
        self._scene = scene
        self._edge  = edge

    def redo(self):
        self._scene._add_edge_item(self._edge)

    def undo(self):
        self._scene._remove_edge_item(self._edge)


class _MoveNodesCmd(QUndoCommand):
    def __init__(self, scene, node_id_deltas: list):
        """node_id_deltas: list of (node_id, old_pos, new_pos)"""
        super().__init__("Move node(s)")
        self._scene = scene
        self._deltas = node_id_deltas

    def redo(self):
        for nid, _, new_pos in self._deltas:
            node = self._scene.get_node(nid)
            if node:
                node.setPos(new_pos)

    def undo(self):
        for nid, old_pos, _ in self._deltas:
            node = self._scene.get_node(nid)
            if node:
                node.setPos(old_pos)


class _EditNodeCmd(QUndoCommand):
    def __init__(self, scene, node_id: str, old_data: dict, new_data: dict):
        super().__init__("Edit node")
        self._scene    = scene
        self._node_id  = node_id
        self._old_data = old_data
        self._new_data = new_data

    def _apply(self, data):
        node = self._scene.get_node(self._node_id)
        if node:
            self._scene._apply_node_data(node, data)

    def redo(self):
        self._apply(self._new_data)

    def undo(self):
        self._apply(self._old_data)


# ──────────────────────────────────────────────────────────────────────────────
# Scene
# ──────────────────────────────────────────────────────────────────────────────

class MindMapScene(QGraphicsScene):
    """
    Core scene for the CFX Mind Map.

    Manages the collection of NodeItem and EdgeItem objects and provides
    helpers for node/edge creation, undo/redo, serialisation, and layout.

    Signals:
        scene_changed(): Emitted after any structural modification.
        node_double_clicked(str): Forwarded from NodeItem.
        status_message(str): Short informational message for the status bar.
    """

    scene_changed        = QtCore.Signal()
    node_double_clicked  = QtCore.Signal(str)
    status_message       = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        half = SCENE_SIZE / 2
        self.setSceneRect(-half, -half, SCENE_SIZE, SCENE_SIZE)
        self.setBackgroundBrush(QBrush(QColor(SCENE_BG_COLOR)))

        self._nodes: dict  = {}
        self._edges: dict  = {}

        self.undo_stack  = QUndoStack(self)
        self.snap_grid   = False
        self._clipboard  : list = []
        self._style_clipboard: dict = {}   # holds copied node style

        # Edge-drawing state
        self._edge_src              = None  # type: Optional[NodeItem]
        self._temp_line             = None

        # Track positions for move undo
        self._drag_start_positions: dict[str, QPointF] = {}

    # ── internal helpers ──────────────────────────────────────────────────────

    def _add_node_item(self, node: NodeItem):
        self._nodes[node.node_id] = node
        self.addItem(node)
        node.signals.node_double_clicked.connect(self.node_double_clicked)
        self.scene_changed.emit()

    def _remove_node_item(self, node: NodeItem, remove_edges=True):
        if remove_edges:
            for edge in list(self._edges.values()):
                if edge.source is node or edge.target is node:
                    self._remove_edge_item(edge)
        self.removeItem(node)
        self._nodes.pop(node.node_id, None)
        self.scene_changed.emit()

    def _add_edge_item(self, edge: EdgeItem):
        self._edges[edge.edge_id] = edge
        self.addItem(edge)
        self.scene_changed.emit()

    def _remove_edge_item(self, edge: EdgeItem):
        self.removeItem(edge)
        self._edges.pop(edge.edge_id, None)
        self.scene_changed.emit()

    def _apply_node_data(self, node: NodeItem, data: dict):
        node.label        = data.get("label",        node.label)
        node.body_text    = data.get("body_text",    node.body_text)
        node.node_shape   = data.get("shape",        node.node_shape)
        node.bg_color     = data.get("bg_color",     node.bg_color)
        node.border_color = data.get("border_color", node.border_color)
        node.text_color   = data.get("text_color",   node.text_color)
        node.font_size    = data.get("font_size",    node.font_size)
        node.category     = data.get("category",     node.category)
        node.border_width = data.get("border_width", node.border_width)
        node.prepareGeometryChange()
        node._width  = data.get("width",  node._width)
        node._height = data.get("height", node._height)
        node._rebuild_geometry()
        node.setOpacity(data.get("opacity", node.opacity()))
        # Attachment — use set_attachment so the QPixmap cache is rebuilt
        if "attachment" in data:
            node.set_attachment(data["attachment"])
        node.update()
        self.scene_changed.emit()

    def _snap(self, pos: QPointF) -> QPointF:
        if self.snap_grid:
            g = GRID_SIZE
            return QPointF(round(pos.x() / g) * g, round(pos.y() / g) * g)
        return pos

    # ── public API ────────────────────────────────────────────────────────────

    def get_node(self, node_id: str):
        return self._nodes.get(node_id)

    def get_edge(self, edge_id: str):
        return self._edges.get(edge_id)

    def all_nodes(self) -> list:
        return list(self._nodes.values())

    def all_edges(self) -> list:
        return list(self._edges.values())

    def create_node(
        self,
        pos          = None,
        label        : str   = "New Node",
        body_text    : str   = "",
        shape        : str   = SHAPE_ROUNDED_RECT,
        bg_color     : str   = DEFAULT_BG_COLOR,
        border_color : str   = DEFAULT_BORDER_COLOR,
        text_color   : str   = DEFAULT_TEXT_COLOR,
        font_size    : int   = DEFAULT_FONT_SIZE,
        width        : int   = DEFAULT_NODE_WIDTH,
        height       : int   = DEFAULT_NODE_HEIGHT,
        opacity      : float = DEFAULT_OPACITY,
        border_width : float = DEFAULT_BORDER_WIDTH,
        category     : str   = "",
        node_id      : str   = None,
        undoable     : bool  = True,
    ) -> NodeItem:
        """Create and add a new node to the scene."""
        node = NodeItem(
            label=label, body_text=body_text, shape=shape,
            bg_color=bg_color, border_color=border_color,
            text_color=text_color, font_size=font_size,
            width=width, height=height, opacity=opacity,
            border_width=border_width, category=category,
            node_id=node_id,
        )
        if pos is None:
            pos = QPointF(0, 0)
        node.setPos(self._snap(pos - QPointF(width / 2, height / 2)))

        if undoable:
            self.undo_stack.push(_AddNodeCmd(self, node))
        else:
            self._add_node_item(node)

        return node

    def create_edge(
        self,
        source   : NodeItem,
        target   : NodeItem,
        label    : str   = DEFAULT_EDGE_LABEL,
        color    : str   = DEFAULT_EDGE_COLOR,
        width    : float = DEFAULT_EDGE_WIDTH,
        style    : str   = DEFAULT_EDGE_STYLE,
        directed : bool  = DEFAULT_EDGE_DIRECTED,
        edge_id  : str   = None,
        undoable : bool  = True,
    ) -> EdgeItem:
        """Connect two nodes with an edge."""
        # Prevent duplicate
        for e in self._edges.values():
            if e.source is source and e.target is target:
                self.status_message.emit("Edge already exists between these nodes.")
                return e

        edge = EdgeItem(source=source, target=target, label=label,
                        color=color, width=width, style=style,
                        directed=directed, edge_id=edge_id)
        if undoable:
            self.undo_stack.push(_AddEdgeCmd(self, edge))
        else:
            self._add_edge_item(edge)

        return edge

    def delete_selection(self):
        """Delete all selected nodes and their connected edges."""
        nodes = [i for i in self.selectedItems() if isinstance(i, NodeItem)]
        edges_to_del = set()
        for n in nodes:
            for e in self._edges.values():
                if e.source is n or e.target is n:
                    edges_to_del.add(e)
        # Also delete selected edges
        for i in self.selectedItems():
            if isinstance(i, EdgeItem):
                edges_to_del.add(i)

        if not nodes and not edges_to_del:
            return

        self.undo_stack.push(_RemoveNodesCmd(self, nodes, list(edges_to_del)))

    def edit_node(self, node: NodeItem, new_data: dict):
        """Apply new properties to a node with undo support."""
        old_data = node.to_dict()
        self.undo_stack.push(_EditNodeCmd(self, node.node_id, old_data, new_data))

    def copy_node_style(self, node: NodeItem):
        """Copy the visual style of *node* into the style clipboard."""
        self._style_clipboard = {
            "shape"       : node.node_shape,
            "bg_color"    : node.bg_color,
            "border_color": node.border_color,
            "text_color"  : node.text_color,
            "font_size"   : node.font_size,
            "border_width": node.border_width,
            "opacity"     : node.opacity(),
        }
        self.status_message.emit(f"Style copied from '{node.label}'.")

    def paste_node_style(self, node: NodeItem):
        """Apply the style clipboard onto *node* with undo support."""
        if not self._style_clipboard:
            return
        old_data = node.to_dict()
        new_data = dict(old_data)
        new_data.update(self._style_clipboard)
        self.undo_stack.push(_EditNodeCmd(self, node.node_id, old_data, new_data))
        self.status_message.emit(f"Style pasted onto '{node.label}'.")

    def copy_selection(self):
        """Copy selected nodes to clipboard."""
        self._clipboard = [
            n.to_dict()
            for n in self.selectedItems()
            if isinstance(n, NodeItem)
        ]
        self.status_message.emit(f"{len(self._clipboard)} node(s) copied.")

    def paste(self, offset: QPointF = QPointF(30, 30)):
        """Paste clipboard nodes with an offset."""
        if not self._clipboard:
            return
        import uuid
        self.clearSelection()
        for data in self._clipboard:
            new_data            = dict(data)
            new_data["id"]      = str(uuid.uuid4())
            new_data["x"]       = data["x"] + offset.x()
            new_data["y"]       = data["y"] + offset.y()
            node                = NodeItem.from_dict(new_data)
            self._add_node_item(node)
            node.setSelected(True)
        self.scene_changed.emit()

    def select_all(self):
        for item in self.items():
            item.setSelected(True)

    def clear_graph(self):
        """Remove all nodes and edges (not undoable — used for load/new)."""
        self.undo_stack.clear()
        for edge in list(self._edges.values()):
            self.removeItem(edge)
        for node in list(self._nodes.values()):
            self.removeItem(node)
        self._nodes.clear()
        self._edges.clear()
        self.scene_changed.emit()

    # ── auto-layout (force-directed) ──────────────────────────────────────────

    def auto_layout(self, iterations: int = 200):
        """Simple force-directed layout (Fruchterman–Reingold inspired)."""
        nodes = list(self._nodes.values())
        if len(nodes) < 2:
            return

        k  = math.sqrt((SCENE_SIZE * SCENE_SIZE) / len(nodes)) * 0.5
        pos = {n.node_id: QPointF(n.pos()) for n in nodes}

        def repulsion(d):
            return (k * k) / max(d, 1.0)

        def attraction(d):
            return (d * d) / k

        t = SCENE_SIZE * 0.1   # temperature

        edge_pairs = {(e.source.node_id, e.target.node_id) for e in self._edges.values()}

        for _ in range(iterations):
            disp = {nid: QPointF(0, 0) for nid in pos}

            # Repulsion
            nids = list(pos.keys())
            for i, u in enumerate(nids):
                for v in nids[i + 1:]:
                    dx = pos[u].x() - pos[v].x()
                    dy = pos[u].y() - pos[v].y()
                    d  = math.sqrt(dx * dx + dy * dy) or 0.01
                    f  = repulsion(d)
                    disp[u] += QPointF(dx / d * f, dy / d * f)
                    disp[v] -= QPointF(dx / d * f, dy / d * f)

            # Attraction
            for (uid, vid) in edge_pairs:
                if uid not in pos or vid not in pos:
                    continue
                dx = pos[uid].x() - pos[vid].x()
                dy = pos[uid].y() - pos[vid].y()
                d  = math.sqrt(dx * dx + dy * dy) or 0.01
                f  = attraction(d)
                disp[uid] -= QPointF(dx / d * f, dy / d * f)
                disp[vid] += QPointF(dx / d * f, dy / d * f)

            # Apply with temperature clamping
            for nid in pos:
                dx, dy = disp[nid].x(), disp[nid].y()
                d  = math.sqrt(dx * dx + dy * dy) or 0.01
                clamp = min(d, t)
                pos[nid] += QPointF(dx / d * clamp, dy / d * clamp)

            t *= 0.95  # cool

        # Commit
        old_pos = {n.node_id: QPointF(n.pos()) for n in nodes}
        deltas  = [(nid, old_pos[nid], pos[nid]) for nid in old_pos]
        self.undo_stack.push(_MoveNodesCmd(self, deltas))
        self.status_message.emit("Auto-layout applied.")

    # ── serialisation ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        from dw_utils.mindmap.constants import SAVE_FORMAT_VERSION
        return {
            "version": SAVE_FORMAT_VERSION,
            "nodes"  : [n.to_dict() for n in self._nodes.values()],
            "edges"  : [e.to_dict() for e in self._edges.values()],
        }

    def from_dict(self, data: dict):
        """Load graph from a dict (replaces current content)."""
        self.clear_graph()
        for nd in data.get("nodes", []):
            node = NodeItem.from_dict(nd)
            self._add_node_item(node)
        for ed in data.get("edges", []):
            src = self._nodes.get(ed["source"])
            tgt = self._nodes.get(ed["target"])
            if src and tgt:
                edge = EdgeItem(
                    source   = src,
                    target   = tgt,
                    label    = ed.get("label", ""),
                    color    = ed.get("color", DEFAULT_EDGE_COLOR),
                    width    = ed.get("width", DEFAULT_EDGE_WIDTH),
                    style    = ed.get("style", DEFAULT_EDGE_STYLE),
                    directed = ed.get("directed", DEFAULT_EDGE_DIRECTED),
                    edge_id  = ed.get("id"),
                )
                self._add_edge_item(edge)

    # ── mouse for edge drawing ─────────────────────────────────────────────────

    def start_edge_from(self, node: NodeItem):
        self._edge_src = node
        self.status_message.emit(f"Click target node to connect  ←  '{node.label}'")

    def cancel_edge_draw(self):
        self._edge_src = None
        self.status_message.emit("")

    # ── drawing events ────────────────────────────────────────────────────────

    def mouseReleaseEvent(self, event):
        # Finalise edge drawing when user clicks a target node
        if self._edge_src is not None:
            items = self.items(event.scenePos())
            for item in items:
                if isinstance(item, NodeItem) and item is not self._edge_src:
                    self.create_edge(self._edge_src, item)
                    self._edge_src = None
                    self.status_message.emit("Edge created.")
                    break
            else:
                if not any(isinstance(i, NodeItem) for i in items):
                    self._edge_src = None
                    self.status_message.emit("Edge cancelled.")

        # Record positions after drag for undo
        moved = []
        for item in self.selectedItems():
            if isinstance(item, NodeItem):
                nid = item.node_id
                old = self._drag_start_positions.get(nid)
                new = item.pos()
                if old and old != new:
                    moved.append((nid, old, new))
        if moved:
            self.undo_stack.push(_MoveNodesCmd(self, moved))
        self._drag_start_positions.clear()

        super().mouseReleaseEvent(event)

    def mousePressEvent(self, event):
        # Save start positions for move undo
        for item in self.selectedItems():
            if isinstance(item, NodeItem):
                self._drag_start_positions[item.node_id] = QPointF(item.pos())
        super().mousePressEvent(event)

    def drawBackground(self, painter: QPainter, rect: QRectF):
        super().drawBackground(painter, rect)
        if not self.snap_grid:
            return

        # Draw subtle grid
        pen = QPen(QColor(GRID_LINE_COLOR), 0.5)
        painter.setPen(pen)

        left   = int(rect.left())   - (int(rect.left())   % GRID_SIZE)
        top    = int(rect.top())    - (int(rect.top())    % GRID_SIZE)
        right  = int(rect.right())  + GRID_SIZE
        bottom = int(rect.bottom()) + GRID_SIZE

        for x in range(left, right, GRID_SIZE):
            painter.drawLine(x, int(rect.top()), x, int(rect.bottom()))
        for y in range(top, bottom, GRID_SIZE):
            painter.drawLine(int(rect.left()), y, int(rect.right()), y)







