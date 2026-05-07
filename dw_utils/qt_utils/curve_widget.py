"""
CurveRemapper - Maya-compatible PySide2/PySide6 curve editor widget.
Remaps values through an editable bezier curve with min/max ranges.

Usage (Maya script editor):
    import sys
    sys.path.insert(0, r"/path/to/script/")
    from curve_remapper import show_in_maya
    win = show_in_maya()

    win.remap(0.75)                              # single value
    win.curveChanged.connect(lambda: print(win.remap(0.5)))
"""

# ── PySide2 / PySide6 shim ────────────────────────────────────────────────────
try:
    from PySide6 import QtWidgets, QtCore, QtGui
    from PySide6.QtCore import Signal
    _PYSIDE6 = True
except ImportError:
    from PySide2 import QtWidgets, QtCore, QtGui
    from PySide2.QtCore import Signal
    _PYSIDE6 = False

import bisect

# ── Palette ───────────────────────────────────────────────────────────────────
_C = {
    "bg":       QtGui.QColor(38,  38,  38),
    "grid":     QtGui.QColor(55,  55,  55),
    "grid_maj": QtGui.QColor(72,  72,  72),
    "diag":     QtGui.QColor(80,  80,  80),
    "curve":    QtGui.QColor(72, 200, 130),
    "pt":       QtGui.QColor(210, 210, 210),
    "pt_hov":   QtGui.QColor(255, 230,  80),
    "pt_sel":   QtGui.QColor(72,  200, 130),
}

# Scene lives in pixel space: 0..SCENE_SIZE x 0..SCENE_SIZE
# This avoids any sub-pixel pen/radius issues that plagued the [0,1] version.
_SZ = 256


# ── Bezier math ───────────────────────────────────────────────────────────────

def _cbez(p0, p1, p2, p3, t):
    mt = 1.0 - t
    return mt**3*p0 + 3*mt**2*t*p1 + 3*mt*t**2*p2 + t**3*p3


def _solve_t(x0, cx0, cx1, x1, tx, tol=1e-5):
    lo, hi = 0.0, 1.0
    for _ in range(32):
        mid = (lo + hi) * 0.5
        bx  = _cbez(x0, cx0, cx1, x1, mid)
        if abs(bx - tx) < tol:
            return mid
        lo, hi = (mid, hi) if bx < tx else (lo, mid)
    return (lo + hi) * 0.5


def _eval_norm(points, x):
    """Evaluate spline at normalised x in [0,1]. points = [[nx,ny,ti,to], ...]"""
    if not points:
        return x
    if x <= points[0][0]:
        return points[0][1]
    if x >= points[-1][0]:
        return points[-1][1]
    xs  = [p[0] for p in points]
    i   = max(0, min(bisect.bisect_right(xs, x) - 1, len(points) - 2))
    x0, y0, _,  to = points[i]
    x1, y1, ti, _  = points[i + 1]
    w   = x1 - x0
    cx0 = x0 + w / 3.0;  cy0 = y0 + (w / 3.0) * to
    cx1 = x1 - w / 3.0;  cy1 = y1 - (w / 3.0) * ti
    t   = _solve_t(x0, cx0, cx1, x1, x)
    return _cbez(y0, cy0, cy1, y1, t)


# ── Coordinate conversion ─────────────────────────────────────────────────────
# Normalised (0,0) = bottom-left, (1,1) = top-right.
# Qt scene (0,0) = top-left, (SZ,SZ) = bottom-right.
# Mapping:  scene_x = nx * SZ,   scene_y = (1-ny) * SZ

def _n2s(nx, ny):
    return QtCore.QPointF(nx * _SZ, (1.0 - ny) * _SZ)

def _s2n(px, py):
    return px / _SZ, 1.0 - py / _SZ


# ── Control point ─────────────────────────────────────────────────────────────

_PR = 5   # radius in pixels


class _CP(QtWidgets.QGraphicsEllipseItem):
    def __init__(self, idx, owner):
        super().__init__(-_PR, -_PR, _PR * 2, _PR * 2)
        self._idx   = idx
        self._owner = owner
        self.setFlag(QtWidgets.QGraphicsItem.ItemIsMovable,            True)
        self.setFlag(QtWidgets.QGraphicsItem.ItemIsSelectable,         True)
        self.setFlag(QtWidgets.QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)
        self._hov = False
        self._style()
        self.setZValue(10)

    def _style(self):
        if   self.isSelected(): col = _C["pt_sel"]
        elif self._hov:         col = _C["pt_hov"]
        else:                   col = _C["pt"]
        self.setBrush(QtGui.QBrush(col))
        self.setPen(QtGui.QPen(col.darker(160), 1.0))

    def hoverEnterEvent(self, e): self._hov = True;  self._style(); super().hoverEnterEvent(e)
    def hoverLeaveEvent(self, e): self._hov = False; self._style(); super().hoverLeaveEvent(e)
    def paint(self, painter, option, widget=None): self._style(); super().paint(painter, option, widget)

    def itemChange(self, change, value):
        if change == QtWidgets.QGraphicsItem.ItemPositionChange:
            px = max(0.0, min(float(_SZ), value.x()))
            py = max(0.0, min(float(_SZ), value.y()))
            nx, ny = _s2n(px, py)
            pts = self._owner.points
            if self._idx > 0:
                nx = max(nx, pts[self._idx - 1][0] + 0.005)
            if self._idx < len(pts) - 1:
                nx = min(nx, pts[self._idx + 1][0] - 0.005)
            return _n2s(nx, max(0.0, min(1.0, ny)))

        if change == QtWidgets.QGraphicsItem.ItemPositionHasChanged:
            nx, ny = _s2n(self.pos().x(), self.pos().y())
            self._owner.points[self._idx][0] = nx
            self._owner.points[self._idx][1] = max(0.0, min(1.0, ny))
            self._owner._refresh_curve()

        return super().itemChange(change, value)

    def mouseDoubleClickEvent(self, e):
        if len(self._owner.points) > 2:
            self._owner.remove_point(self._idx)
        super().mouseDoubleClickEvent(e)


# ── Scene ─────────────────────────────────────────────────────────────────────

_DEFAULTS = [[0.0, 0.0, 1.0, 1.0], [1.0, 1.0, 1.0, 1.0]]

_PRESETS = {
    "linear":   [[0.0, 0.0, 1.0, 1.0], [1.0, 1.0, 1.0, 1.0]],
    "ease in":  [[0.0, 0.0, 0.0, 0.0], [1.0, 1.0, 1.0, 1.0]],
    "ease out": [[0.0, 0.0, 1.0, 1.0], [1.0, 1.0, 0.0, 0.0]],
    "ease":     [[0.0, 0.0, 0.0, 0.0], [1.0, 1.0, 0.0, 0.0]],
    "smooth":   [[0.0, 0.0, 0.0, 0.0], [0.5, 0.5, 1.0, 1.0], [1.0, 1.0, 0.0, 0.0]],
    "s-curve":  [[0.0, 0.0, 0.0, 0.0], [0.25, 0.1, 2.0, 2.0], [0.75, 0.9, 2.0, 2.0], [1.0, 1.0, 0.0, 0.0]],
    "invert":   [[0.0, 1.0, -1.0, -1.0], [1.0, 0.0, -1.0, -1.0]],
}


class CurveScene(QtWidgets.QGraphicsScene):
    curveChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSceneRect(0, 0, _SZ, _SZ)
        self.points      = [list(p) for p in _DEFAULTS]
        self._cp_items   = []
        self._curve_item = None
        self._rebuild()

    def evaluate(self, x):          return _eval_norm(self.points, x)
    def reset(self):                self.points = [list(p) for p in _DEFAULTS]; self._rebuild(); self.curveChanged.emit()
    def set_preset(self, name):
        if name in _PRESETS:
            self.points = [list(p) for p in _PRESETS[name]]; self._rebuild(); self.curveChanged.emit()
    def remove_point(self, idx):
        if len(self.points) <= 2: return
        del self.points[idx]; self._rebuild(); self.curveChanged.emit()

    def _rebuild(self):
        self.clear()
        self._cp_items   = []
        self._curve_item = None
        self._draw_bg()
        pen_curve = QtGui.QPen(_C["curve"], 2.0, QtCore.Qt.SolidLine,
                               QtCore.Qt.RoundCap, QtCore.Qt.RoundJoin)
        self._curve_item = self.addPath(QtGui.QPainterPath(), pen_curve)
        self._curve_item.setZValue(5)
        for i, pt in enumerate(self.points):
            cp = _CP(i, self)
            self.addItem(cp)
            cp.setPos(_n2s(pt[0], pt[1]))
            self._cp_items.append(cp)
        self._refresh_curve()

    def _draw_bg(self):
        steps = 10
        for i in range(steps + 1):
            t   = i / steps
            px  = t * _SZ
            py  = t * _SZ
            maj = (i % (steps // 2) == 0)
            pen = QtGui.QPen(_C["grid_maj"] if maj else _C["grid"],
                             1.0 if maj else 0.5)
            self.addLine(px, 0,   px, _SZ, pen)
            self.addLine(0,  py, _SZ, py,  pen)
        # Diagonal: normalised (0,0)->(1,1) = scene (0,SZ)->(SZ,0)
        pen_d = QtGui.QPen(_C["diag"], 1.0, QtCore.Qt.DashLine)
        p0 = _n2s(0.0, 0.0)
        p1 = _n2s(1.0, 1.0)
        self.addLine(p0.x(), p0.y(), p1.x(), p1.y(), pen_d)

    def _refresh_curve(self):
        self.points.sort(key=lambda p: p[0])
        # Reposition control points without triggering recursive updates
        for i, cp in enumerate(self._cp_items):
            cp._idx = i
            cp.setFlag(QtWidgets.QGraphicsItem.ItemSendsGeometryChanges, False)
            cp.setPos(_n2s(self.points[i][0], self.points[i][1]))
            cp.setFlag(QtWidgets.QGraphicsItem.ItemSendsGeometryChanges, True)
        # Draw curve
        path = QtGui.QPainterPath()
        path.moveTo(_n2s(0.0, self.evaluate(0.0)))
        steps = 200
        for i in range(1, steps + 1):
            nx = i / steps
            path.lineTo(_n2s(nx, self.evaluate(nx)))
        if self._curve_item:
            self._curve_item.setPath(path)
        self.curveChanged.emit()

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.RightButton:
            item = self.itemAt(event.scenePos(), QtGui.QTransform())
            if item is None or item is self._curve_item:
                px, py = event.scenePos().x(), event.scenePos().y()
                nx = max(0.01, min(0.99, px / _SZ))
                self.points.append([nx, self.evaluate(nx), 1.0, 1.0])
                self._rebuild()
                self.curveChanged.emit()
                return
        super().mousePressEvent(event)


# ── View ──────────────────────────────────────────────────────────────────────

class CurveView(QtWidgets.QGraphicsView):
    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHint(QtGui.QPainter.Antialiasing, True)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setBackgroundBrush(QtGui.QBrush(_C["bg"]))
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.setDragMode(QtWidgets.QGraphicsView.NoDrag)
        self.setStyleSheet("border: 1px solid #505050;")

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.fitInView(self.scene().sceneRect(), QtCore.Qt.IgnoreAspectRatio)

    def showEvent(self, e):
        super().showEvent(e)
        self.fitInView(self.scene().sceneRect(), QtCore.Qt.IgnoreAspectRatio)


# ── Range spinbox row ─────────────────────────────────────────────────────────

class _RangeRow(QtWidgets.QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        ss = ("QDoubleSpinBox{background:#252525;color:#bbb;border:1px solid #505050;"
              "border-radius:3px;padding:1px 3px;}"
              "QDoubleSpinBox::up-button,QDoubleSpinBox::down-button{width:14px;}")

        def _spin(v):
            s = QtWidgets.QDoubleSpinBox()
            s.setRange(-99999.0, 99999.0); s.setValue(v)
            s.setDecimals(3); s.setSingleStep(0.1); s.setFixedWidth(78)
            s.setStyleSheet(ss); return s

        def _lbl(t):
            l = QtWidgets.QLabel(t); l.setStyleSheet("color:#666;font-size:10px;"); return l

        self.in_min  = _spin(0.0); self.in_max  = _spin(1.0)
        self.out_min = _spin(0.0); self.out_max = _spin(1.0)

        for lbl, w in [("In min", self.in_min), ("In max", self.in_max),
                        ("Out min", self.out_min), ("Out max", self.out_max)]:
            lay.addWidget(_lbl(lbl)); lay.addWidget(w); lay.addSpacing(3)
        lay.addStretch()

        for w in (self.in_min, self.in_max, self.out_min, self.out_max):
            w.valueChanged.connect(self.changed)


# ── Main widget ───────────────────────────────────────────────────────────────

class CurveRemapperWidget(QtWidgets.QWidget):
    curveChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Curve Remapper")
        self.setMinimumSize(400, 420)
        self._scene  = CurveScene()
        self._ranges = _RangeRow()
        self._scene.blockSignals(True)
        self._build_ui()
        self._scene.blockSignals(False)
        self._wire()
        self._refresh_preview()

    # ── Public ────────────────────────────────────────────────────────────────

    def remap(self, value):
        r  = self._ranges
        i0, i1 = r.in_min.value(), r.in_max.value()
        o0, o1 = r.out_min.value(), r.out_max.value()
        if i1 == i0: return o0
        t = max(0.0, min(1.0, (value - i0) / (i1 - i0)))
        return o0 + self._scene.evaluate(t) * (o1 - o0)

    def evaluate(self, t):   return self._scene.evaluate(t)

    def get_lut(self, steps=256):
        i0, i1 = self._ranges.in_min.value(), self._ranges.in_max.value()
        return [self.remap(i0 + k / (steps - 1) * (i1 - i0)) for k in range(steps)]

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # Preset bar
        prow = QtWidgets.QHBoxLayout(); prow.setSpacing(3)
        pl = QtWidgets.QLabel("Preset:"); pl.setStyleSheet("color:#666;font-size:11px;")
        prow.addWidget(pl)
        btn_ss = ("QPushButton{background:#2e2e2e;color:#999;border:1px solid #505050;"
                  "border-radius:3px;font-size:10px;padding:1px 6px;}"
                  "QPushButton:hover{background:#3a3a3a;color:#ddd;}"
                  "QPushButton:pressed{background:#222;}")
        for name in _PRESETS:
            b = QtWidgets.QPushButton(name); b.setFixedHeight(20); b.setStyleSheet(btn_ss)
            b.clicked.connect(lambda chk=False, n=name: self._scene.set_preset(n))
            prow.addWidget(b)
        prow.addStretch()
        rst = QtWidgets.QPushButton("Reset"); rst.setFixedHeight(20)
        rst.setStyleSheet("QPushButton{background:#3a1f1f;color:#d88;border:1px solid #633;"
                          "border-radius:3px;font-size:10px;padding:1px 6px;}"
                          "QPushButton:hover{background:#4a2828;color:#faa;}")
        rst.clicked.connect(self._scene.reset); prow.addWidget(rst)
        root.addLayout(prow)

        # View
        self._view = CurveView(self._scene)
        self._view.setMinimumHeight(260)
        root.addWidget(self._view)

        hint = QtWidgets.QLabel("Right-click: add point   Double-click point: remove")
        hint.setStyleSheet("color:#404040;font-size:10px;")
        hint.setAlignment(QtCore.Qt.AlignCenter)
        root.addWidget(hint)

        sep = QtWidgets.QFrame(); sep.setFrameShape(QtWidgets.QFrame.HLine)
        sep.setStyleSheet("color:#404040;"); root.addWidget(sep)

        root.addWidget(self._ranges)

        # Preview
        srow = QtWidgets.QHBoxLayout(); srow.setSpacing(6)
        pl2 = QtWidgets.QLabel("Preview:"); pl2.setStyleSheet("color:#666;font-size:11px;")
        srow.addWidget(pl2)
        self._slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self._slider.setRange(0, 1000); self._slider.setValue(500)
        self._slider.setStyleSheet(
            "QSlider::groove:horizontal{background:#202020;height:4px;border-radius:2px;}"
            "QSlider::handle:horizontal{background:#48c878;width:12px;height:12px;"
            "border-radius:6px;margin:-4px 0;}")
        srow.addWidget(self._slider)
        self._plbl = QtWidgets.QLabel("in: 0.500  \u2192  out: 0.500")
        self._plbl.setStyleSheet("color:#48c878;font-size:11px;font-family:monospace;")
        self._plbl.setMinimumWidth(200); srow.addWidget(self._plbl)
        root.addLayout(srow)

        self.setStyleSheet("CurveRemapperWidget{background:#242424;}")

    def _wire(self):
        self._scene.curveChanged.connect(self._on_change)
        self._ranges.changed.connect(self._on_change)
        self._slider.valueChanged.connect(self._refresh_preview)

    def _on_change(self):
        self._refresh_preview(); self.curveChanged.emit()

    def _refresh_preview(self):
        t01 = self._slider.value() / 1000.0
        i0  = self._ranges.in_min.value()
        i1  = self._ranges.in_max.value()
        raw = i0 + t01 * (i1 - i0)
        self._plbl.setText("in: {:.3f}  \u2192  out: {:.3f}".format(raw, self.remap(raw)))


# ── Maya launcher ─────────────────────────────────────────────────────────────

def show_in_maya():
    try:
        import maya.OpenMayaUI as omui
        ptr = omui.MQtUtil.mainWindow()
        try:    from shiboken6 import wrapInstance
        except: from shiboken2 import wrapInstance
        maya_win = wrapInstance(int(ptr), QtWidgets.QWidget)
        win = CurveRemapperWidget(parent=maya_win)
        win.setWindowFlags(QtCore.Qt.Window)
    except Exception as e:
        print("curve_remapper: cannot parent to Maya:", e)
        win = CurveRemapperWidget()
    win.show(); win.raise_(); return win


if __name__ == "__main__":
    import sys
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    w = CurveRemapperWidget(); w.show()
    sys.exit(app.exec() if _PYSIDE6 else app.exec_())


#
# From Maya's script editor
# import sys
# sys.path.insert(0, "/path/to/your/script/")
# from curve_remapper import show_in_maya
#
# win = show_in_maya()
#
# # Later, get a remapped value:
# win.remap(0.75)          # single value
# win.get_lut(steps=256)   # full LUT list
# win.curveChanged.connect(lambda: print(win.remap(0.5)))