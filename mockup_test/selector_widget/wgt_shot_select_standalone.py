"""
Standalone, pipeline-agnostic version of wgt_shot_select.

Identical in behaviour to AnimBakeMan/wgt_shot_select.py but all pipeline
dependencies (dp_pub, pyu) are replaced with the local mockup_data module so
the widget can be developed and tested at home without a rez / pipeline
environment.

Features

- Runs with plain PySide2 or PySide6 (via the Qt.py shim or a thin local shim).
- Resolves token chains from mockup_data._SHOT_TREE / _ASSET_TREE.
- Supports all modes: expanded, compact, listview, combo_filtered.
- Preserves orange-highlight logic for "possible but not yet published" values.
- Includes a __main__ block with a demo window identical to the original.

Usage

    # From the selector_widget/ directory
    python wgt_shot_select_standalone.py

    # Or import in your own script
    from selector_widget.wgt_shot_select_standalone import PublishSelector, SelectorType, Mode

Classes

    - PublishSelector: Main multi-token selector widget.
    - HighlightableComboBox: Framed combobox with orange-item support.

Integration

    No DCC context required.  The mockup_data module provides a MockProject
    whose API surface mirrors dp_pub.project so this file can be diffed
    directly against the production wgt_shot_select.py.

Dependencies

    Internal : selector_widget/mockup_data.py
    External : PySide2 >= 5.12  (or PySide6 via Qt.py shim)

Version
    1.0.0

Authors
    CFX TD team
"""

# ---------------------------------------------------------------------------
# Qt import — try Qt.py first, fall back to direct PySide2 / PySide6
# ---------------------------------------------------------------------------
try:
    from Qt import QtWidgets, QtGui, QtCore
except ImportError:
    try:
        from PySide2 import QtWidgets, QtGui, QtCore
    except ImportError:
        from PySide6 import QtWidgets, QtGui, QtCore

from contextlib import contextmanager
from enum import Enum
from typing import Union, Dict, List, Tuple
from functools import partial
import os

# ---------------------------------------------------------------------------
# Pipeline replacement: use mockup_data instead of dp_pub / pyu
# ---------------------------------------------------------------------------
import sys
import pathlib
# Make sure the selector_widget/ directory is importable regardless of cwd
_HERE = pathlib.Path(__file__).parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE.parent))  # cfxTools root

import standalone.mockup_data as _mock_project_module


# ---------------------------------------------------------------------------
# Thin replacements for the two pyu helpers used in the original
# ---------------------------------------------------------------------------

def _basename(path: str) -> str:
    return os.path.basename(path)


def _splitext(path: str) -> tuple:
    return os.path.splitext(path)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class SelectorType(Enum):
    """Whether the selector handles shots or assets."""
    shot = 0
    asset = 1


class Direction(Enum):
    horizontal = 0
    vertical = 1


class Mode(Enum):
    ultra_compact  = 0
    compact        = 1  # comboboxes + one shared listview
    expanded       = 2  # comboboxes + per-token listviews
    listview       = 3  # listviews only
    combo_filtered = 4  # comboboxes + filter edits


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_enum(enum_class, value):
    """
    Parse an enum value from instance, int, or str.

    Args:
        enum_class: The Enum subclass to parse into.
        value: An existing member, an int index, or a string name.

    Returns:
        An instance of enum_class.
    """
    if isinstance(value, enum_class):
        return value
    elif hasattr(value, '__class__') and hasattr(value.__class__, '__bases__'):
        try:
            if issubclass(value.__class__, enum_class):
                return value
        except TypeError:
            pass
    if isinstance(value, int):
        return enum_class(value)
    elif isinstance(value, str):
        try:
            return enum_class[value]
        except KeyError:
            raise ValueError(
                f"Invalid {enum_class.__name__} name: '{value}'. "
                f"Valid values: {[m.name for m in enum_class]}"
            )
    raise TypeError(
        f"Invalid type for {enum_class.__name__}: {type(value)}. "
        f"Must be {enum_class.__name__}, int, or str."
    )


def get_token_order_for_type(selector_type: SelectorType, limit: int = None) -> list:
    """
    Return the ordered token list for the given selector type.

    Args:
        selector_type: SelectorType.shot or SelectorType.asset
        limit: Optional number of tokens to keep (from the start).

    Returns:
        list: e.g. ['category', 'name', 'variation', 'department', 'lod']
    """
    proj = _mock_project_module.get()
    if selector_type == SelectorType.asset:
        token_order = proj.VersionAliases.get(
            "asset", ["category", "name", "variation", "department", "lod", "revision"]
        )
    else:
        token_order = proj.VersionAliases.get(
            "shot", ["episode", "sequence", "shot", "department", "element", "revision"]
        )
    if limit and isinstance(limit, int):
        if 0 < limit <= len(token_order):
            token_order = token_order[:limit]
    return token_order


def resolve_token_chain(
    token_order: list = None,
    default_keys: Union[Dict[str, str], List[str]] = None,
    selector_type: SelectorType = SelectorType.shot,
) -> Tuple[dict, dict]:
    """
    Walk the token chain and return the current selection and available values.

    Args:
        token_order:   Ordered list of token names to resolve.
        default_keys:  Dict or list of preferred default values.
        selector_type: SelectorType.shot or SelectorType.asset.

    Returns:
        tokens: {token_name: selected_value, ...}
        data:   {token_name: [all_possible_values], ...}
    """
    proj = _mock_project_module.get()
    pattern = proj.get_publish_dir_pattern()

    if not token_order:
        token_order = get_token_order_for_type(selector_type)

    type_name = "asset" if selector_type == SelectorType.asset else "shot"

    tokens: dict = {}
    data:   dict = {}

    for token_wrap in token_order:
        result = proj.next_token_values(type_name, pattern, **tokens)
        if not result:
            break
        token_name, values = result
        filtered = sorted([v for v in values if "." not in v])
        if not filtered:
            break

        selection = filtered[0]
        if isinstance(default_keys, dict):
            selection = default_keys.get(token_name, selection)
        elif isinstance(default_keys, list):
            default_copy = list(default_keys)
            for val in default_copy:
                if val in filtered:
                    selection = val
                    default_keys.remove(val)
                    break

        tokens[token_name] = selection
        data[token_name] = filtered

    return tokens, data


@contextmanager
def block_signal(signal, slot):
    """Temporarily disconnect a signal then reconnect it."""
    try:
        signal.disconnect()
        yield
    finally:
        signal.connect(slot)


def block_ui_update(method):
    """Decorator that prevents re-entrant UI updates."""
    def wrapper(self, *args, **kwargs):
        if getattr(self, "_block_ui_update", False):
            return
        self._block_ui_update = True
        try:
            return method(self, *args, **kwargs)
        finally:
            self._block_ui_update = False
    return wrapper


# ---------------------------------------------------------------------------
# HighlightableComboBox
# ---------------------------------------------------------------------------

class HighlightableComboBox(QtWidgets.QWidget):
    """
    Framed combobox with orange-item highlighting and right-click signal.

    Attributes:
        tokens:       Resolved tokens up to this combobox (for context queries).
        all_items:    Full unfiltered item list.
        orange_items: Set of item texts that are coloured orange.

    Example:
        cb = HighlightableComboBox()
        cb.addItems(["apple", "banana"])
        cb.add_possible_values(["cherry"], color="orange")
    """

    rightClicked        = QtCore.Signal(QtWidgets.QWidget)
    currentTextChanged  = QtCore.Signal(str)
    currentIndexChanged = QtCore.Signal(int)

    def __init__(self):
        super().__init__()

        self.tokens      = {}
        self.all_items   = []
        self.orange_items: set = set()

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)

        self.frame = QtWidgets.QFrame()
        self.frame.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.frame.setStyleSheet(
            "QFrame { border: 2px solid transparent; border-radius: 4px; }"
        )

        self.combo = QtWidgets.QComboBox()
        self.combo.installEventFilter(self)
        self.combo.currentTextChanged.connect(self.currentTextChanged)
        self.combo.currentIndexChanged.connect(self.currentIndexChanged)
        self.combo.currentTextChanged.connect(self._update_text_color)

        frame_layout = QtWidgets.QVBoxLayout(self.frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.addWidget(self.combo)

        layout.addWidget(self.frame)

    # ------------------------------------------------------------------
    # Forwarded QComboBox API
    # ------------------------------------------------------------------

    def set_text(self, text: str):
        idx = self.combo.findText(text)
        if idx != -1:
            self.combo.setCurrentIndex(idx)

    def currentText(self) -> str:
        return self.combo.currentText()

    def setCurrentText(self, text: str):
        self.combo.setCurrentText(text)

    def findText(self, text: str) -> int:
        return self.combo.findText(text)

    def addItem(self, item: str):
        self.all_items.append(item)
        return self.combo.addItem(item)

    def addItems(self, item_list: list):
        self.all_items = list(item_list)
        return self.combo.addItems(item_list)

    def setItemData(self, *args, **kwargs):
        return self.combo.setItemData(*args, **kwargs)

    def count(self) -> int:
        return self.combo.count()

    def itemText(self, index: int) -> str:
        return self.combo.itemText(index)

    def clear(self):
        self.combo.clear()
        self.orange_items.clear()
        self.combo.setStyleSheet("")

    def blockSignals(self, block: bool) -> bool:  # type: ignore[override]
        # Forward to the inner combo so signal blocking works as expected
        self.combo.blockSignals(block)
        return super().blockSignals(block)

    def setEnabled(self, enabled: bool):
        self.combo.setEnabled(enabled)

    # ------------------------------------------------------------------
    # Orange-item helpers
    # ------------------------------------------------------------------

    def add_possible_values(self, values: list, color: str = "orange"):
        """
        Append values that don't yet exist, coloured with *color*.

        Args:
            values: Items to add if not already present.
            color:  Qt colour name or hex string (default: "orange").
        """
        for value in values:
            if self.combo.findText(value) == -1:
                index = self.combo.count()
                self.combo.addItem(value)
                self.all_items.append(value)
                self.combo.setItemData(index, QtGui.QColor(color), QtCore.Qt.ForegroundRole)
                self.orange_items.add(value)
        self._update_text_color(self.combo.currentText())

    def _update_text_color(self, text: str):
        if text in self.orange_items:
            self.combo.setStyleSheet("QComboBox { color: orange; }")
        else:
            self.combo.setStyleSheet("")

    # ------------------------------------------------------------------
    # Highlight border
    # ------------------------------------------------------------------

    def set_highlight(self, on: bool = True, color: str = "#90ee90"):
        if on:
            self.frame.setStyleSheet(f"""
                QFrame {{
                    border: 2px solid {color};
                    border-radius: 4px;
                    background-color: rgba(144, 238, 144, 0.1);
                }}
            """)
        else:
            self.frame.setStyleSheet(
                "QFrame { border: 2px solid transparent; border-radius: 4px; }"
            )

    # ------------------------------------------------------------------
    # Event filter (right-click)
    # ------------------------------------------------------------------

    def eventFilter(self, obj, event):
        if isinstance(obj, QtWidgets.QComboBox):
            if event.type() == QtCore.QEvent.MouseButtonPress:
                if event.button() == QtCore.Qt.RightButton:
                    self.rightClicked.emit(self)
                    return True
        return super().eventFilter(obj, event)


# ---------------------------------------------------------------------------
# PublishSelector
# ---------------------------------------------------------------------------

class PublishSelector(QtWidgets.QWidget):
    """
    Multi-token selector widget — drop-in replacement for the production
    AnimBakeMan.wgt_shot_select.PublishSelector.

    Attributes:
        selector_type:         SelectorType.shot or SelectorType.asset.
        token_wrap_list:       Ordered token names used by this instance.
        _cb:                   List of HighlightableComboBox widgets (one per token).
        list_views:            List of QListView widgets (expanded / listview modes).
        proxy_models:          Corresponding QSortFilterProxyModel instances.
        filter_edits:          QLineEdit filter widgets.
        current_combo_selection: {token: value} dict for the active selection.
        data:                  {token: [values]} dict of all available choices.

    Example:
        selector = PublishSelector(
            mode=Mode.expanded,
            direction=Direction.vertical,
            label=True,
            selector_type=SelectorType.asset,
            limit=5,
            default_keys={"category": "animal", "name": "cat"},
        )
    """

    selectionChanged = QtCore.Signal(dict)

    def __init__(
        self,
        mode: Union[int, str, Mode] = 2,
        direction: Union[int, str, Direction] = 1,
        label: bool = False,
        limit: int = None,
        default_keys: Union[list, dict] = None,
        selector_type: Union[SelectorType, int, str] = SelectorType.shot,
        parent=None,
        **kwargs,
    ):
        """
        Args:
            mode:          Display mode (int 0-4, string name, or Mode enum).
            direction:     0=horizontal, 1=vertical (int, string, or Direction enum).
            label:         Show token name labels above combos.
            limit:         Slice the token list to this many entries from the start.
            default_keys:  Preferred default values (dict or list).
            selector_type: SelectorType.shot / SelectorType.asset (or int/str).
            parent:        Parent QWidget.
            **kwargs:      width, height — minimum widget dimensions.
        """
        QtWidgets.QWidget.__init__(self, parent)

        _width  = kwargs.get("width",  None)
        _height = kwargs.get("height", None)
        if _width  is not None: self.setMinimumWidth(_width)
        if _height is not None: self.setMinimumHeight(_height)

        self.selector_type   = parse_enum(SelectorType, selector_type)
        self.token_wrap_list = get_token_order_for_type(self.selector_type, limit)

        self._clear_opti           = 0
        self.fixed_width           = 200
        self.default_keys          = default_keys
        self.data: dict            = {}
        self.current_combo_selection = None
        self._cb: list             = []
        self.list_views: list      = []
        self.filter_edits: list    = []
        self.proxy_models: list    = []
        self._block_ui_update      = False

        self.mode      = parse_enum(Mode, mode)
        self.direction = parse_enum(Direction, direction)
        self.display_label = label

        # Settings persistence (uses plain QSettings with no pyu.path)
        programbase = _splitext(_basename(__file__))[0]
        self.settings = QtCore.QSettings("cfxshotpubsel_standalone", programbase)
        for sd in self.token_wrap_list:
            _data = self.settings.value(sd)
            if _data is not None:
                if not isinstance(self.default_keys, dict):
                    self.default_keys = {}
                self.default_keys[sd] = _data

        self.proj    = _mock_project_module.get()
        self.pattern = self.proj.get_publish_dir_pattern()

        self.build_ui()
        self.populate_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def build_ui(self):
        if self.direction == Direction.horizontal:
            combo_layout = QtWidgets.QHBoxLayout()
            label_layout = QtWidgets.QHBoxLayout() if self.display_label else None
            list_layout  = QtWidgets.QHBoxLayout() if self.mode == Mode.expanded else None
        else:
            combo_layout = QtWidgets.QVBoxLayout()
            label_layout = QtWidgets.QVBoxLayout() if self.display_label else None
            list_layout  = QtWidgets.QVBoxLayout() if self.mode == Mode.expanded else None

        for i, token in enumerate(self.token_wrap_list):
            combo_filter_layout = QtWidgets.QVBoxLayout()
            combo = HighlightableComboBox()
            combo.label = token
            combo.setFixedWidth(self.fixed_width)
            self._cb.append(combo)
            combo.currentIndexChanged.connect(partial(self.on_ui_changed, "combobox", i))

            if self.display_label:
                lbl = QtWidgets.QLabel(token)
                label_layout.addWidget(lbl)
            combo_filter_layout.addWidget(combo)
            combo_layout.addLayout(combo_filter_layout)

            if self.mode in [Mode.expanded, Mode.listview]:
                column_layout = QtWidgets.QVBoxLayout()

                listview = QtWidgets.QListView()
                listview.setFixedWidth(self.fixed_width)

                proxy = QtCore.QSortFilterProxyModel()
                proxy.setFilterCaseSensitivity(QtCore.Qt.CaseInsensitive)
                proxy.setFilterKeyColumn(0)

                model = QtGui.QStandardItemModel()
                proxy.setSourceModel(model)

                listview.setModel(proxy)
                listview.selectionModel().selectionChanged.connect(
                    partial(self.on_ui_changed, "listview", i)
                )
                self.proxy_models.append(proxy)
                self.list_views.append(listview)

                column_layout.addWidget(listview)
                list_layout.addLayout(column_layout)

            if self.mode.value > 1:
                filter_edit = QtWidgets.QLineEdit()
                filter_edit.setPlaceholderText(f"Filter {token}…")
                filter_edit.setClearButtonEnabled(True)
                filter_edit.setFixedWidth(self.fixed_width)
                self.filter_edits.append(filter_edit)
                filter_edit.textChanged.connect(partial(self.apply_filter, i))

                if self.mode == Mode.listview:
                    column_layout.addWidget(filter_edit)
                elif self.mode in [Mode.expanded, Mode.combo_filtered]:
                    combo_filter_layout.insertWidget(0, filter_edit)

        if self.mode == Mode.compact:
            self.shared_listview = QtWidgets.QListView()
            self.shared_listview.setModel(QtGui.QStandardItemModel())

        main_layout = (
            QtWidgets.QVBoxLayout(self)
            if self.direction == Direction.horizontal
            else QtWidgets.QHBoxLayout(self)
        )
        main_layout.setAlignment(QtCore.Qt.AlignLeft)

        if label_layout:
            main_layout.addLayout(label_layout)
        main_layout.addLayout(combo_layout)

        if self.mode == Mode.expanded and list_layout:
            main_layout.addLayout(list_layout)
        elif self.mode == Mode.compact:
            main_layout.addWidget(self.shared_listview)

        self.setLayout(main_layout)

    # ------------------------------------------------------------------
    # Data population
    # ------------------------------------------------------------------

    def get_current_selection(self) -> dict:
        """
        Return the current value for every token by reading directly from combos.

        Returns:
            dict: {token_name: current_text}
        """
        return {
            token_name: self._cb[i].currentText()
            for i, token_name in enumerate(self.token_wrap_list)
        }

    def flatten_selection_path(self, current_cb_dic: dict) -> list:
        """Return selected values in token order."""
        return [current_cb_dic.get(key) for key in self.token_wrap_list]

    def populate_ui(self, tokens=None):
        """Repopulate all comboboxes from the token chain."""
        self.current_combo_selection, self.data = resolve_token_chain(
            self.token_wrap_list,
            tokens or self.default_keys,
            selector_type=self.selector_type,
        )

        selected_values = self.flatten_selection_path(self.current_combo_selection)
        resolved_tokens: dict = {}

        for i, token_name in enumerate(self.token_wrap_list):
            values = self.data.get(token_name, [])

            combo = self._cb[i]
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(values)
            combo.setEnabled(bool(values))

            selected_value = (
                selected_values[i]
                if i < len(selected_values)
                else (values[0] if values else "")
            )
            combo.set_text(selected_value)
            combo.tokens = resolved_tokens.copy()
            resolved_tokens[token_name] = selected_value
            combo.blockSignals(False)

            if self.mode == Mode.expanded and i < len(self.proxy_models):
                model = self.proxy_models[i].sourceModel()
                model.clear()
                items_qt = [
                    QtGui.QStandardItem(v)
                    for v in values
                    if not v.startswith(".")
                ]
                model.invisibleRootItem().appendRows(items_qt)

                with block_signal(
                    self.list_views[i].selectionModel().selectionChanged,
                    partial(self.on_ui_changed, "listview", i),
                ):
                    self.select_item_in_listview(self.proxy_models[i], i, selected_value)

            if self.filter_edits:
                filter_text = self.filter_edits[i].text()
                if filter_text:
                    QtCore.QTimer.singleShot(
                        0, partial(self.apply_filter, i, filter_text)
                    )

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    @block_ui_update
    def on_ui_changed(self, wgt_type: str, index: int, *args):
        tokens: dict = {}
        for i in range(index + 1):
            key = self.token_wrap_list[i]
            if wgt_type == "combobox":
                tokens[key] = self._cb[i].currentText()
            elif wgt_type == "listview":
                tokens[key] = self.get_selected_item_in_listview_text(i)
                self._cb[i].set_text(tokens[key])
            else:
                raise ValueError(f"Unsupported widget type: {wgt_type}")

        self.populate_ui(tokens)
        self.selectionChanged.emit(self.current_combo_selection)

    # ------------------------------------------------------------------
    # ListView helpers
    # ------------------------------------------------------------------

    def get_selected_item_in_listview_text(self, index: int) -> str:
        """Return the text of the currently selected item in list_views[index]."""
        view = self.list_views[index]
        proxy_model = self.proxy_models[index]
        selected = view.selectionModel().selectedIndexes()
        if not selected:
            return ""
        return selected[0].data()

    def select_item_in_listview(self, model, i: int, text_to_select: str):
        if model is None:
            return
        source_model = model.sourceModel() if isinstance(model, QtCore.QSortFilterProxyModel) else model
        for row in range(source_model.rowCount()):
            index = source_model.index(row, 0)
            if source_model.data(index) == text_to_select:
                if isinstance(model, QtCore.QSortFilterProxyModel):
                    index = model.mapFromSource(index)
                sm = self.list_views[i].selectionModel()
                sm.blockSignals(True)
                self.list_views[i].setCurrentIndex(index)
                self.list_views[i].scrollTo(index)
                sm.blockSignals(False)
                return

    # ------------------------------------------------------------------
    # Token data helpers
    # ------------------------------------------------------------------

    def reset_next_tokens_data(self, depth: int):
        max_depth = len(self.token_wrap_list)
        if depth <= max_depth:
            for x in range(depth + 1, max_depth):
                self.data.pop(self.token_wrap_list[x], None)

    def gather_data(self, tokens=None, depth: int = 0):
        if tokens is None:
            tokens = {}
        if depth >= len(self.token_wrap_list):
            return tokens.copy()

        token      = self.token_wrap_list[depth]
        type_name  = "asset" if self.selector_type == SelectorType.asset else "shot"
        result     = self.proj.next_token_values(type_name, self.pattern, **tokens)

        if not result:
            self.reset_next_tokens_data(depth)
            return tokens.copy()

        token_name, values = result
        filtered_values = sorted([v for v in values if "." not in v])
        if not filtered_values:
            self.reset_next_tokens_data(depth)
            return tokens.copy()

        selection = filtered_values[0]
        if isinstance(self.default_keys, dict):
            if self.default_keys.get(token_name) in filtered_values:
                selection = self.default_keys[token_name]
        elif isinstance(self.default_keys, list):
            for dv in self.default_keys:
                if dv in filtered_values:
                    selection = dv
                    self.default_keys.remove(dv)
                    break

        self.data[token_name] = filtered_values
        new_tokens = tokens.copy()
        new_tokens[token_name] = selection

        if depth:
            self._cb[depth].tokens = tokens.copy()

        return self.gather_data(new_tokens, depth + 1)

    def add_possible_values_to_combo(
        self, token_name: str, values: list, color: str = "orange"
    ):
        """
        Add orange (possible, not-yet-existing) values to a named combobox.

        Args:
            token_name: Token to target (e.g. 'lod', 'phase').
            values:     Values to add if not already present.
            color:      Display colour (default: "orange").
        """
        try:
            index = self.token_wrap_list.index(token_name)
            self._cb[index].add_possible_values(values, color)
        except ValueError:
            print(
                f"Token '{token_name}' not found in token list: {self.token_wrap_list}"
            )

    @block_ui_update
    def apply_filter(self, index: int, text: str, *args):
        combo   = self._cb[index]
        current = combo.currentText()
        filtered = sorted(
            set(i for i in combo.all_items if text.lower() in i.lower())
        )
        if current not in filtered:
            filtered.insert(0, current)

        combo.clear()
        combo.addItems(filtered)
        combo.setCurrentText(current)

        if self.mode == Mode.expanded:
            self.proxy_models[index].setFilterFixedString(text)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        for i, key in enumerate(self.token_wrap_list):
            self.settings.setValue(key, self._cb[i].currentText())
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# Demo window — mirrors the __main__ block in the original wgt_shot_select.py
# ---------------------------------------------------------------------------

class _DemoWindow(QtWidgets.QMainWindow):
    """
    Demo window that shows shot + asset selectors side by side with a
    PublishAssetUI-like panel for testing the phase/lod orange-item logic.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Selector Demo — Standalone (mockup data)")
        self.setMinimumSize(1000, 600)

        central = QtWidgets.QWidget()
        root_layout = QtWidgets.QVBoxLayout(central)

        # ── Shot selector ────────────────────────────────────────────────
        root_layout.addWidget(QtWidgets.QLabel("<b>Shot Selector</b>"))
        self.shot_selector = PublishSelector(
            mode=Mode.compact,
            direction=Direction.vertical,
            label=True,
            selector_type=SelectorType.shot,
            default_keys={"episode": "ep001", "sequence": "sq010"},
        )
        root_layout.addWidget(self.shot_selector)

        root_layout.addSpacing(16)

        # ── Asset selector with orange department/lod panel ─────────────────
        root_layout.addWidget(QtWidgets.QLabel("<b>Asset Selector  (department + LOD with orange possible values)</b>"))

        asset_row = QtWidgets.QHBoxLayout()

        self.asset_selector = PublishSelector(
            mode=Mode.expanded,
            direction=Direction.vertical,
            label=True,
            selector_type=SelectorType.asset,
            limit=5,
            default_keys={"category": "animal", "name": "cat", "variation": "STD", "department": "cfx"},
        )
        asset_row.addWidget(self.asset_selector)

        # Populate orange department + lod for the current selection on startup
        self._populate_orange_options()
        self.asset_selector.selectionChanged.connect(self._on_asset_changed)

        root_layout.addLayout(asset_row)

        self.setCentralWidget(central)

    def _populate_orange_options(self):
        proj = _mock_project_module.get()
        sel  = self.asset_selector.get_current_selection()
        cat, name, var = sel.get("category"), sel.get("name"), sel.get("variation")
        if not all([cat, name, var]):
            return

        existing_depts  = _mock_project_module.list_pub_asset_departments(cat, name, var)
        possible_depts  = list(set(proj.get_valid_departments("asset")) - set(existing_depts))
        self.asset_selector.add_possible_values_to_combo("department", possible_depts, color="orange")

        active_dept = self.asset_selector._cb[
            self.asset_selector.token_wrap_list.index("department")
        ].currentText()
        existing_lods = _mock_project_module.list_pub_asset_lod(cat, name, var, active_dept)
        possible_lods = list(set(proj.get_valid_lods()) - set(existing_lods))
        self.asset_selector.add_possible_values_to_combo("lod", possible_lods, color="orange")

    def _on_asset_changed(self, selection):
        self._populate_orange_options()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    win = _DemoWindow()
    win.show()
    sys.exit(app.exec_() if hasattr(app, "exec_") else app.exec())

