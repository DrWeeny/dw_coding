"""
main_ui.py - DemBones main window.

Layout
------
    +-----------------------------------------------+
    | SourcePanel   (target mesh, abc, range, rig)  |
    +-----------------------+-----------------------+
    | ParamsPanel           | Solve + log           |
    +-----------------------+-----------------------+
    | GenerationsPanel  (fbx + sidecar list)        |
    +-----------------------------------------------+

This is a small tool: the panels expose plain getters/signals and main_ui wires
them directly (no DataHub). main_ui owns the solve orchestration: export the
rest FBX, build the exe args, run DemBones via a non-blocking QProcess, then
drop an fbx + sidecar json the generations list picks up.

Launch from inside Maya:
    from dw_maya.DemBones import main_ui
    main_ui.launch()
"""

from __future__ import annotations

import os

from dw_maya.DemBones.compat import QtCore, QtGui, QtWidgets, wrapInstance, QAction, qt_exec
from dw_maya.DemBones.wgt_source import SourcePanel
from dw_maya.DemBones.wgt_params import ParamsPanel
from dw_maya.DemBones.wgt_generations import GenerationsPanel
from dw_maya.DemBones import wgt_bind_skin
from dw_maya.DemBones import wgt_transfer
from dw_maya.DemBones import wgt_bones_to_asset
from dw_maya.DemBones import dem_cmds
from dw_logger import get_logger

logger = get_logger()

_window = None


def _solve_mode(params: dict, use_rig: bool) -> str:
    """Label the solve for the generation sidecar.

    The two half-solves are mutually exclusive mode switches, so they are read
    off the params rather than tracked separately: ``nWeightsIters == 0`` keeps
    the supplied weights and solves the joint animation only, ``nTransIters ==
    0`` keeps the supplied transforms and solves the weights only.
    """
    if params.get("nWeightsIters") == 0:
        return "transforms-only"
    if params.get("nTransIters") == 0:
        return "weights-only"
    return "use-rig" if use_rig else "full"


class DemBonesUI(QtWidgets.QMainWindow):
    """DemBones main window: configure, solve, and manage generations."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("DemBones")
        self.setObjectName("DemBonesUI")
        self.resize(680, 640)

        self._out_dir = dem_cmds.default_output_dir()
        self._runner = dem_cmds.SolveRunner(self)
        self._log_buffer = []
        self._pending = None   # metadata for the in-flight solve
        self._dialogs = {}   # kept alive: Qt would collect them otherwise

        self._build_ui()
        self._connect()

    # -- Setup ------------------------------------------------------------

    def _build_ui(self) -> None:
        self._build_menu()

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)

        # Top: source (left) + params (right).
        top = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self.source_panel = SourcePanel()
        self.params_panel = ParamsPanel()
        top.addWidget(self.source_panel)
        top.addWidget(self.params_panel)
        top.setStretchFactor(0, 1)
        top.setStretchFactor(1, 0)
        layout.addWidget(top)

        # Solve row: buttons, busy bar, rmse, log toggle.
        solve_row = QtWidgets.QHBoxLayout()
        self.solve_btn = QtWidgets.QPushButton("Solve")
        self.cancel_btn = QtWidgets.QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        # A self-driven marquee: a determinate bar whose value loops left->right
        # on a timer. We avoid Qt's native indeterminate mode (setRange(0, 0))
        # because Maya's stylesheet can render it as a static block - which looks
        # frozen. This always animates, so it clearly reads as "still working".
        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setVisible(False)
        self._busy_timer = QtCore.QTimer(self)
        self._busy_timer.setInterval(30)
        self._busy_timer.timeout.connect(self._tick_busy)
        self.rmse_label = QtWidgets.QLabel("rmse: --")
        self.show_log_chk = QtWidgets.QCheckBox("show log")
        self.show_log_chk.setToolTip(
            "Show the DemBones stdout/stderr log. When off, a busy bar is shown "
            "while solving instead.")
        solve_row.addWidget(self.solve_btn)
        solve_row.addWidget(self.cancel_btn)
        solve_row.addWidget(self.progress, 1)
        solve_row.addWidget(self.rmse_label)
        solve_row.addWidget(self.show_log_chk)
        layout.addLayout(solve_row)

        self.log_view = QtWidgets.QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(120)
        self.log_view.setVisible(False)
        layout.addWidget(self.log_view, 1)

        self.generations_panel = GenerationsPanel()
        self.generations_panel.set_output_dir(self._out_dir)
        layout.addWidget(self.generations_panel, 1)

        # Output dir line at the bottom.
        out_row = QtWidgets.QHBoxLayout()
        out_row.addWidget(QtWidgets.QLabel("Output"))
        self.out_field = QtWidgets.QLineEdit(self._out_dir)
        self.out_field.setReadOnly(True)
        out_row.addWidget(self.out_field, 1)
        self.open_dir_btn = QtWidgets.QPushButton("Open")
        self.open_dir_btn.setToolTip("Open the output folder in the file browser.")
        out_row.addWidget(self.open_dir_btn)
        layout.addLayout(out_row)

    def _build_menu(self) -> None:
        """Tools menu: locate the executable, copy a skin mesh to mesh."""
        menu = self.menuBar().addMenu("Tools")
        locate_action = QAction("Locate DemBones executable...", self)
        locate_action.setToolTip(
            "Point the tool at a DemBones[.exe] binary; the choice is "
            "remembered across Maya sessions.")
        locate_action.triggered.connect(self._on_locate_exe)
        menu.addAction(locate_action)

        menu.addSeparator()
        bind_action = QAction("Bind skin (prepare rest mesh)...", self)
        bind_action.setToolTip(
            "Bind the rest mesh so every joint takes part in the solve, and "
            "add the non-deforming ones (the root) at weight 0.")
        bind_action.triggered.connect(self._on_bind_skin)
        menu.addAction(bind_action)

        transfer_action = QAction("Transfer to rig (skin / animation)...", self)
        transfer_action.setToolTip(
            "Hand a solved generation back: copy its skinning onto another "
            "mesh, and its animation onto the rig's controls or joints.")
        transfer_action.triggered.connect(self._on_transfer)
        menu.addAction(transfer_action)

        to_asset_action = QAction("Solve -> Asset (joints in asset space)...",
                                  self)
        to_asset_action.setToolTip(
            "The return leg: rebuild the solved joints in ASSET space, bind "
            "the asset mesh to them and carry the animation across.\n"
            "Reports which correspondence the two meshes support (rigid / "
            "topology / uv) instead of asking.")
        to_asset_action.triggered.connect(self._on_bones_to_asset)
        menu.addAction(to_asset_action)

    def _on_bones_to_asset(self) -> None:
        """Open the Solve -> Asset dialog (kept alive on the window)."""
        self._dialogs["to_asset"] = wgt_bones_to_asset.launch(parent=self)

    def _on_bind_skin(self) -> None:
        """Open the bind-skin dialog (kept alive on the window)."""
        self._dialogs["bind"] = wgt_bind_skin.launch(parent=self)

    def _on_transfer(self) -> None:
        """Open the transfer dialog (kept alive on the window)."""
        self._dialogs["transfer"] = wgt_transfer.launch(parent=self)

    def _on_locate_exe(self) -> bool:
        """Open a file picker and persist the chosen DemBones binary.

        Returns:
            True if a valid executable was selected and saved.
        """
        if os.name == "nt":
            filt = "DemBones (DemBones.exe);;Executables (*.exe);;All files (*)"
        else:
            filt = "DemBones (DemBones);;All files (*)"
        start_dir = os.path.dirname(dem_cmds.get_exe_path() or "") or os.path.expanduser("~")
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Locate DemBones executable", start_dir, filt)
        if not path:
            return False
        if not os.path.isfile(path):
            QtWidgets.QMessageBox.warning(
                self, "DemBones", f"Not a file:\n{path}")
            return False
        dem_cmds.set_saved_exe(path)
        logger.info(f"DemBones exe set to: {path}")
        return True

    def _connect(self) -> None:
        self.solve_btn.clicked.connect(self._on_solve)
        self.cancel_btn.clicked.connect(self._runner.cancel)
        self.show_log_chk.toggled.connect(self._update_busy_display)
        self.open_dir_btn.clicked.connect(self._on_open_dir)
        self._runner.log.connect(self._on_log)
        self._runner.finished.connect(self._on_solve_finished)
        # Cross-widget wiring (plain signals, no hub).
        self.source_panel.use_rig_changed.connect(self.params_panel.set_use_rig)
        self.source_panel.anim_only_changed.connect(
            self.params_panel.set_anim_only)
        self.generations_panel.restore_requested.connect(self._on_restore_params)

    def _on_restore_params(self, params: dict) -> None:
        """Load a generation's params, syncing the anim-only mode with them.

        The mode is a source-panel checkbox rather than a param, so it is
        inferred from the restored ``nWeightsIters`` - otherwise restoring a
        transforms-only generation would leave the mode off and the params
        panel would let the zeros be edited away.
        """
        self.source_panel.set_anim_only(params.get("nWeightsIters") == 0)
        self.params_panel.set_params(params)

    # -- Solve ------------------------------------------------------------

    def _on_solve(self) -> None:
        if self._runner.is_running():
            return

        target = self.source_panel.target_mesh()
        abc_path = self.source_panel.abc_path()
        start, end = self.source_panel.frame_range()
        use_rig = self.source_panel.use_rig()
        anim_only = self.source_panel.anim_only()

        if not target or not abc_path:
            QtWidgets.QMessageBox.information(
                self, "DemBones", "Pick a target mesh and an Alembic cache first.")
            return
        if not self.source_panel.topo_valid():
            QtWidgets.QMessageBox.warning(
                self, "DemBones",
                "Target mesh vertex count does not match the Alembic. The solve "
                "would be garbage - fix the topology first.")
            return
        if not self._check_alembic_topology(target, abc_path):
            return
        if use_rig and not dem_cmds.find_skin_cluster(target):
            from maya import cmds
            if anim_only:
                # Anim-only keeps the weights it is given; bare joints have none.
                QtWidgets.QMessageBox.warning(
                    self, "DemBones",
                    "Animation only needs the weights to keep, but no "
                    "skinCluster was found on the target mesh.")
                return
            if not (cmds.ls(selection=True, type="joint") or []):
                QtWidgets.QMessageBox.warning(
                    self, "DemBones",
                    "Use-rig is on but no skinCluster was found and no joints "
                    "are selected.")
                return

        exe = dem_cmds.get_exe_path()
        if not exe:
            box = QtWidgets.QMessageBox(self)
            box.setIcon(QtWidgets.QMessageBox.Warning)
            box.setWindowTitle("DemBones")
            box.setText("DemBones executable not found.")
            box.setInformativeText(
                "Locate it now, or provide it via the DEMBONES_EXE env var, "
                "the system PATH, or DemBones/bin/<OS>/.\n\n"
                f"Download: {dem_cmds.DEMBONES_DOWNLOAD_URL}")
            locate = box.addButton("Locate...", QtWidgets.QMessageBox.AcceptRole)
            box.addButton(QtWidgets.QMessageBox.Cancel)
            qt_exec(box)
            if box.clickedButton() is not locate or not self._on_locate_exe():
                return
            exe = dem_cmds.get_exe_path()
            if not exe:
                return

        params = self.params_panel.get_params()
        index = dem_cmds.next_generation_index(self._out_dir)
        abc_stem = os.path.splitext(os.path.basename(abc_path))[0]
        base = f"{index:03d}_{abc_stem}_b{params['nBones']}_{start}-{end}"
        # Forward slashes throughout: os.path.join would mix separators into a
        # workspace root that already uses '/', and these paths get written to
        # a json a pipeline has to read.
        init_fbx = f"{self._out_dir}/{base}_rest.fbx".replace("\\", "/")
        out_fbx = f"{self._out_dir}/{base}.fbx".replace("\\", "/")

        # Export the rest FBX (mesh-only or mesh+rig).
        try:
            from maya import cmds
            joints = cmds.ls(selection=True, type="joint") or None
            dem_cmds.export_target_fbx(target, init_fbx, use_rig, joints=joints)
        except Exception as e:
            logger.error(f"Rest FBX export failed: {e}")
            QtWidgets.QMessageBox.critical(self, "DemBones", f"Export failed:\n{e}")
            return

        args = dem_cmds.build_args(abc_path, init_fbx, out_fbx, params, use_rig)
        self._pending = {
            "index": index,
            "name": base,
            "fbx": out_fbx,
            "params": params,
            "range": [start, end],
            "mode": _solve_mode(params, use_rig),
        }
        self._log_buffer = []
        self.log_view.clear()
        self.rmse_label.setText("rmse: solving...")
        self.solve_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self._runner.start(exe, args)
        self._update_busy_display()

    def _check_alembic_topology(self, target: str, abc_path: str) -> bool:
        """Compare the rest mesh against the .abc file itself before solving.

        The panel's green/red check compares two meshes in the scene, which
        both lie when the cached mesh was edited after the cache was written.
        This reads the file (imported into a throwaway namespace and deleted
        again) so the mismatch is caught here rather than as an exit code 1.

        Returns:
            True to go ahead with the solve.
        """
        counts = dem_cmds.alembic_vertex_counts(abc_path)
        if not counts:
            # Unreadable or no mesh inside: not proof of a mismatch, let the
            # exe have its say - its error message is surfaced now anyway.
            return True

        target_n = dem_cmds.mesh_vertex_count(target)
        if target_n in counts:
            return True

        found = ", ".join(str(n) for n in counts)
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Warning)
        box.setWindowTitle("DemBones")
        box.setText("The rest mesh does not match the Alembic file.")
        box.setInformativeText(
            f"The rest mesh has {target_n} vertices; the cache on disk holds "
            f"{found}.\n\n"
            f"DemBones matches the two vertex by vertex and will refuse the "
            f"pair. This usually means points were edited after the cache was "
            f"written - the fix is to re-cache the Alembic from the mesh you "
            f"are solving.\n\n"
            f"Note the panel's own check compares the rest mesh to the "
            f"abc-driven mesh in the scene, which agrees with it here; only "
            f"the file disagrees.")
        box.addButton("Solve anyway", QtWidgets.QMessageBox.DestructiveRole)
        cancel = box.addButton(QtWidgets.QMessageBox.Cancel)
        box.setDefaultButton(cancel)
        qt_exec(box)
        return box.clickedButton() is not cancel

    def _update_busy_display(self) -> None:
        """Log replaces the busy bar: show the log when asked, else a busy bar
        while a solve is running."""
        running = self._runner.is_running()
        show_log = self.show_log_chk.isChecked()
        self.log_view.setVisible(show_log)
        busy = running and not show_log
        self.progress.setVisible(busy)
        if busy:
            if not self._busy_timer.isActive():
                self._busy_timer.start()
        else:
            self._busy_timer.stop()
            self.progress.setValue(0)

    def _tick_busy(self) -> None:
        """Loop the marquee value left->right; reset at the end."""
        value = self.progress.value() + 3
        self.progress.setValue(0 if value > self.progress.maximum() else value)

    def _on_open_dir(self) -> None:
        QtGui.QDesktopServices.openUrl(
            QtCore.QUrl.fromLocalFile(self._out_dir))

    def _on_log(self, line: str) -> None:
        self._log_buffer.append(line)
        self.log_view.appendPlainText(line)

    def _on_solve_finished(self, code: int) -> None:
        self.solve_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self._update_busy_display()

        if code != 0 or self._pending is None:
            self.rmse_label.setText("rmse: failed")
            self._report_failure(code)
            return

        rmse = dem_cmds.parse_rmse("\n".join(self._log_buffer))
        self._pending["rmse"] = rmse
        self.rmse_label.setText(
            f"rmse: {rmse:.4f}" if rmse is not None else "rmse: (n/a)")

        if os.path.isfile(self._pending["fbx"]):
            dem_cmds.write_sidecar(self._pending["fbx"], self._pending)
            dem_cmds.write_log(self._pending["fbx"], "\n".join(self._log_buffer))
            self.generations_panel.refresh()
        else:
            logger.warning("Solve finished but no output FBX was produced.")
        self._pending = None

    def _report_failure(self, code: int) -> None:
        """Surface why a solve failed instead of leaving it in the log view.

        The exe explains itself on stdout/stderr, which the runner already
        captures - but the log view is hidden by default, so a failure used to
        show up as a bare exit code. The output is written to a .log next to the
        would-be generation, echoed to the script editor, and the tail is put in
        front of the artist with the log view forced open.
        """
        log_text = "\n".join(self._log_buffer)
        logger.warning(f"DemBones solve exited with code {code}")
        if log_text:
            logger.warning(f"DemBones output:\n{log_text}")

        written = None
        if self._pending:
            written = dem_cmds.write_log(self._pending["fbx"], log_text)

        # Show the log rather than the busy bar - the answer is in there.
        if not self.show_log_chk.isChecked():
            self.show_log_chk.setChecked(True)

        if code == -1:
            detail = ("The DemBones executable never started. Check the path "
                      "under Tools > Locate DemBones executable.")
        else:
            detail = self._log_tail(log_text) or (
                "The executable produced no output at all.")

        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Critical)
        box.setWindowTitle("DemBones")
        box.setText(f"The solve failed (exit code {code}).")
        box.setInformativeText(detail)
        if written:
            box.setDetailedText(f"Full log written to:\n{written}\n\n{log_text}")
        elif log_text:
            box.setDetailedText(log_text)
        qt_exec(box)
        self._pending = None

    @staticmethod
    def _log_tail(log_text: str, lines: int = 12) -> str:
        """Last non-empty lines of the log - where the reason usually is."""
        kept = [line for line in log_text.splitlines() if line.strip()]
        return "\n".join(kept[-lines:])


# ---------------------------------------------------------------------------
# Launch
# ---------------------------------------------------------------------------

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
    """Create (or re-show) the DemBones window, parented to Maya."""
    global _window
    if _window is not None:
        try:
            _window.close()
            _window.deleteLater()
        except Exception:
            pass
        _window = None

    _window = DemBonesUI(parent=_maya_main_window())
    _window.show()
    return _window