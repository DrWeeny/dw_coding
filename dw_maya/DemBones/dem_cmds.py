"""
dem_cmds.py - DemBones tool commands: scene discovery, validation, FBX export,
exe argument building, generation (fbx + sidecar json) I/O, and a QProcess-based
solve runner.

This module holds every non-UI operation so the widgets stay thin. Maya calls
live here; the exe call is wrapped in :class:`SolveRunner` (QProcess) so the UI
never blocks during a solve.

Layout on disk
--------------
    <output_dir>/
        curtain_b100_1001-1052.fbx
        curtain_b100_1001-1052.json   <- sidecar: params + range + rmse

Author:
    DrWeeny
"""

from __future__ import annotations

import os
import re
import sys
import json
import glob
import tempfile
from typing import Dict, List, Optional, Tuple

from maya import cmds, mel

from dw_maya.DemBones.compat import QtCore
from dw_logger import get_logger

logger = get_logger()


# ============================================================================
# EXE RESOLUTION
# ============================================================================

def get_exe_path() -> Optional[str]:
    """Resolve the bundled DemBones executable for the current platform.

    Looks under ``<package>/bin/<OS>/DemBones[.exe]``.

    Returns:
        str path to the executable, or ``None`` if it isn't bundled.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    if sys.platform.startswith("win"):
        candidate = os.path.join(here, "bin", "Windows", "DemBones.exe")
    elif sys.platform.startswith("linux"):
        candidate = os.path.join(here, "bin", "Linux", "DemBones")
    else:
        candidate = os.path.join(here, "bin", "macOS", "DemBones")

    if os.path.isfile(candidate):
        return candidate
    logger.warning(f"DemBones exe not found at expected path: {candidate}")
    return None


# ============================================================================
# SCENE DISCOVERY (Alembic + rig from the target mesh history)
# ============================================================================

def find_alembic_node(mesh: str) -> Optional[str]:
    """Find the AlembicNode driving ``mesh`` by walking its history.

    Args:
        mesh: Mesh transform or shape name.

    Returns:
        The AlembicNode name, or ``None`` if the mesh isn't abc-driven.
    """
    try:
        history = cmds.listHistory(mesh) or []
    except Exception as e:
        logger.warning(f"listHistory failed on '{mesh}': {e}")
        return None
    abc_nodes = cmds.ls(history, type="AlembicNode") or []
    return abc_nodes[0] if abc_nodes else None


def alembic_file_path(abc_node: str) -> Optional[str]:
    """Return the .abc file path stored on an AlembicNode."""
    try:
        return cmds.getAttr(f"{abc_node}.abc_File")
    except Exception as e:
        logger.warning(f"Could not read abc_File on '{abc_node}': {e}")
        return None


def alembic_frame_range(abc_node: str) -> Optional[Tuple[int, int]]:
    """Return (start, end) frames stored on an AlembicNode, if available."""
    try:
        start = cmds.getAttr(f"{abc_node}.startFrame")
        end = cmds.getAttr(f"{abc_node}.endFrame")
        return int(round(start)), int(round(end))
    except Exception:
        return None


def find_skin_cluster(mesh: str) -> Optional[str]:
    """Find the skinCluster in the history of ``mesh`` (None if unskinned)."""
    try:
        history = cmds.listHistory(mesh) or []
    except Exception as e:
        logger.warning(f"listHistory failed on '{mesh}': {e}")
        return None
    skins = cmds.ls(history, type="skinCluster") or []
    return skins[0] if skins else None


def skin_influences(skin_cluster: str) -> List[str]:
    """Return the influence joints of a skinCluster, in influence order."""
    try:
        return cmds.skinCluster(skin_cluster, query=True, influence=True) or []
    except Exception as e:
        logger.warning(f"Could not query influences on '{skin_cluster}': {e}")
        return []


def find_joints_from_mesh(mesh: str) -> List[str]:
    """Best-effort joint discovery: influences if skinned, else None.

    For the sparse / external-bone case (joints present but no skinCluster yet)
    the joints can't be derived from the mesh; the caller falls back to the
    current selection.
    """
    skin = find_skin_cluster(mesh)
    if skin:
        return skin_influences(skin)
    return []


# ============================================================================
# TOPOLOGY VALIDATION
# ============================================================================

def mesh_vertex_count(mesh: str) -> Optional[int]:
    """Vertex count of a mesh transform/shape, or None on failure."""
    try:
        return cmds.polyEvaluate(mesh, vertex=True)
    except Exception:
        return None


def validate_topology(target_mesh: str,
                      source_mesh: Optional[str] = None,
                      ) -> Tuple[Optional[int], Optional[int], bool]:
    """Compare the target (rest) mesh vert count against the source (abc) mesh.

    When ``source_mesh`` is empty we can only return the target count and
    ``valid=True`` (nothing to compare against yet).

    Args:
        target_mesh: The rest mesh that will carry the skinCluster.
        source_mesh: The abc-driven deformed mesh the solve targets.

    Returns:
        (target_count, source_count, valid)
    """
    target_n = mesh_vertex_count(target_mesh)
    source_n = mesh_vertex_count(source_mesh) if source_mesh else None

    if target_n is None:
        return None, source_n, False
    if source_n is None:
        # Nothing to compare; treat as provisionally valid.
        return target_n, None, True
    return target_n, source_n, target_n == source_n


def create_rest_duplicate(source_mesh: str,
                          frame: Optional[int] = None,
                          ) -> str:
    """Duplicate the source mesh at ``frame`` to make a static rest mesh.

    The duplicate carries no upstream graph (no AlembicNode), so it stays put at
    the sampled frame - exactly the non-animated rest geometry DemBones wants
    for ``-i``.

    Args:
        source_mesh: The abc-driven deformed mesh.
        frame: Frame to sample (the alembic's first frame). When None the
            current time is used.

    Returns:
        The new rest mesh transform name.
    """
    if frame is not None:
        try:
            cmds.currentTime(frame)
        except Exception as e:
            logger.warning(f"Could not set time to {frame}: {e}")

    short = source_mesh.split("|")[-1].split(":")[-1]
    dup = cmds.duplicate(source_mesh,
                         name=f"{short}_rest",
                         returnRootsOnly=True)[0]
    # Make it fully static: drop any construction history that came along.
    try:
        cmds.delete(dup, constructionHistory=True)
    except Exception:
        pass
    return dup


# ============================================================================
# PATHS / FRAME RANGE
# ============================================================================

def timeline_range() -> Tuple[int, int]:
    """Return Maya's current playback range (start, end)."""
    start = int(cmds.playbackOptions(query=True, minTime=True))
    end = int(cmds.playbackOptions(query=True, maxTime=True))
    return start, end


def default_output_dir() -> str:
    """Default solve output dir: <project>/cache/dembones, tempdir fallback."""
    try:
        root = cmds.workspace(query=True, rootDirectory=True)
        if root:
            out = os.path.join(root, "cache", "dembones")
            os.makedirs(out, exist_ok=True)
            return out
    except Exception as e:
        logger.warning(f"Could not resolve project output dir: {e}")
    out = os.path.join(tempfile.gettempdir(), "dembones")
    os.makedirs(out, exist_ok=True)
    return out


# ============================================================================
# FBX EXPORT (the init -i file)
# ============================================================================

def _ensure_fbx_plugin() -> None:
    if not cmds.pluginInfo("fbxmaya", query=True, loaded=True):
        cmds.loadPlugin("fbxmaya")


def export_target_fbx(mesh: str,
                      out_fbx: str,
                      with_rig: bool,
                      joints: Optional[List[str]] = None,
                      ) -> str:
    """Export the rest mesh (optionally with its joints + skinCluster) to FBX.

    Args:
        mesh: Rest mesh (the non-animated target mesh).
        out_fbx: Destination .fbx path.
        with_rig: When True, export skin + skeleton; else mesh-only geometry.
        joints: Joints to include with the rig (defaults to skin influences).

    Returns:
        The output path written.
    """
    _ensure_fbx_plugin()
    out_fbx = out_fbx.replace("\\", "/")

    selection = [mesh]
    if with_rig:
        if joints is None:
            joints = find_joints_from_mesh(mesh)
        selection += joints
        mel.eval("FBXExportSkins -v true")
        mel.eval("FBXExportSkeletonDefinitions -v true")
    else:
        mel.eval("FBXExportSkins -v false")

    cmds.select(selection, replace=True)
    # Bake nothing here; the init FBX is a static rest pose.
    mel.eval("FBXExportInAscii -v false")
    mel.eval(f'FBXExport -f "{out_fbx}" -s')
    logger.info(f"Exported target FBX -> {out_fbx} (with_rig={with_rig})")
    return out_fbx


# ============================================================================
# EXE ARGUMENT BUILDING
# ============================================================================

# UI param key -> DemBones CLI flag. Only emitted when present in the params.
_PARAM_FLAGS = {
    "nBones":           "-b",
    "nIters":           "-n",
    "nInitIters":       "--nInitIters",
    "nTransIters":      "--nTransIters",
    "nWeightsIters":    "--nWeightsIters",
    "nnz":              "--nnz",
    "weightsSmooth":    "--weightsSmooth",
    "weightsSmoothStep": "--weightsSmoothStep",
    "transAffine":      "--transAffine",
    "transAffineNorm":  "--transAffineNorm",
    "bindUpdate":       "--bindUpdate",
    "patience":         "--patience",
    "tolerance":        "--tolerance",
}


def build_args(abc_path: str,
               init_fbx: str,
               out_fbx: str,
               params: Dict,
               use_rig: bool,
               ) -> List[str]:
    """Build the DemBones.exe argument list.

    Args:
        abc_path: Animated cache (-a).
        init_fbx: Rest geometry FBX, optionally with bones/skin (-i).
        out_fbx: Output FBX (-o).
        params: UI param dict (keys from ``_PARAM_FLAGS``).
        use_rig: When True the init already has bones; drop -b so DemBones
            infers the bone count from the rig instead of re-clustering.

    Returns:
        Argument list (without the exe itself). Each entry is a single
        ``flag=value`` token - DemBones' Windows parser requires the ``=`` form
        (``-a=path``, ``--nnz=8``), not space-separated pairs. Paths are NOT
        wrapped in literal quotes here: QProcess quotes any argument containing
        spaces when it builds the command line, so embedding quotes would
        double-quote and break the path.
    """
    args: List[str] = [
        f"-a={abc_path.replace(chr(92), '/')}",
        f"-i={init_fbx.replace(chr(92), '/')}",
        f"-o={out_fbx.replace(chr(92), '/')}",
    ]
    for key, flag in _PARAM_FLAGS.items():
        if key == "nBones" and use_rig:
            # Let the solver infer bone count from the supplied rig.
            continue
        if key in params and params[key] is not None:
            args.append(f"{flag}={params[key]}")
    return args


# ============================================================================
# GENERATIONS (fbx + sidecar json)
# ============================================================================

def next_generation_index(out_dir: str) -> int:
    """Return the next free leading number for a generation file.

    Generations are named ``NNN_<...>.fbx`` so they always sort the same way
    and map to a stable ``demNNN`` namespace on import. This scans existing
    files and returns ``max(NNN) + 1`` (1 when the dir is empty).
    """
    max_n = 0
    if out_dir and os.path.isdir(out_dir):
        for fbx in glob.glob(os.path.join(out_dir, "*.fbx")):
            m = re.match(r"(\d+)_", os.path.basename(fbx))
            if m:
                max_n = max(max_n, int(m.group(1)))
    return max_n + 1


def sidecar_path(fbx_path: str) -> str:
    """Return the sidecar .json path for a generation fbx."""
    return os.path.splitext(fbx_path)[0] + ".json"


def write_sidecar(fbx_path: str, meta: Dict) -> str:
    """Write a generation's metadata next to its fbx."""
    path = sidecar_path(fbx_path)
    try:
        with open(path, "w") as fh:
            json.dump(meta, fh, indent=2)
    except Exception as e:
        logger.error(f"Failed to write sidecar '{path}': {e}")
    return path


def read_sidecar(fbx_path: str) -> Dict:
    """Read a generation's sidecar metadata (empty dict if missing/broken)."""
    path = sidecar_path(fbx_path)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r") as fh:
            return json.load(fh)
    except Exception as e:
        logger.warning(f"Failed to read sidecar '{path}': {e}")
        return {}


def scan_generations(out_dir: str) -> List[Dict]:
    """List solved generations in ``out_dir`` as metadata dicts.

    Only FBX files that have a sidecar json are returned - that is the solve
    output. Intermediate exports (the ``_rest`` init FBX, manual target dumps)
    have no sidecar and are skipped, so the list shows decompositions only.

    Each dict carries at least ``fbx`` (full path) and ``name`` plus whatever
    the sidecar stored (params, range, rmse).
    """
    results: List[Dict] = []
    if not out_dir or not os.path.isdir(out_dir):
        return results
    for fbx in sorted(glob.glob(os.path.join(out_dir, "*.fbx"))):
        meta = read_sidecar(fbx)
        if not meta:
            continue  # no sidecar -> not a solve output
        meta["fbx"] = fbx
        meta.setdefault("name", os.path.splitext(os.path.basename(fbx))[0])
        results.append(meta)
    return results


def _unique_namespace(base: str) -> str:
    """Return ``base`` or ``base_1``/``base_2``... if it already exists."""
    if not cmds.namespace(exists=base):
        return base
    i = 1
    while cmds.namespace(exists=f"{base}_{i}"):
        i += 1
    return f"{base}_{i}"


def import_generation(fbx_path: str,
                      namespace: Optional[str] = None,
                      group_under_root: bool = True,
                      ) -> List[str]:
    """Import a solved FBX (joints + skin + anim) back into the scene.

    The import goes into a short namespace (``dem001``, ``dem002``, ...) so a
    same-named mesh/joints already in the scene don't get merged - that merge is
    why a bare ``FBXImport`` looked like it skipped the mesh.

    Args:
        fbx_path: Generation fbx to import.
        namespace: Target namespace. When None it's derived from the file's
            leading number (``001_...fbx`` -> ``dem001``). Made unique if taken.
        group_under_root: Parent the imported nodes under one transform so the
            artist can place the whole result in local space.

    Returns:
        The newly created top-level nodes.
    """
    _ensure_fbx_plugin()
    fbx_path = fbx_path.replace("\\", "/")

    if namespace is None:
        m = re.match(r"(\d+)_", os.path.basename(fbx_path))
        namespace = f"dem{int(m.group(1)):03d}" if m else "dem001"
    namespace = _unique_namespace(namespace)

    # Make sure the FBX importer adds nodes (rather than updating existing).
    try:
        mel.eval("FBXImportMode -v add")
        mel.eval("FBXImportSkins -v true")
    except Exception:
        pass

    new_nodes = cmds.file(fbx_path,
                          i=True,
                          type="FBX",
                          namespace=namespace,
                          mergeNamespacesOnClash=False,
                          returnNewNodes=True,
                          ignoreVersion=True) or []

    roots = cmds.ls(new_nodes, assemblies=True) or []
    if group_under_root and roots:
        root = cmds.group(roots, name=f"{namespace}_GRP")
        return [root]
    return roots


# ============================================================================
# SOLVE RUNNER (non-blocking QProcess wrapper)
# ============================================================================

class SolveRunner(QtCore.QObject):
    """Run DemBones.exe via QProcess so the UI stays responsive.

    Signals
    -------
    log(str)       a line of stdout/stderr from the exe.
    finished(int)  process exit code (0 = success).
    """

    log = QtCore.Signal(str)
    finished = QtCore.Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._proc: Optional[QtCore.QProcess] = None

    def is_running(self) -> bool:
        return (self._proc is not None
                and self._proc.state() != QtCore.QProcess.NotRunning)

    def start(self, exe: str, args: List[str]) -> bool:
        """Launch the exe with args. Returns False if one is already running."""
        if self.is_running():
            self.log.emit("A solve is already running.")
            return False

        self._proc = QtCore.QProcess(self)
        self._proc.setProcessChannelMode(QtCore.QProcess.MergedChannels)
        self._proc.readyReadStandardOutput.connect(self._on_output)
        self._proc.finished.connect(self._on_finished)

        self.log.emit(self._format_cmd(exe, args))
        self._proc.start(exe, args)
        return True

    @staticmethod
    def _format_cmd(exe: str, args: List[str]) -> str:
        """Render the command for the log, quoting tokens that contain spaces.

        Display only - QProcess does the real quoting when it runs the exe.
        """
        def q(token: str) -> str:
            # Quote the value part of a flag=value token if the value has spaces.
            if "=" in token:
                flag, _, value = token.partition("=")
                if " " in value:
                    return f'{flag}="{value}"'
                return token
            return f'"{token}"' if " " in token else token
        return "$ " + " ".join(q(t) for t in [exe] + args)

    def cancel(self) -> None:
        if self.is_running():
            self._proc.kill()
            self.log.emit("Solve cancelled.")

    def _on_output(self) -> None:
        data = bytes(self._proc.readAllStandardOutput()).decode("utf-8", "replace")
        for line in data.splitlines():
            self.log.emit(line)

    def _on_finished(self, code, _status) -> None:
        self.finished.emit(int(code))


def parse_rmse(log_text: str) -> Optional[float]:
    """Pull the last rmse value out of the exe log, if present."""
    import re
    matches = re.findall(r"rmse[^0-9eE+\-.]*([0-9eE+\-.]+)", log_text, re.IGNORECASE)
    if not matches:
        return None
    try:
        return float(matches[-1])
    except ValueError:
        return None