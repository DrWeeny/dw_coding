"""
Constants and default style definitions for the Mind Map tool.
"""

# ── Node shapes ──────────────────────────────────────────────────────────────
SHAPE_ROUNDED_RECT  = "rounded_rect"
SHAPE_ELLIPSE       = "ellipse"
SHAPE_DIAMOND       = "diamond"
SHAPE_HEXAGON       = "hexagon"
SHAPE_PARALLELOGRAM = "parallelogram"
SHAPE_RECT          = "rect"

ALL_SHAPES = [
    SHAPE_ROUNDED_RECT,
    SHAPE_ELLIPSE,
    SHAPE_DIAMOND,
    SHAPE_HEXAGON,
    SHAPE_PARALLELOGRAM,
    SHAPE_RECT,
]

# ── Edge styles ───────────────────────────────────────────────────────────────
EDGE_SOLID  = "solid"
EDGE_DASHED = "dashed"
EDGE_DOTTED = "dotted"

ALL_EDGE_STYLES = [EDGE_SOLID, EDGE_DASHED, EDGE_DOTTED]

# ── Default node style ────────────────────────────────────────────────────────
DEFAULT_NODE_WIDTH   = 160
DEFAULT_NODE_HEIGHT  = 60
DEFAULT_NODE_SHAPE   = SHAPE_ROUNDED_RECT
DEFAULT_BG_COLOR     = "#2c3e50"
DEFAULT_BORDER_COLOR = "#1abc9c"
DEFAULT_TEXT_COLOR   = "#ecf0f1"
DEFAULT_FONT_SIZE    = 11
DEFAULT_OPACITY      = 1.0
DEFAULT_BORDER_WIDTH = 2.0

# ── Default edge style ────────────────────────────────────────────────────────
DEFAULT_EDGE_COLOR      = "#95a5a6"
DEFAULT_EDGE_WIDTH      = 2.0
DEFAULT_EDGE_STYLE      = EDGE_SOLID
DEFAULT_EDGE_DIRECTED   = True
DEFAULT_EDGE_LABEL      = ""

# ── Grid ──────────────────────────────────────────────────────────────────────
GRID_SIZE = 20
GRID_COLOR = "#1a1a2e"
GRID_LINE_COLOR = "#16213e"

# ── Scene ─────────────────────────────────────────────────────────────────────
SCENE_BG_COLOR   = "#0f0f1a"
SCENE_SIZE       = 8000   # px, square

# ── Minimap ──────────────────────────────────���────────────────────────────────
MINIMAP_WIDTH  = 200
MINIMAP_HEIGHT = 150

# ── Z-values ─────────────────────────────────────────────────────────────────
Z_EDGE = 0
Z_NODE = 1
Z_SELECTED = 10

# ── Category colours (used for the CFX template) ─────────────────────────────
PALETTE = {
    "launcher":    "#1a535c",
    "app":         "#4ecdc4",
    "maya":        "#f7fff7",
    "houdini":     "#ff6b6b",
    "cfx":         "#ffe66d",
    "anim":        "#6b4226",
    "sim":         "#a8dadc",
    "publish":     "#457b9d",
    "note":        "#6c757d",
}

# Dark versions for border
PALETTE_BORDER = {
    "launcher":    "#0d2b30",
    "app":         "#1a8c85",
    "maya":        "#2d6a4f",
    "houdini":     "#c0392b",
    "cfx":         "#c9a227",
    "anim":        "#3e1c04",
    "sim":         "#2a7f83",
    "publish":     "#1d3557",
    "note":        "#343a40",
}

TEXT_DARK  = "#1a1a2e"
TEXT_LIGHT = "#ecf0f1"

# JSON file version for forward-compatibility
SAVE_FORMAT_VERSION = 2

