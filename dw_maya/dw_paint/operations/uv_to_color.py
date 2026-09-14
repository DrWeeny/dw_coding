# operations/uv_to_color.py
"""Bake a UV set into vertex-colour channels.

Summary:
    Stores a mesh's UV coordinates as per-vertex colour so a shader, a solver
    or a cache can read them back where no UV lookup is available. U goes to
    RED and V to BLUE by default, leaving GREEN and ALPHA untouched - a
    convention that keeps green free for a mask and reads clearly in the
    viewport, where a UV square becomes a red/blue gradient.

    **Why the UV set has to be named.** ``MeshData.vertex_uvs`` reads whatever
    UV set is *current*, which is fine for a one-off query and wrong here: the
    set that was authored to carry this data (often not ``map1``) has to be
    addressed by name, or the bake silently records a different parameterisation
    that looks plausible and is not.

    **Seams.** UVs are per-face-vertex; vertex colours written here are
    per-vertex. A vertex on a UV seam therefore has several UVs and only one
    slot to store them in. This module averages them and REPORTS how many were
    affected rather than silently smoothing across the cut - on a set authored
    one-UV-per-vertex (UV count == vertex count) the count is zero and the bake
    is exact, which is the case this is meant for.

Features:
    - Named UV set, never the current one by accident.
    - Reports seam vertices and UVs outside 0-1 instead of clamping behind the
      caller's back; clamping is opt-in.
    - Writes through :class:`VertexColorSet`, so the result is undoable and
      the B&W preview stays correct.

Classes:
    UVBakeResult

Functions:
    uv_sets - the UV sets a mesh carries.
    get_uvs - per-vertex U and V for a named set, with seam/range counts.
    uv_to_color - the operation: bake a UV set into two colour channels.

Example::

    import dw_maya.dw_paint.operations.uv_to_color as uv_to_color

    print(uv_to_color.uv_sets('pPlane1'))            # ['map1', 'map2', 'map3']
    report = uv_to_color.uv_to_color('pPlane1', uv_set='map3')
    print(report.summary())

TODO:
    - A per-face-vertex mode, for a seamed set where averaging is not
      acceptable. Needs MFnMesh.setFaceVertexColors and a reader that does not
      collapse to per-vertex.

Author:
    DrWeeny
"""

from typing import Dict, List, Optional, Tuple

import numpy as np

from maya import cmds
import maya.api.OpenMaya as om2

from ..core import MeshDataFactory, WeightList
from ..vertex_color import VertexColorSet, create_alpha_map
from dw_logger import get_logger

logger = get_logger()

#: Channel each UV component lands in by default. Green stays free for a mask.
DEFAULT_U_CHANNEL = 'red'
DEFAULT_V_CHANNEL = 'blue'

#: Channels a UV component may be written to.
CHANNELS = ('red', 'green', 'blue', 'alpha')


class UVBakeResult:
    """What a UV bake did, and what it had to compromise on.

    Attributes:
        mesh: Mesh the bake ran on.
        uv_set: UV set that was read.
        color_set: Colour set that was written.
        channels: ``(u channel, v channel)``.
        vertex_count: Vertices written.
        seam_vertices: Vertices whose several UVs were averaged into one.
        unmapped_vertices: Vertices with no UV in this set - written as 0.
        out_of_range: Vertices whose U or V fell outside 0-1.
        clamped: Whether those were clamped.
        u_range: ``(min, max)`` of U actually written.
        v_range: ``(min, max)`` of V actually written.
    """

    def __init__(self,
                 mesh: str = '',
                 uv_set: str = '',
                 color_set: str = '',
                 channels: Tuple[str, str] = (DEFAULT_U_CHANNEL,
                                              DEFAULT_V_CHANNEL),
                 vertex_count: int = 0,
                 seam_vertices: int = 0,
                 unmapped_vertices: int = 0,
                 out_of_range: int = 0,
                 clamped: bool = False,
                 u_range: Tuple[float, float] = (0.0, 0.0),
                 v_range: Tuple[float, float] = (0.0, 0.0),
                 ):
        self.mesh = mesh
        self.uv_set = uv_set
        self.color_set = color_set
        self.channels = channels
        self.vertex_count = vertex_count
        self.seam_vertices = seam_vertices
        self.unmapped_vertices = unmapped_vertices
        self.out_of_range = out_of_range
        self.clamped = clamped
        self.u_range = u_range
        self.v_range = v_range
        #: Set by :func:`uv_to_color` when it had to create the colour set.
        self.created_color_set = False

    @property
    def exact(self) -> bool:
        """True when nothing had to be averaged or dropped."""
        return not self.seam_vertices and not self.unmapped_vertices

    def summary(self) -> str:
        """One readable block, leading with whatever was compromised."""
        made = " (created)" if self.created_color_set else ""
        lines = [f"{self.mesh.split('|')[-1]}: '{self.uv_set}' -> "
                 f"'{self.color_set}'{made} "
                 f"({self.channels[0]}=U, {self.channels[1]}=V), "
                 f"{self.vertex_count} vertices"]
        if self.seam_vertices:
            lines.append(f"  {self.seam_vertices} seam vertex/vertices "
                         f"averaged - their UVs disagree and only one fits")
        if self.unmapped_vertices:
            lines.append(f"  {self.unmapped_vertices} vertex/vertices have no "
                         f"UV in this set, written as 0")
        if self.out_of_range:
            state = "clamped to 0-1" if self.clamped else "written as-is"
            lines.append(f"  {self.out_of_range} vertex/vertices outside 0-1, "
                         f"{state}")
        if self.exact and not self.out_of_range:
            lines.append("  exact: one UV per vertex, all inside 0-1")
        lines.append(f"  U {self.u_range[0]:.4f}..{self.u_range[1]:.4f}   "
                     f"V {self.v_range[0]:.4f}..{self.v_range[1]:.4f}")
        return "\n".join(lines)

    def __repr__(self) -> str:
        return (f"UVBakeResult({self.mesh.split('|')[-1]!r}, "
                f"uv_set={self.uv_set!r}, vertices={self.vertex_count}, "
                f"seams={self.seam_vertices})")


def _shape_of(mesh: str) -> str:
    """The deformable shape under a transform, or the shape itself."""
    if cmds.objectType(mesh, isAType='mesh'):
        return mesh
    shapes = cmds.listRelatives(mesh, shapes=True, noIntermediate=True,
                                fullPath=True) or []
    if not shapes:
        raise ValueError(f"No mesh shape under '{mesh}'")
    return shapes[0]


def uv_sets(mesh: str) -> List[str]:
    """The UV sets a mesh carries, in Maya's order.

    Args:
        mesh: Mesh transform or shape.

    Returns:
        UV set names, or [] when the mesh has none.
    """
    return list(cmds.polyUVSet(mesh, query=True, allUVSets=True) or [])


def current_uv_set(mesh: str) -> str:
    """The mesh's current UV set, or ''."""
    found = cmds.polyUVSet(mesh, query=True, currentUVSet=True) or []
    return found[0] if found else ''


def get_uvs(mesh: str,
            uv_set: str = '',
            ) -> Tuple[np.ndarray, Dict]:
    """Per-vertex U and V for a named UV set.

    Reads through ``MItMeshVertex.getUVs(uvSet)`` - the named overload, so the
    mesh's current UV set is irrelevant and never switched. A vertex carrying
    several UVs (a seam) is averaged, and counted.

    Args:
        mesh: Mesh transform or shape.
        uv_set: UV set to read. Empty uses the mesh's current one.

    Returns:
        ``(uvs, stats)`` where ``uvs`` is an Nx2 float array (columns U, V) and
        ``stats`` is ``{'seams', 'unmapped'}``.

    Raises:
        ValueError: When the mesh has no such UV set.
    """
    shape = _shape_of(mesh)
    available = uv_sets(shape)
    uv_set = uv_set or current_uv_set(shape)
    if not uv_set:
        raise ValueError(f"'{mesh}' has no UV set to read")
    if uv_set not in available:
        raise ValueError(f"'{mesh}' has no UV set '{uv_set}' - it has "
                         f"{available}")

    sel = om2.MSelectionList()
    sel.add(shape)
    dag = sel.getDagPath(0)
    count = om2.MFnMesh(dag).numVertices

    uvs = np.zeros((count, 2), dtype=np.float64)
    seams = 0
    unmapped = 0

    it = om2.MItMeshVertex(dag)
    while not it.isDone():
        index = it.index()
        try:
            u_arr, v_arr, _faces = it.getUVs(uv_set)
        except RuntimeError:
            # Not an error: a vertex can simply be outside this set's layout.
            u_arr, v_arr = [], []
        if not len(u_arr):
            unmapped += 1
        else:
            if len(u_arr) > 1 and (len(set(u_arr)) > 1 or len(set(v_arr)) > 1):
                # Several face-vertices reference this vertex with DIFFERENT
                # UVs - a real seam. Several references to the same UV is not.
                seams += 1
            uvs[index, 0] = float(np.mean(u_arr))
            uvs[index, 1] = float(np.mean(v_arr))
        it.next()

    return uvs, {"seams": seams, "unmapped": unmapped}


def uv_to_color(mesh: str,
                uv_set: str = '',
                color_set: str = '',
                u_channel: str = DEFAULT_U_CHANNEL,
                v_channel: str = DEFAULT_V_CHANNEL,
                clamp: bool = False,
                dry_run: bool = False,
                ) -> UVBakeResult:
    """Bake a UV set into two vertex-colour channels.

    U lands in ``u_channel`` and V in ``v_channel``; every other channel of the
    colour set is left exactly as it was, so this can be run over an existing
    map without destroying a mask stored beside it.

    Args:
        mesh: Mesh transform or shape.
        uv_set: UV set to read. Empty uses the mesh's current one.
        color_set: Colour set to write. Empty uses the mesh's current one.
            A name that does not exist yet is CREATED (via ``create_alpha_map``,
            which establishes a full RGBA baseline - writing single channels
            into a fresh set otherwise leaves Maya's storage ambiguous). Prefer
            a dedicated set: baking over a colour set that already carries a
            painted mask costs whichever channel U or V lands in.
        u_channel: Channel for U. One of :data:`CHANNELS`.
        v_channel: Channel for V. Must differ from ``u_channel``.
        clamp: Clamp values into 0-1. Off by default: a UV set laid out over
            several tiles is meaningless once clamped, and silently flattening
            it would hide that. The report says how many are affected either
            way.
        dry_run: Measure and report, write nothing.

    Returns:
        A :class:`UVBakeResult`.

    Raises:
        ValueError: On an unknown UV set, an unknown channel, or the same
            channel given for both components.
    """
    if u_channel not in CHANNELS:
        raise ValueError(f"Unknown channel '{u_channel}' - use one of "
                         f"{list(CHANNELS)}")
    if v_channel not in CHANNELS:
        raise ValueError(f"Unknown channel '{v_channel}' - use one of "
                         f"{list(CHANNELS)}")
    if u_channel == v_channel:
        raise ValueError(f"U and V would both write to '{u_channel}' - the "
                         f"second would overwrite the first")

    shape = _shape_of(mesh)
    uv_set = uv_set or current_uv_set(shape)
    uvs, stats = get_uvs(shape, uv_set)

    outside = int(np.count_nonzero((uvs < 0.0) | (uvs > 1.0)))
    if clamp:
        uvs = np.clip(uvs, 0.0, 1.0)

    existing = cmds.polyColorSet(shape, query=True, allColorSets=True) or []
    if color_set and color_set not in existing and not dry_run:
        # Through create_alpha_map, not a bare polyColorSet create: it floods a
        # full RGBA baseline afterwards, without which single-channel writes on
        # a brand-new set read back as Maya's internal default rather than what
        # was written. That trap is documented on create_alpha_map itself.
        #
        # default_value=1.0, i.e. an OPAQUE baseline, unlike the 0.0 a painted
        # mask wants: alpha here carries no meaning, and a bake left at alpha 0
        # draws as nothing in the viewport - the data is written and correct,
        # and the mesh looks untouched, which reads as a failed bake.
        create_alpha_map(mesh, color_set=color_set, default_value=1.0)
    source = VertexColorSet(mesh, color_set)
    result = UVBakeResult(
        mesh=mesh,
        uv_set=uv_set,
        color_set=source.color_set,
        channels=(u_channel, v_channel),
        vertex_count=int(uvs.shape[0]),
        seam_vertices=stats["seams"],
        unmapped_vertices=stats["unmapped"],
        out_of_range=outside,
        clamped=bool(clamp),
        u_range=(float(uvs[:, 0].min()), float(uvs[:, 0].max())) if len(uvs)
        else (0.0, 0.0),
        v_range=(float(uvs[:, 1].min()), float(uvs[:, 1].max())) if len(uvs)
        else (0.0, 0.0),
    )

    result.created_color_set = bool(color_set) and color_set not in existing
    if dry_run:
        return result

    # Two writes, not one: VertexColorSet owns the read-modify-write that keeps
    # the other channels intact, plus the undo entry and the preview refresh.
    # Reproducing that here to save a pass would mean reproducing all three.
    u_values: WeightList = uvs[:, 0].tolist()
    v_values: WeightList = uvs[:, 1].tolist()
    source.use_map(u_channel).set_weights(u_values)
    source.use_map(v_channel).set_weights(v_values)

    logger.info(result.summary())
    return result
