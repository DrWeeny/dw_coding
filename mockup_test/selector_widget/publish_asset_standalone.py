"""
Standalone publish-asset dialog for offline development and debugging.
"""

# ---------------------------------------------------------------------------
# Qt import
# ---------------------------------------------------------------------------
try:
    from Qt import QtWidgets, QtCore
except ImportError:
    try:
        from PySide2 import QtWidgets, QtCore
    except ImportError:
        from PySide6 import QtWidgets, QtCore

import sys
import pathlib

# Make sure the repo root is importable
_HERE = pathlib.Path(__file__).parent
_ROOT = _HERE.parent
for _p in [str(_HERE), str(_ROOT)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ---------------------------------------------------------------------------
# Pipeline replacements
# ---------------------------------------------------------------------------
import standalone.mockup_data as _mock

# Namespaces that mirror the production import style
class _MockPubProject:
    """Thin namespace so we can write  pub.project.get()  below."""
    @staticmethod
    def get():
        return _mock.get()

class _pub:
    project = _MockPubProject

pub = _pub  # local alias

class _cfx_utils_files:
    """Mirrors the cfx_utils.files surface used in PublishAssetUI."""
    @staticmethod
    def list_pub_asset_departments(category, name, variation):
        return _mock.list_pub_asset_departments(category, name, variation)

    @staticmethod
    def list_pub_asset_lod(category, name, variation, department):
        return _mock.list_pub_asset_lod(category, name, variation, department)

class _cfx_utils:
    files = _cfx_utils_files

cfx_utils = _cfx_utils  # local alias

# ---------------------------------------------------------------------------
# Widget import
# ---------------------------------------------------------------------------
from standalone.wgt_shot_select_standalone import (
    PublishSelector,
    SelectorType,
    Mode,
)


# ---------------------------------------------------------------------------
# Simulated publish functions (print-only, no real I/O)
# ---------------------------------------------------------------------------

def _publish_sim_asset(category=None, name=None, variation=None, department=None, lod=None):
    """Simulated publish — prints what would be sent to the pipeline."""
    print(
        f"[MOCK] _publish_sim_asset called:\n"
        f"  category={category}  name={name}  variation={variation}\n"
        f"  department={department}  lod={lod}"
    )


def _publish_expanded_rig(category=None, name=None, variation=None, department=None, lod=None):
    """Simulated rend publish — prints what would be sent to the pipeline."""
    print(
        f"[MOCK] _publish_expanded_rig called:\n"
        f"  category={category}  name={name}  variation={variation}\n"
        f"  department={department}  lod={lod}"
    )


# ---------------------------------------------------------------------------
# PublishAssetUI — identical logic to the production version
# ---------------------------------------------------------------------------

class PublishAssetUI(QtWidgets.QDialog):
    """
    Dialog to select asset tokens and trigger a (mock) publish.

    This is a direct port of cfx_houdini.asset_publisher.PublishAssetUI with
    all pipeline calls replaced by mockup_data equivalents so it can run
    entirely offline.

    Attributes:
        _desired_dept: Last explicitly chosen department (survives asset changes).
        _desired_lod:  Last explicitly chosen LOD (survives asset changes).
        _previous_values: Category/name/variation snapshot to detect asset change.
        _is_updating:  Re-entrancy guard for _update_options.

    Example:
        dialog = PublishAssetUI()
        if dialog.exec_() == QtWidgets.QDialog.Accepted:
            print(dialog.get_selection())
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self._previous_values = {"category": None, "name": None, "variation": None}
        self._is_updating  = False
        self._desired_dept = "cfx"
        self._desired_lod  = "default"

        self.setWindowTitle("Publish Asset  [STANDALONE / MOCKUP]")
        self.setMinimumWidth(460)
        self.setMinimumHeight(320)

        self._setup_ui()

    # ------------------------------------------------------------------
    # Default values — in production these come from the Houdini scene;
    # here we just fall back to None so the combo starts at the first item.
    # ------------------------------------------------------------------

    def _get_default_values(self):
        """Return (category, name, variation, department, lod) defaults."""
        return None, None, None, "cfx", "default"

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        layout.addWidget(QtWidgets.QLabel("Select asset details for publishing:"))

        default_category, default_name, default_variation, default_dept, default_lod = (
            self._get_default_values()
        )

        default_keys = {}
        if default_category: default_keys["category"]   = default_category
        if default_name:     default_keys["name"]        = default_name
        if default_variation:default_keys["variation"]   = default_variation
        if default_dept:     default_keys["department"]  = default_dept
        if default_lod:      default_keys["lod"]         = default_lod

        self.selector = PublishSelector(
            mode=0,   # ultra_compact → comboboxes only, no listviews
            direction=1,  # vertical
            label=True,
            selector_type=SelectorType.asset,
            limit=5,  # category, name, variation, department, lod
            default_keys=default_keys,
            parent=self,
        )
        layout.addWidget(self.selector)

        self.selector.selectionChanged.connect(self._on_selection_changed)

        # Disconnect ALL slots from the LOD combobox then re-attach only a
        # thin slot that records user picks into _desired_lod.
        lod_index = self.selector.token_wrap_list.index("lod")
        lod_cb    = self.selector._cb[lod_index]
        try:
            lod_cb.currentIndexChanged.disconnect()
        except (RuntimeError, TypeError):
            pass
        lod_cb.currentIndexChanged.connect(self._on_lod_changed)

        # Initial population (deferred so the window is shown first)
        QtCore.QTimer.singleShot(100, self._update_options)

        # Buttons
        btn_layout = QtWidgets.QHBoxLayout()
        self.confirm_button = QtWidgets.QPushButton("Confirm")
        self.cancel_button  = QtWidgets.QPushButton("Cancel")
        btn_layout.addWidget(self.confirm_button)
        btn_layout.addWidget(self.cancel_button)
        layout.addLayout(btn_layout)

        self.confirm_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_lod_changed(self, index: int):
        """Capture user LOD pick without triggering any upstream rebuild."""
        if self._is_updating:
            return
        lod_index = self.selector.token_wrap_list.index("lod")
        lod_cb    = self.selector._cb[lod_index]
        chosen    = lod_cb.itemText(index)
        if chosen:
            self._desired_lod = chosen

    def _on_selection_changed(self, selection: dict):
        """Called when category / name / variation / department combo changes.

        The LOD combobox is disconnected from this path — it only updates
        _desired_lod through _on_lod_changed.

        Args:
            selection: dict from selectionChanged signal.
        """
        if self._is_updating:
            return

        incoming_asset = {
            "category":  selection.get("category"),
            "name":      selection.get("name"),
            "variation": selection.get("variation"),
        }
        asset_stable = (incoming_asset == self._previous_values)

        if asset_stable:
            snap_dept = selection.get("department")
            if snap_dept:
                self._desired_dept = snap_dept

        QtCore.QTimer.singleShot(0, lambda: self._update_options(selection))

    def _update_options(self, selection=None):
        """Repopulate the department and LOD combos with orange possible-values.

        Args:
            selection: Current selection dict; read from widget if None.
        """
        if self._is_updating:
            return

        if selection is None:
            selection = self.selector.get_current_selection()

        if not selection or not all(
            k in selection for k in ("category", "name", "variation")
        ):
            return

        self._is_updating = True

        dept_index = self.selector.token_wrap_list.index("department")
        lod_index  = self.selector.token_wrap_list.index("lod")

        for cb in self.selector._cb:
            cb.blockSignals(True)

        try:
            current_asset = {
                "category":  selection.get("category"),
                "name":      selection.get("name"),
                "variation": selection.get("variation"),
            }
            asset_changed = current_asset != self._previous_values

            proj = pub.project.get()

            # --- Department ---
            existing_depts  = cfx_utils.files.list_pub_asset_departments(
                category=selection["category"],
                name=selection["name"],
                variation=selection["variation"],
            )
            possible_depts = list(
                set(proj.get_valid_departments("asset")) - set(existing_depts)
            )
            self.selector.add_possible_values_to_combo("department", possible_depts, color="orange")

            if asset_changed:
                target_dept       = "cfx"
                self._desired_dept = "cfx"
                self._desired_lod  = "default"
            else:
                target_dept = self._desired_dept

            self.selector._cb[dept_index].setCurrentText(target_dept)
            actual_dept = self.selector._cb[dept_index].currentText()
            if actual_dept != target_dept:
                self._desired_dept = actual_dept

            # --- LOD ---
            existing_lods = cfx_utils.files.list_pub_asset_lod(
                category=selection["category"],
                name=selection["name"],
                variation=selection["variation"],
                department=actual_dept,
            )
            possible_lods = list(set(proj.get_valid_lods()) - set(existing_lods))
            self.selector.add_possible_values_to_combo("lod", possible_lods, color="orange")

            target_lod = self._desired_lod
            self.selector._cb[lod_index].setCurrentText(target_lod)
            actual_lod = self.selector._cb[lod_index].currentText()
            if actual_lod != target_lod:
                print(
                    f"[PublishAssetUI] WARNING: lod target '{target_lod}' "
                    f"not available, got '{actual_lod}'"
                )

            self._previous_values = current_asset.copy()

        except Exception as exc:
            import traceback
            print(f"[PublishAssetUI] _update_options ERROR: {exc}")
            traceback.print_exc()

        finally:
            self._is_updating = False
            for cb in self.selector._cb:
                cb.blockSignals(False)

    # ------------------------------------------------------------------
    # Result accessor
    # ------------------------------------------------------------------

    def get_selection(self) -> dict:
        """Return the current selector state as a dict."""
        return self.selector.get_current_selection()


# ---------------------------------------------------------------------------
# publish_asset — mirrors the production entry point
# ---------------------------------------------------------------------------

def publish_asset(parent=None):
    """Open the dialog and dispatch the appropriate (mock) publish call."""
    dialog = PublishAssetUI(parent)

    if dialog.exec_() == QtWidgets.QDialog.Accepted:
        selection = dialog.get_selection()

        category  = selection.get("category")
        name      = selection.get("name")
        variation = selection.get("variation")
        department = dialog._desired_dept or selection.get("department", "cfx")

        lod_index = dialog.selector.token_wrap_list.index("lod")
        lod       = dialog.selector._cb[lod_index].currentText() or dialog._desired_lod or "default"

        print(f"[publish_asset] Confirmed → cat={category} name={name} var={variation} dept={department} lod={lod}")

        if lod == "default":
            _publish_sim_asset(category=category, name=name, variation=variation,
                               department=department, lod=lod)
        elif lod == "rend":
            _publish_expanded_rig(category=category, name=name, variation=variation,
                                  department=department, lod=lod)
        else:
            # Non-standard LOD — show confirmation
            msg = (
                f"Non-standard LOD publish\n\n"
                f"Asset      : {category} / {name} / {variation}\n"
                f"Department : {department}\n"
                f"LOD        : {lod}\n\n"
                f"This will use _publish_sim_asset with lod='{lod}'.\n"
                f"Continue?"
            )
            result = QtWidgets.QMessageBox.warning(
                None, f"Confirm publish — LOD: {lod}", msg,
                QtWidgets.QMessageBox.Ok | QtWidgets.QMessageBox.Cancel,
            )
            if result == QtWidgets.QMessageBox.Ok:
                _publish_sim_asset(category=category, name=name, variation=variation,
                                   department=department, lod=lod)
            else:
                print(f"[publish_asset] Cancelled for lod='{lod}'")
    else:
        print("[publish_asset] Cancelled")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    publish_asset()
    sys.exit(0)

