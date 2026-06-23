"""
forge_cmds/icons.py - small drawn badges for DynForge guide rows.

No external icon files: each creation mode (edge / face / locator) is rendered
as a coloured rounded badge with a letter, ringed by the guide status colour.
The list panel calls make_mode_icon() to refresh a row's icon after build.
"""

from __future__ import annotations

from dw_maya.DynForge.forge_cmds.compat import QtCore, QtGui, Qt


# Letter + fill colour per creation mode.
_MODE_STYLE = {
    "edge":    ("E", QtGui.QColor("#4a90d9")),
    "face":    ("F", QtGui.QColor("#6ab04c")),
    "locator": ("L", QtGui.QColor("#e58e26")),
}

# Ring colour per guide status.
_STATUS_RING = {
    "pending": QtGui.QColor("#d9a441"),
    "built":   QtGui.QColor("#5fd35f"),
    "broken":  QtGui.QColor("#c0392b"),
}


def make_mode_icon(mode:   str,
                   status: str = "pending",
                   size:   int = 18,) -> QtGui.QIcon:
    """Return a QIcon badge for a guide of `mode` in state `status`."""
    letter, fill = _MODE_STYLE.get(mode, ("?", QtGui.QColor("#888888")))
    if status == "pending":
        fill = fill.darker(170)   # dim until built

    pix = QtGui.QPixmap(size, size)
    pix.fill(Qt.transparent)

    painter = QtGui.QPainter(pix)
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)

    rect = QtCore.QRectF(1.5, 1.5, size - 3, size - 3)
    painter.setBrush(fill)
    ring = QtGui.QPen(_STATUS_RING.get(status, fill))
    ring.setWidthF(1.5)
    painter.setPen(ring)
    painter.drawRoundedRect(rect, 4, 4)

    painter.setPen(QtGui.QPen(QtGui.QColor("#ffffff")))
    font = painter.font()
    font.setBold(True)
    font.setPointSizeF(max(7.0, size * 0.5))
    painter.setFont(font)
    painter.drawText(rect, Qt.AlignCenter, letter)
    painter.end()

    return QtGui.QIcon(pix)