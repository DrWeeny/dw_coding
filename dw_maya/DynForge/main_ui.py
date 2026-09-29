"""
main_ui.py - DynForge main window.

Layout
------
    +----------------------------------------------------------+
    | NamingPanel        prefix _ side _ index _ name          |
    +-------------------------+--------------------------------+
    | GuideListPanel          | QTabWidget                     |
    |  Name | Build | Status  |   Attributes (GuideAttrEditor) |
    |  [+] [-] Load (Re)build |   Skinning   (SkinPanel)       |
    |                         |   Install    (InstallPanel)    |
    |                         |   + tabs of the ForgeHost      |
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
import re
import traceback
from functools import partial

import maya.cmds as cmds

from dw_maya.DynForge.forge_cmds.compat import QtCore, QtWidgets, Qt, qt_exec, wrapInstance
from dw_maya.DynForge.wgt_base import DynForgeMainWindow, ForgeContext
from dw_maya.DynForge.wgt_naming_panel import NamingPanel
from dw_maya.DynForge.wgt_attr_editor import GuideAttrEditor
from dw_maya.DynForge.wgt_guide_list import GuideListPanel
from dw_maya.DynForge.wgt_load_dialog import LoadDialog
from dw_maya.DynForge.wgt_skin_panel import SkinPanel
from dw_maya.DynForge.wgt_install_panel import InstallPanel
from dw_maya.DynForge import forge_host
from dw_maya.DynForge.forge_cmds import skin_ops
from dw_maya.DynForge import guide_registry
from dw_logger import get_logger

logger = get_logger()

_VALID_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")   # a legal Maya node name


class DynForgeUI(DynForgeMainWindow):
    """DynForge main window: name, list, edit and build guides."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("DynForge")
        self.setObjectName("DynForgeUI")
        self.resize(860, 600)

        self._settings = QtCore.QSettings("dw_open_tools", "DynForge")
        self._defaults = self._load_defaults()

        self._register_backends()
        self._build_ui()
        self._connect()
        self._restore_from_scene()

    # -- Setup ------------------------------------------------------------

    def _register_backends(self) -> None:
        """Importing the backends package self-registers every guide type."""
        try:
            from dw_maya.DynForge import backends  # noqa: F401  registers all backends
        except Exception:
            logger.error("DynForge: failed to import guide backends")
            traceback.print_exc()

    def _restore_from_scene(self) -> None:
        """Fill the list with the guides whose recipe groups are in the scene."""
        guides = guide_registry.discover_all()
        for guide in guides:
            self.list_panel.add_guide(guide)
        if guides:
            logger.info(f"DynForge: restored {len(guides)} guide(s) from the scene.")
        self._changed()

    def _build_ui(self) -> None:
        self._build_menu()

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)

        self.naming_panel = NamingPanel(self.hub, defaults=forge_host.get_host().naming_defaults())
        layout.addWidget(self.naming_panel)

        splitter = QtWidgets.QSplitter()
        self.list_panel = GuideListPanel(self.hub)
        splitter.addWidget(self.list_panel)

        # What the tabs see of the window (Install + any studio tab of the host).
        self.context = ForgeContext(self.list_panel.all_guides, self.list_panel.selected_guide, self)

        self.tabs = QtWidgets.QTabWidget()
        self.attr_editor = GuideAttrEditor(self.hub)
        self.attr_editor.apply_defaults(self._defaults)
        self.attr_editor.load_guide(None)   # placeholder until something is selected
        self.tabs.addTab(self.attr_editor, "Attributes")
        self.skin_panel = SkinPanel(self.hub)
        self.skin_panel.set_peers_provider(self.guides_on_skin)
        self.skin_panel.load_guide(None)
        self.tabs.addTab(self.skin_panel, "Skinning")
        self.install_panel = InstallPanel(self.hub, self.context)
        self._add_host_options(self.install_panel.options_row)
        self.install_panel.with_skin_cb.setChecked(
            str(self._settings.value("install_with_skin", "true")).lower() in ("1", "true", "yes"))
        self.tabs.addTab(self.install_panel, "Install")
        self._add_host_tabs()
        splitter.addWidget(self.tabs)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, stretch=1)

    def _add_host_tabs(self) -> None:
        """Tabs a studio ForgeHost adds (e.g. a solver-setup tab); a broken one is skipped, not fatal."""
        try:
            extra = forge_host.get_host().extra_tabs(self.context) or []
        except Exception:
            logger.error("DynForge: the host's extra tabs failed to build")
            traceback.print_exc()
            return
        for title, widget in extra:
            self.tabs.addTab(widget, title)

    def _changed(self) -> None:
        """Tell the tabs something changed in the guides' scene state."""
        self.context.guides_changed.emit()

    def _on_tab_changed(self,
                        index: int,) -> None:
        # Skinning edits (donors, parent bone) change install readiness without a signal.
        if self.tabs.widget(index) is self.install_panel:
            self.install_panel.refresh()

    def _on_with_skin_toggled(self,
                              checked: bool,) -> None:
        self._settings.setValue("install_with_skin", bool(checked))

    def _add_host_options(self,
                          row: QtWidgets.QHBoxLayout,) -> None:
        """One field per ForgeHost install option (e.g. the target rig group), persisted."""
        host = forge_host.get_host()
        for name, default in host.options.items():
            key = f"host/{host.label}/{name}"
            value = str(self._settings.value(key, default))
            host.set_option(name, value)
            row.addWidget(QtWidgets.QLabel(name.replace("_", " ").capitalize()))
            field = QtWidgets.QLineEdit(value)
            field.setMaximumWidth(140)
            field.editingFinished.connect(partial(self._on_host_option_edited, name, key, field))
            row.addWidget(field)

    def _on_host_option_edited(self,
                               name:  str,
                               key:   str,
                               field: QtWidgets.QLineEdit,) -> None:
        value = field.text().strip()
        forge_host.get_host().set_option(name, value)
        self._settings.setValue(key, value)
        self.install_panel.refresh()   # the targets depend on the options

    def guides_on_skin(self,
                       skin: str,) -> list:
        """The listed guides registered on `skin` (the chains competing for it)."""
        return [g for g in self.list_panel.all_guides()
                if getattr(g, "skin_cluster", None) == skin]

    def _install(self,
                 guides:    list,
                 with_skin: bool,) -> None:
        """
        Install `guides`. With skin: one skinCluster at a time, restore its
        vanilla backup (taken on the first install), apply all its chains at
        once so shared donors are split, and place each chain. Without skin:
        only place the chains, the skin is left untouched. Guides that are not
        ready are listed, not installed.
        """
        ready = [g for g in guides if hasattr(g, "is_installable") and g.is_installable(with_skin=with_skin)]
        skipped = [g.name for g in guides if g not in ready]
        if not ready:
            hint = ("register a mesh and pick donor bone(s) (Analyze suggests one)" if with_skin
                    else "pick the parent bone (Analyze suggests one)")
            QtWidgets.QMessageBox.information(
                self, "DynForge", f"Nothing to install.\n\nBuild a chain, then on the Skinning tab {hint}.")
            return

        lines = []
        if with_skin:
            by_skin: dict = {}
            for guide in ready:
                by_skin.setdefault(guide.skin_cluster, []).append(guide)
            for skin, group in by_skin.items():
                # Chains of this skin already installed stay installed: they are
                # re-applied with the batch (install always restarts from vanilla).
                batch = group + [p for p in self.guides_on_skin(skin)
                                 if p not in group and getattr(p, "skin_installed", False)]
                try:
                    stats = skin_ops.install_skin(skin, batch)
                except Exception as e:
                    logger.error(f"DynForge: install on {skin!r} failed: {e}")
                    traceback.print_exc()
                    QtWidgets.QMessageBox.warning(self, "DynForge", f"Install on {skin} failed:\n{e}")
                    continue
                lines.append(f"{skin.split('|')[-1]}:")
                lines += [f"   {s['name']}: {s['verts']} vert(s), {s['contested']} contested" for s in stats]
        else:
            for guide in ready:
                try:
                    guide.install_pin()
                except Exception as e:
                    logger.error(f"DynForge: install of {guide.name!r} failed: {e}")
                    traceback.print_exc()
                    QtWidgets.QMessageBox.warning(self, "DynForge", f"Install of {guide.name} failed:\n{e}")
                    continue
                lines.append(f"   {guide.name}: placed in the rig (skin untouched)")

        for guide in self.list_panel.all_guides():
            self.skin_panel.reload_if_current(guide)
            self.list_panel.refresh_guide(guide)
        if skipped:
            lines += ["", "Not ready, skipped:"] + [f"   {name}" for name in skipped]
        if lines:
            QtWidgets.QMessageBox.information(self, "DynForge", "Installed\n\n" + "\n".join(lines))
        self._changed()
        self._offer_json_for_homeless(ready)

    def _uninstall(self,
                   guides: list,) -> None:
        """Revert the install of `guides` (weights + hierarchy), one undo step each."""
        targets = [g for g in guides if hasattr(g, "uninstall")
                   and (getattr(g, "installed", False) or getattr(g, "skin_installed", False))]
        if not targets:
            QtWidgets.QMessageBox.information(self, "DynForge", "Nothing installed in the selection.")
            return
        for guide in targets:
            peers = self.guides_on_skin(guide.skin_cluster) if guide.skin_cluster else []
            try:
                guide.uninstall(skin_peers=tuple(peers))
            except Exception as e:
                logger.error(f"DynForge: uninstall of {guide.name!r} failed: {e}")
                traceback.print_exc()
                QtWidgets.QMessageBox.warning(self, "DynForge", f"Uninstall of {guide.name} failed:\n{e}")
        for guide in self.list_panel.all_guides():
            self.list_panel.refresh_guide(guide)
            self.skin_panel.reload_if_current(guide)
            self.attr_editor.reload_if_current(guide)
        self._changed()

    def _cleanup(self,
                 guides: list,) -> None:
        """Tidy only: split preview, clip gizmos of `guides`, empty setup groups. Points / curves / recipes stay."""
        removed = []
        if cmds.objExists(skin_ops.PREVIEW_GRP):
            skin_ops.clear_preview()
            removed.append("split preview")
        gizmos = [g for g in guides if getattr(g, "gizmo", None)]
        for guide in gizmos:
            guide.delete_gizmo()
        if gizmos:
            removed.append(f"{len(gizmos)} clip gizmo(s)")
        empty = [s for s in forge_host.get_host().list_setups()
                 if cmds.objExists(s) and not cmds.listRelatives(s, children=True)]
        if empty:
            cmds.delete(empty)
            removed.append(f"{len(empty)} empty setup group(s)")
        for guide in guides:
            self.skin_panel.reload_if_current(guide)
        self._changed()
        QtWidgets.QMessageBox.information(
            self, "DynForge", "Cleaned: " + ", ".join(removed) if removed else "Nothing to clean.")

    def _offer_json_for_homeless(self,
                                 guides: list,) -> None:
        """
        When the host keeps setups in a studio home (e.g. a metadata container),
        guides that found none stay in the scene hierarchy - offer a JSON copy.
        """
        if not forge_host.get_host().has_setup_home:
            return
        homeless = [g for g in guides if not getattr(g, "setup_home", None)]
        if not homeless:
            return
        reply = QtWidgets.QMessageBox.question(
            self, "DynForge",
            "No setup home (metadata container) found for:\n   "
            + "\n   ".join(g.name for g in homeless)
            + "\n\nTheir setup stays in the scene hierarchy. Also save it to a JSON file?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        if reply == QtWidgets.QMessageBox.Yes:
            self._save_json(homeless)

    def _build_menu(self) -> None:
        menu = self.menuBar().addMenu("System")
        act_save = menu.addAction("Save JSON...")
        act_load = menu.addAction("Load...")
        act_save.triggered.connect(self._on_save_json)
        act_load.triggered.connect(self._on_load)

    def _connect(self) -> None:
        self.list_panel.add_requested.connect(self._on_add)
        self.list_panel.remove_requested.connect(self._on_remove)
        self.list_panel.build_requested.connect(self._on_build)
        self.list_panel.build_all_requested.connect(self._on_build_all)
        self.list_panel.load_requested.connect(self._on_load)
        self.list_panel.selection_changed.connect(self._on_selection_changed)
        self.list_panel.rename_requested.connect(self._on_rename)
        self.list_panel.pattern_requested.connect(self._on_apply_pattern)
        self.attr_editor.params_edited.connect(self._on_params_edited)
        self.list_panel.selection_changed.connect(self.context.selection_changed.emit)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.install_panel.with_skin_cb.toggled.connect(self._on_with_skin_toggled)
        self.install_panel.install_requested.connect(self._install)
        self.install_panel.uninstall_requested.connect(self._uninstall)
        self.install_panel.cleanup_requested.connect(self._cleanup)
        self.install_panel.save_json_requested.connect(self._save_json)

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
            "n_joints":   as_int("n_joints", 10),
            "up_axis":    str(s.value("up_axis", "y")),
            "degree":     as_int("degree", 3),
            "flip":       False,   # per-fix correction, never persisted / default-on
            "point_type": str(s.value("point_type", "locator")),
            "cv_count":   as_int("cv_count", 6),
            "exact_points": str(s.value("exact_points", "false")).lower() in ("1", "true", "yes"),
            "strip_handles": as_int("strip_handles", 3),
        }

    def _save_defaults(self) -> None:
        """Persist the current build defaults to QSettings (flip is intentionally not saved)."""
        for key in ("n_joints", "up_axis", "degree", "point_type", "cv_count", "exact_points", "strip_handles"):
            self._settings.setValue(key, self._defaults[key])

    # -- Handlers ---------------------------------------------------------

    def _on_add(self) -> None:
        params = dict(self._defaults)
        params["name"] = self.naming_panel.compose_unique(self.list_panel.existing_names())
        if not _VALID_NAME.match(params["name"]):
            QtWidgets.QMessageBox.warning(
                self, "DynForge",
                f"{params['name']!r} is not a valid name: letters, digits and underscores, "
                "not starting with a digit. Fix the naming fields above.")
            return

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
        self._changed()

    def _on_rename(self,
                   guide,
                   new_name: str,) -> None:
        """Rename a guide and its scene nodes; an invalid / taken name is refused."""
        others = [n for n in self.list_panel.existing_names() if n != guide.name]
        error = None
        if not hasattr(guide, "rename"):
            error = f"{guide.label} guides cannot be renamed."
        elif not _VALID_NAME.match(new_name):
            error = (f"{new_name!r} is not a valid name: letters, digits and underscores, "
                     "not starting with a digit.")
        elif new_name in others:
            error = f"A guide named {new_name!r} already exists."
        if error is None:
            try:
                guide.rename(new_name)
            except Exception as e:
                logger.error(f"DynForge: rename of {guide.name!r} failed: {e}")
                traceback.print_exc()
                error = f"Rename failed:\n{e}"
        if error is not None:
            QtWidgets.QMessageBox.warning(self, "DynForge", error)
        # Refresh either way: shows the new name, or puts the old one back.
        self.list_panel.refresh_guide(guide)
        self.attr_editor.reload_if_current(guide)
        self.skin_panel.reload_if_current(guide)
        self._changed()

    def _on_apply_pattern(self,
                          guide,) -> None:
        """Rename a guide from the naming panel fields (prefix _ side _ index _ name)."""
        others = [n for n in self.list_panel.existing_names() if n != guide.name]
        self._on_rename(guide, self.naming_panel.compose_unique(others))

    def _on_params_edited(self,
                          guide,) -> None:
        """Remember the edited guide's settings as the default for the next one."""
        self._defaults.update({
            "n_joints":   getattr(guide, "n_joints", self._defaults["n_joints"]),
            "up_axis":    getattr(guide, "up_axis", self._defaults["up_axis"]),
            "degree":     getattr(guide, "degree", self._defaults["degree"]),
            "point_type": getattr(guide, "point_type", self._defaults["point_type"]),
            "cv_count":   getattr(guide, "cv_count", self._defaults["cv_count"]),
            "exact_points": getattr(guide, "exact_points", self._defaults["exact_points"]),
            "strip_handles": getattr(guide, "strip_handles", self._defaults["strip_handles"]),
        })
        # flip is deliberately left out of the persisted defaults.
        if hasattr(guide, "store_recipe"):
            guide.store_recipe()
        # Point type / exact may have changed -> refresh the row badge; a point
        # placed on a skinned mesh may have pre-registered its skinCluster.
        self.list_panel.refresh_guide(guide)
        self.skin_panel.refresh_if_current(guide)

    def _uninstall_quietly(self,
                           guide,) -> None:
        """Uninstall `guide` (weights + hierarchy) before an action that rebuilds / deletes its joints."""
        peers = self.guides_on_skin(guide.skin_cluster) if getattr(guide, "skin_cluster", None) else []
        guide.uninstall(skin_peers=tuple(peers))
        for peer in peers:
            self.list_panel.refresh_guide(peer)

    def _is_installed(self,
                      guide,) -> bool:
        return bool(getattr(guide, "installed", False) or getattr(guide, "skin_installed", False))

    def _on_build_all(self) -> None:
        """Save each curve's CV positions (preserving manual edits), then build. Installed guides are skipped."""
        skipped = []
        for guide in self.list_panel.all_guides():
            if self._is_installed(guide):
                skipped.append(guide.name)
                continue
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
        self._changed()
        if skipped:
            QtWidgets.QMessageBox.information(
                self, "DynForge",
                "Installed guides were not rebuilt (uninstall them first):\n   " + "\n   ".join(skipped))

    def _on_remove(self,
                   guide,) -> None:
        """Delete a guide from the scene (points, curve, chain, gizmo) and its row."""
        installed = self._is_installed(guide)
        extra = "\n\nIt is installed: it is uninstalled first (weights + rig)." if installed else ""
        reply = QtWidgets.QMessageBox.question(
            self, "DynForge",
            f"Delete guide {guide.name!r} and its scene nodes (points, curve, chain)?{extra}",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return
        try:
            if installed and hasattr(guide, "uninstall"):
                self._uninstall_quietly(guide)
            if hasattr(guide, "delete"):
                guide.delete()
            else:
                guide.destroy()
        except Exception as e:
            logger.warning(f"DynForge: delete failed for {guide.name!r}: {e}")
        self.list_panel.remove_guide(guide)
        self._changed()

    def _on_build(self,
                  guide,) -> None:
        # Editor edits are applied to the guide live, so the guide already holds
        # its current parameters (even when it is not the selected row).
        if self._is_installed(guide):
            reply = QtWidgets.QMessageBox.question(
                self, "DynForge",
                f"{guide.name} is installed. Uninstall it (weights + rig) and rebuild?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
            if reply != QtWidgets.QMessageBox.Yes:
                return
        try:
            if self._is_installed(guide) and hasattr(guide, "uninstall"):
                self._uninstall_quietly(guide)
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
        self._changed()

    def _on_selection_changed(self,
                              guide,) -> None:
        self.attr_editor.load_guide(guide)
        self.skin_panel.load_guide(guide)

    # -- Save / load / pick ----------------------------------------------

    def _populate(self,
                  guides: list,) -> None:
        """Replace the list rows with `guides` (UI only; scene untouched)."""
        self.list_panel.clear()
        for guide in guides:
            self.list_panel.add_guide(guide)
        self._changed()

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
        self._save_json(self.list_panel.all_guides())

    def _save_json(self,
                   guides: list,
                   stem:   str = "",) -> None:
        if not guides:
            QtWidgets.QMessageBox.information(self, "DynForge", "No guides to save.")
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, f"Save DynForge system{' - ' + stem if stem else ''}",
            f"{stem}.json" if stem else "", "JSON files (*.json)")
        if not path:
            return
        data = {"format": "dw_forge_setup", "version": 2, "guides": [g.to_dict() for g in guides]}
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
            groups = forge_host.get_host().list_setups()
        except Exception as e:
            logger.warning(f"DynForge: could not list the guide setups: {e}")

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
                # Loaded version lands in its own setup so it does not merge with
                # guides already in the scene (lets the artist compare versions).
                guide.setup = group
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
                        setup: str,) -> None:
        """Populate from the guides stored in the setup group `setup`."""
        guides = [g for g in guide_registry.discover_all()
                  if getattr(g, "setup", None) == setup]
        if not guides:
            QtWidgets.QMessageBox.information(
                self, "DynForge", f"No guides found in {setup.split('|')[-1]!r}.")
            return
        if not self._confirm_replace():
            return
        self._populate(guides)
        logger.info(f"DynForge: loaded {len(guides)} guide(s) from the scene.")

    def closeEvent(self, event):
        self._save_defaults()
        for guide in self.list_panel.all_guides():
            try:
                if hasattr(guide, "store_recipe"):
                    guide.store_recipe()
            except Exception as e:
                logger.warning(f"DynForge: could not store the recipe of {guide.name!r}: {e}")
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