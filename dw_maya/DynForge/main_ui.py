"""
main_ui.py - DynForge main window.

Layout
------
    +----------------------------------------------------------+
    | NamingPanel        prefix _ side _ index _ name          |
    +-------------------------+--------------------------------+
    | GuideListPanel          | QTabWidget                     |
    |  Name | Build | Status  |   Attributes   (GuideAttrEditor)|
    |  [+] [-]                |   Skinning    (placeholder)    |
    +-------------------------+--------------------------------+

main_ui owns the orchestration: [+] reads the naming pattern + the editor's
creation params and asks the registry for a new guide; the per-row Build button
applies the editor params then builds / rebuilds the guide.

Launch from inside Maya:
    from dw_maya.DynForge import main_ui
    main_ui.launch()
"""

from __future__ import annotations

import json
import traceback

from dw_maya.DynForge.forge_cmds.compat import QtCore, QtWidgets, Qt, qt_exec, wrapInstance
from dw_maya.DynForge.wgt_base import DynForgeMainWindow
from dw_maya.DynForge.wgt_naming_panel import NamingPanel
from dw_maya.DynForge.wgt_attr_editor import GuideAttrEditor
from dw_maya.DynForge.wgt_guide_list import GuideListPanel
from dw_maya.DynForge.wgt_load_dialog import LoadDialog
from dw_maya.DynForge import guide_registry
from dw_logger import get_logger

logger = get_logger()


class DynForgeUI(DynForgeMainWindow):
    """DynForge main window: name, list, edit and build guides."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("DynForge")
        self.setObjectName("DynForgeUI")
        self.resize(640, 520)

        self._settings = QtCore.QSettings("dw_open_tools", "DynForge")
        self._defaults = self._load_defaults()

        self._register_backends()
        self._build_ui()
        self._connect()

    # -- Setup ------------------------------------------------------------

    def _register_backends(self) -> None:
        """Importing the backends package self-registers every guide type."""
        try:
            from dw_maya.DynForge import backends  # noqa: F401  registers all backends
        except Exception:
            logger.error("DynForge: failed to import guide backends")
            traceback.print_exc()

    def _build_ui(self) -> None:
        self._build_menu()

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)

        self.naming_panel = NamingPanel(self.hub)
        layout.addWidget(self.naming_panel)

        splitter = QtWidgets.QSplitter()
        self.list_panel = GuideListPanel(self.hub)
        splitter.addWidget(self.list_panel)

        self.tabs = QtWidgets.QTabWidget()
        self.attr_editor = GuideAttrEditor(self.hub)
        self.attr_editor.apply_defaults(self._defaults)
        self.attr_editor.load_guide(None)   # placeholder until something is selected
        self.tabs.addTab(self.attr_editor, "Attributes")
        self.tabs.addTab(self._make_skinning_placeholder(), "Skinning")
        splitter.addWidget(self.tabs)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, stretch=1)

    def _build_menu(self) -> None:
        menu = self.menuBar().addMenu("System")
        act_save = menu.addAction("Save JSON...")
        act_load = menu.addAction("Load...")
        act_save.triggered.connect(self._on_save_json)
        act_load.triggered.connect(self._on_load)

    def _make_skinning_placeholder(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        page_layout = QtWidgets.QVBoxLayout(page)
        label = QtWidgets.QLabel("Skinning transfer - coming soon.")
        label.setAlignment(Qt.AlignCenter)
        page_layout.addWidget(label)
        page_layout.addStretch(1)
        return page

    def _connect(self) -> None:
        self.list_panel.add_requested.connect(self._on_add)
        self.list_panel.remove_requested.connect(self._on_remove)
        self.list_panel.build_requested.connect(self._on_build)
        self.list_panel.build_all_requested.connect(self._on_build_all)
        self.list_panel.load_requested.connect(self._on_load)
        self.list_panel.selection_changed.connect(self._on_selection_changed)
        self.attr_editor.params_edited.connect(self._on_params_edited)

    # -- Settings ---------------------------------------------------------

    def _load_defaults(self) -> dict:
        """Read the last-used build defaults from QSettings (with fallbacks)."""
        s = self._settings

        def as_int(key, fallback):
            try:
                return int(s.value(key, fallback))
            except (TypeError, ValueError):
                return fallback

        return {
            "type_name":  "chain_joint",
            "mode":       str(s.value("mode", "edge")),
            "n_joints":   as_int("n_joints", 10),
            "up_axis":    str(s.value("up_axis", "y")),
            "degree":     as_int("degree", 3),
            "flip":       False,   # per-fix correction, never persisted / default-on
            "n_locators": as_int("n_locators", 4),
            "point_type": str(s.value("point_type", "locator")),
            "cv_count":   as_int("cv_count", 6),
        }

    def _save_defaults(self) -> None:
        """Persist the current build defaults to QSettings (flip is intentionally not saved)."""
        for key in ("mode", "n_joints", "up_axis", "degree", "n_locators", "point_type", "cv_count"):
            self._settings.setValue(key, self._defaults[key])

    # -- Handlers ---------------------------------------------------------

    def _on_add(self) -> None:
        params = dict(self._defaults)
        params["name"] = self.naming_panel.compose_unique(self.list_panel.existing_names())

        backend_cls = guide_registry.get_backend(params["type_name"])
        if backend_cls is None:
            logger.error(f"DynForge: no backend registered for {params['type_name']!r}")
            return
        try:
            guide = backend_cls.create(**params)
        except Exception as e:
            logger.error(f"DynForge: guide creation failed: {e}")
            traceback.print_exc()
            QtWidgets.QMessageBox.warning(self, "DynForge", f"Create failed:\n{e}")
            return

        self.list_panel.add_guide(guide)   # selecting it shows the editor
        self.naming_panel.bump_index()

    def _on_params_edited(self,
                          guide,) -> None:
        """Remember the edited guide's settings as the default for the next one."""
        self._defaults.update({
            "mode":       getattr(guide, "mode", self._defaults["mode"]),
            "n_joints":   getattr(guide, "n_joints", self._defaults["n_joints"]),
            "up_axis":    getattr(guide, "up_axis", self._defaults["up_axis"]),
            "degree":     getattr(guide, "degree", self._defaults["degree"]),
            "n_locators": getattr(guide, "n_locators", self._defaults["n_locators"]),
            "point_type": getattr(guide, "point_type", self._defaults["point_type"]),
            "cv_count":   getattr(guide, "cv_count", self._defaults["cv_count"]),
        })
        # flip is deliberately left out of the persisted defaults.
        # Mode may have changed -> refresh the row badge.
        self.list_panel.refresh_guide(guide)

    def _on_build_all(self) -> None:
        """Save each curve's CV positions (preserving manual edits), then build."""
        for guide in self.list_panel.all_guides():
            try:
                if hasattr(guide, "save_curve_positions"):
                    guide.save_curve_positions()
                if guide.status is guide_registry.GuideStatus.BUILT:
                    guide.rebuild()
                else:
                    guide.build()
            except Exception as e:
                logger.warning(f"DynForge: (re-)build all skipped {guide.name!r}: {e}")
                continue
            self.list_panel.refresh_guide(guide)
            self.attr_editor.reload_if_current(guide)

    def _on_remove(self,
                   guide,) -> None:
        try:
            guide.destroy()
        except Exception as e:
            logger.warning(f"DynForge: destroy failed for {guide.name!r}: {e}")

    def _on_build(self,
                  guide,) -> None:
        # Editor edits are applied to the guide live, so the guide already holds
        # its current parameters (even when it is not the selected row).
        try:
            if guide.status is guide_registry.GuideStatus.BUILT:
                guide.rebuild()
            else:
                guide.build()
        except Exception as e:
            logger.error(f"DynForge: build failed for {guide.name!r}: {e}")
            traceback.print_exc()
            QtWidgets.QMessageBox.warning(self, "DynForge", f"Build failed:\n{e}")
        self.list_panel.refresh_guide(guide)
        self.attr_editor.reload_if_current(guide)

    def _on_selection_changed(self,
                              guide,) -> None:
        self.attr_editor.load_guide(guide)

    # -- Save / load / pick ----------------------------------------------

    def _populate(self,
                  guides: list,) -> None:
        """Replace the list rows with `guides` (UI only; scene untouched)."""
        self.list_panel.clear()
        for guide in guides:
            self.list_panel.add_guide(guide)

    def _confirm_replace(self) -> bool:
        """Ask before discarding the current rows, return True to proceed."""
        if not self.list_panel.all_guides():
            return True
        reply = QtWidgets.QMessageBox.question(
            self, "DynForge",
            "Replace the current guide list?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        return reply == QtWidgets.QMessageBox.Yes

    def _on_save_json(self) -> None:
        guides = self.list_panel.all_guides()
        if not guides:
            QtWidgets.QMessageBox.information(self, "DynForge", "No guides to save.")
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save DynForge system", "", "JSON files (*.json)")
        if not path:
            return
        data = {"version": 1, "guides": [g.to_dict() for g in guides]}
        try:
            with open(path, "w") as fh:
                json.dump(data, fh, indent=2)
        except OSError as e:
            logger.error(f"DynForge: save failed: {e}")
            QtWidgets.QMessageBox.warning(self, "DynForge", f"Save failed:\n{e}")
            return
        logger.info(f"DynForge: saved {len(guides)} guide(s) to {path}")

    def _on_load(self) -> None:
        """Open the Load dialog (file or Maya group) and populate from the choice."""
        groups = []
        try:
            from dw_maya.dw_rigging import dw_chain_guide
            groups = dw_chain_guide.detect_guide_groups()
        except Exception as e:
            logger.warning(f"DynForge: could not detect guide groups: {e}")

        dialog = LoadDialog(groups, parent=self)
        if qt_exec(dialog) != QtWidgets.QDialog.Accepted:
            return
        choice = dialog.selection()
        if choice is None:
            return
        source, value = choice
        if source == "file":
            self._load_from_file(value)
        else:
            self._load_from_maya(value)

    def _load_from_file(self,
                        path: str,) -> None:
        try:
            with open(path) as fh:
                data = json.load(fh)
        except (OSError, ValueError) as e:
            logger.error(f"DynForge: load failed: {e}")
            QtWidgets.QMessageBox.warning(self, "DynForge", f"Load failed:\n{e}")
            return
        if not self._confirm_replace():
            return
        group = self._unique_group_for(path)
        guides = []
        for entry in data.get("guides", []):
            guide = guide_registry.guide_from_dict(entry)
            if guide is not None:
                # Loaded version lands in its own group so it does not merge with
                # guides already in the scene (lets the artist compare versions).
                guide.group_name = group
                guides.append(guide)
        self._populate(guides)
        logger.info(f"DynForge: loaded {len(guides)} guide(s) from {path} into "
                    f"{group!r} (pending - use '(Re-)build all' to rebuild).")

    @staticmethod
    def _unique_group_for(path: str) -> str:
        """Build a unique guide-group name from the loaded file name."""
        import os
        stem = os.path.splitext(os.path.basename(path))[0] or "loaded"
        base = f"{stem}_GRP"
        try:
            from dw_maya.dw_rigging import dw_chain_guide
            return dw_chain_guide.unique_group_name(base)
        except Exception:
            return base

    def _load_from_maya(self,
                        group: str,) -> None:
        """Populate from the guides whose source curve lives under `group`."""
        guides = [g for g in guide_registry.discover_all()
                  if self._curve_in_scope(g, [group])]
        if not guides:
            QtWidgets.QMessageBox.information(
                self, "DynForge", f"No guide curves found under {group.split('|')[-1]!r}.")
            return
        if not self._confirm_replace():
            return
        self._populate(guides)
        logger.info(f"DynForge: loaded {len(guides)} guide(s) from the scene.")

    @staticmethod
    def _curve_in_scope(guide,
                        selected: list,) -> bool:
        """True if the guide's source curve is one of, or under, the selection."""
        curve = getattr(guide, "source_curve", None)
        if not curve:
            return False
        for node in selected:
            if curve == node or curve.startswith(f"{node}|"):
                return True
        return False

    def closeEvent(self, event):
        self._save_defaults()
        super().closeEvent(event)


# ============================================================================
# LAUNCH
# ============================================================================

_window = None   # module-level ref so the window is not garbage-collected


def _maya_main_window():
    """Return Maya's main window as a QWidget, or None outside Maya."""
    try:
        import maya.OpenMayaUI as omui
    except ImportError:
        return None
    ptr = omui.MQtUtil.mainWindow()
    if ptr is None:
        return None
    return wrapInstance(int(ptr), QtWidgets.QWidget)


def launch():
    """Create (or re-show) the DynForge window, parented to Maya."""
    global _window
    if _window is not None:
        try:
            _window.close()
            _window.deleteLater()
        except Exception:
            pass
        _window = None

    _window = DynForgeUI(parent=_maya_main_window())
    _window.show()
    return _window