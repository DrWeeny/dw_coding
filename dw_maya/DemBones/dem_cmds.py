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
import shutil
import tempfile
from typing import Dict, List, Optional, Tuple

from maya import cmds, mel

from dw_maya.DemBones.compat import QtCore
from dw_logger import get_logger

logger = get_logger()


# ============================================================================
# EXE RESOLUTION
# ============================================================================

# Where to get the precompiled binaries when none is found. DemBones is an
# Electronic Arts project under BSD-3 - the binaries are not redistributed with
# this repo, so the artist points the tool at their own copy (PATH or env var).
DEMBONES_DOWNLOAD_URL = "https://github.com/electronicarts/dem-bones/releases"

# Maya optionVar that stores a user-located exe path (set via "Locate DemBones"
# in the UI). Persists across Maya sessions, per user.
_EXE_PREF_KEY = "dw_dembones_exe"


def get_saved_exe() -> Optional[str]:
    """Return the user-located exe path saved in the Maya prefs, if any."""
    try:
        if cmds.optionVar(exists=_EXE_PREF_KEY):
            path = cmds.optionVar(query=_EXE_PREF_KEY)
            if path and os.path.isfile(path):
                return path
    except Exception as e:
        logger.warning(f"Could not read DemBones exe pref: {e}")
    return None


def set_saved_exe(path: str) -> None:
    """Persist a user-located exe path to the Maya prefs."""
    try:
        cmds.optionVar(stringValue=(_EXE_PREF_KEY, path))
    except Exception as e:
        logger.error(f"Could not save DemBones exe pref: {e}")


def _exe_name() -> str:
    """Platform executable file name."""
    return "DemBones.exe" if sys.platform.startswith("win") else "DemBones"


def _bundled_exe_path() -> str:
    """Expected path of a binary dropped under ``<package>/bin/<OS>/``."""
    here = os.path.dirname(os.path.abspath(__file__))
    if sys.platform.startswith("win"):
        sub = "Windows"
    elif sys.platform.startswith("linux"):
        sub = "Linux"
    else:
        sub = "macOS"
    return os.path.join(here, "bin", sub, _exe_name())


def get_exe_path() -> Optional[str]:
    """Resolve the DemBones executable for the current platform.

    Resolution order, first hit wins:
        1. ``DEMBONES_EXE`` env var - an explicit path (pipeline / tool deploy).
        2. A path the artist located via the UI (saved in Maya prefs).
        3. The system ``PATH`` (artist installed DemBones globally).
        4. A binary dropped under ``<package>/bin/<OS>/DemBones[.exe]``.

    The binaries themselves are not committed (BSD-3, large, platform specific);
    see :data:`DEMBONES_DOWNLOAD_URL`.

    Returns:
        str path to the executable, or ``None`` if it can't be found.
    """
    # 1. Explicit override (pipeline / tool deploy).
    override = os.environ.get("DEMBONES_EXE")
    if override and os.path.isfile(override):
        return override
    if override:
        logger.warning(f"DEMBONES_EXE is set but not a file: {override}")

    # 2. User-located path saved in the Maya prefs.
    saved = get_saved_exe()
    if saved:
        return saved

    # 3. On PATH.
    on_path = shutil.which(_exe_name())
    if on_path:
        return on_path

    # 4. Bundled alongside the tool.
    candidate = _bundled_exe_path()
    if os.path.isfile(candidate):
        return candidate

    logger.warning(
        f"DemBones exe not found (env DEMBONES_EXE, saved pref, PATH, or "
        f"{candidate}). Download from {DEMBONES_DOWNLOAD_URL}")
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
# SKIN TRANSFER (DemBones result -> pipeline mesh, influences differ by namespace)
# ============================================================================

def _leaf_name(node: str) -> str:
    """Strip dag path and namespace, leaving the bare node name."""
    return node.split("|")[-1].split(":")[-1]


def _resolve_target_joint(short_name: str,
                          exclude: str,
                          target_namespace: Optional[str],
                          ) -> Optional[str]:
    """Find the target joint matching a source influence by short name.

    Args:
        short_name: Namespace-stripped influence name (e.g. ``SSDR_JNT_8``).
        exclude: The source influence's full name, so it can't map to itself.
        target_namespace: When given, look only for ``<ns>:<short_name>`` (or
            the root-namespace name when an empty string is passed). When None,
            search the scene for any joint with that short name.

    Returns:
        The target joint's full name, or None if it can't be resolved uniquely.
    """
    if target_namespace is not None:
        candidate = f"{target_namespace}:{short_name}" if target_namespace else short_name
        return candidate if cmds.objExists(candidate) else None

    matches = cmds.ls(f"*:{short_name}", short_name, type="joint", long=True) or []
    matches = [m for m in matches if m != exclude and _leaf_name(m) == short_name]
    if not matches:
        return None
    if len(matches) > 1:
        logger.warning(
            f"'{short_name}' resolves to {len(matches)} joints {matches}; using "
            f"the first. Pass target_namespace to disambiguate.")
    return matches[0]


def build_influence_map(source_influences: List[str],
                        target_namespace: Optional[str] = None,
                        ) -> Tuple[Dict[str, str], List[str]]:
    """Map each source influence to its target counterpart by short name.

    Only the namespace differs between the two skeletons, so influences are
    paired on their namespace-stripped name.

    Args:
        source_influences: Influences of the source skinCluster, in order.
        target_namespace: Namespace of the target joints. None to auto-search
            the scene by short name; an empty string for the root namespace.

    Returns:
        (mapping src->tgt, list of unresolved source influences).
    """
    mapping: Dict[str, str] = {}
    missing: List[str] = []
    for inf in source_influences:
        tgt = _resolve_target_joint(_leaf_name(inf), inf, target_namespace)
        if tgt:
            mapping[inf] = tgt
        else:
            missing.append(inf)
    return mapping, missing


def transfer_skin_by_name(source_mesh: str,
                          target_mesh: str,
                          target_namespace: Optional[str] = None,
                          new_skin_name: Optional[str] = None,
                          ) -> Optional[str]:
    """Copy skinning from ``source_mesh`` to ``target_mesh`` by influence name.

    Built for the DemBones-result -> pipeline-mesh case where the two skeletons
    are the same joints under a different namespace. Influences are paired on
    their short name, a skinCluster is built on the target bound to the matching
    joints (in source order), and weights are copied with Maya's
    ``copySkinWeights`` using closest-point surface association - exact when the
    meshes share topology, nearest-point otherwise. Influence association is
    closest-joint, which is robust here since the joints sit at identical world
    positions.

    Args:
        source_mesh: The skinned DemBones-result mesh (transform or shape).
        target_mesh: The pipeline mesh to receive the skinning.
        target_namespace: Namespace of the target joints (None = auto-search by
            short name; "" = root namespace).
        new_skin_name: Optional name for a newly created target skinCluster.

    Returns:
        The target skinCluster name, or None on failure.
    """
    src_skin = find_skin_cluster(source_mesh)
    if not src_skin:
        logger.error(f"No skinCluster found on source mesh '{source_mesh}'.")
        return None

    src_infs = skin_influences(src_skin)
    mapping, missing = build_influence_map(src_infs, target_namespace)
    if missing:
        logger.error(
            f"{len(missing)} influence(s) could not be matched on the target: "
            f"{missing}. Aborting transfer.")
        return None

    target_infs = [mapping[inf] for inf in src_infs]   # keep source order

    tgt_skin = find_skin_cluster(target_mesh)
    if not tgt_skin:
        name = new_skin_name or f"{_leaf_name(target_mesh)}_skinCluster"
        tgt_skin = cmds.skinCluster(target_infs,
                                    target_mesh,
                                    toSelectedBones=True,
                                    normalizeWeights=1,
                                    name=name)[0]
        logger.info(f"Created skinCluster '{tgt_skin}' on '{target_mesh}'.")
    else:
        existing = set(skin_influences(tgt_skin))
        for joint in target_infs:
            if joint not in existing:
                cmds.skinCluster(tgt_skin,
                                 edit=True,
                                 addInfluence=joint,
                                 weight=0.0)

    cmds.copySkinWeights(sourceSkin=src_skin,
                         destinationSkin=tgt_skin,
                         noMirror=True,
                         surfaceAssociation="closestPoint",
                         influenceAssociation=["closestJoint", "oneToOne"])
    logger.info(
        f"Transferred {len(target_infs)} influences '{src_skin}' -> '{tgt_skin}'.")
    return tgt_skin


_TRANSFORM_CHANNELS = [
    "translateX", "translateY", "translateZ",
    "rotateX", "rotateY", "rotateZ",
    "scaleX", "scaleY", "scaleZ",
]


def bake_target_skeleton(target_mesh: str,
                         start: int,
                         end: int,
                         clean_constraints: bool = True,
                         ) -> List[str]:
    """Bake the target skinCluster's joints so they no longer depend on the
    source skeleton.

    After a name-based skin transfer the target joints are usually still driven
    by the source bones (a connection or constraint), so deleting the source
    breaks the result. Baking over the frame range replaces that drive with the
    skeleton's own anim curves - ``cmds.bakeResults`` disconnects the driven
    inputs as it keys - making the target self-contained and the source safe to
    delete.

    Args:
        target_mesh: The skinned pipeline mesh whose skeleton to bake.
        start: First frame to bake.
        end: Last frame to bake.
        clean_constraints: Delete any leftover constraint nodes parented under
            the joints after baking.

    Returns:
        The list of baked joints (empty on failure).
    """
    skin = find_skin_cluster(target_mesh)
    if not skin:
        logger.error(f"No skinCluster found on '{target_mesh}'; nothing to bake.")
        return []

    joints = skin_influences(skin)
    if not joints:
        logger.error(f"skinCluster '{skin}' has no influences to bake.")
        return []

    cmds.bakeResults(joints,
                     simulation=True,
                     time=(start, end),
                     sampleBy=1,
                     disableImplicitControl=True,
                     preserveOutsideKeys=False,
                     sparseAnimCurveBake=False,
                     attribute=_TRANSFORM_CHANNELS)

    if clean_constraints:
        for joint in joints:
            cons = cmds.listRelatives(joint,
                                      children=True,
                                      type="constraint",
                                      fullPath=True) or []
            if cons:
                cmds.delete(cons)

    logger.info(
        f"Baked {len(joints)} joints on '{target_mesh}' over [{start}, {end}]; "
        f"target skeleton is now independent of the source.")
    return joints


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