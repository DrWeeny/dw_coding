"""WeightSource wrapper for vertex color channels (RGBA).

Maya does not expose the individual channels of a colorSet as paintable
scalar maps.  This module treats each channel (red, green, blue, alpha)
of a colorSet as a standard ``WeightSource`` map so Slimfast (and any
other consumer) can read, write, smooth, remap, copy/paste, and visualise
one channel at a time without touching the other three.

Features:
    - Read/write any single channel per vertex (polyColorPerVertex).
    - Four maps per colorSet: ``alpha`` (default), ``red``, ``green``, ``blue``.
    - Preview mode: copies the active channel -> RGB on a temp colorSet for
      B&W viewport feedback.
    - Interactive artisan painting via artUserPaintCtx (paint one channel
      in real-time).
    - Compatible with apply_operation (flood, smooth, vector, radial ...).

Classes:
    VertexColorSet — WeightSource exposing a colorSet's channels as maps.

Functions:
    install_mel_procs — Register the MEL callbacks needed by artUserPaintCtx.
    create_alpha_map — Create a colorSet and flood its alpha channel.

Example::

    from dw_maya.dw_paint.vertex_color import VertexColorSet
    src = VertexColorSet('pSphere1', color_set='colorSet1')
    src.use_map('red')
    weights = src.get_weights()
    src.set_weights([w * 0.5 for w in weights])

Debugging note (2026-07-23): while chasing a channel-bleed bug in this
module, a freshly launched Maya process (no scene explicitly opened)
still reproduced the bug identically to a session with hours of prior
testing -- restarting the Maya *application* was not enough to get a
clean repro. Only doing File > New (a genuinely empty scene, with the
test mesh/colorSet rebuilt from scratch afterward) actually cleared
whatever state was carrying the corruption forward. Root cause not
pinned down further than that; likely Maya reopening/retaining some
prior scene state on launch (autosave/crash recovery, workspace-remembered
file, or similar) rather than truly starting blank. Lesson for future
debugging sessions on this module: "restart Maya" is not sufficient to
rule out stale state -- use File > New and rebuild the repro from
scratch before trusting a result as a clean signal.

Direct-mode experiment REVERTED (2026-07-27): production confirmed that
painting in direct/color mode bleeds the sibling channels (exactly the
risk flagged below). Painting is now ALWAYS B&W-locked -- ``_paint`` forces
the scratch canvas on, ``preview_locked`` returns True for the whole paint
session, and ``disable_preview`` refuses to leave B&W while the tool is
active. Direct mode survives only as dormant code paths keyed off
``_preview_active`` (kept so the two-mode plumbing isn't lost), but
``_preview_active`` is now pinned True for every paint session. The
paragraph below documents the (now-inactive) experiment for context.

Direct-mode experiment (2026-07-24): the fix above landed as two bundled
changes in one commit -- (1) stop switching 'current' to the real colorSet
for reads (getVertexColors takes a colorSet name directly, no switch
needed), which is the actual root cause fix, and (2) unconditionally pin
'current' to the scratch colorSet for the WHOLE paint session, even
between strokes, which is what forces the B&W-only viewport during
painting. (2) was never tested in isolation with (1) already in place --
it was reverted from an earlier "show true colors between strokes"
version that broke BEFORE fix (1) existed, so the two failures were
confounded. This module now supports two live-switchable paint modes,
driven by ``VertexColorSet._preview_active`` (the same flag the B&W
toggle button sets):
    - Direct mode (``_preview_active=False``): 'current' stays on the
      real colorSet for the whole session -- true colors visible while
      painting, no scratch canvas. Native artUserPaintCtx grayscale
      feedback landing on the real colorSet is corrected per-stamp by
      ``ChannelPaintController._flush_dirty``'s merge-write.
    - BW mode (``_preview_active=True``): unchanged from the previous fix
      -- scratch canvas, merge-on-flush, exactly as before.
See ``ChannelPaintController._pin_target`` for the single place that
decides which target is live. The toggle can now be flipped mid-session
in both directions (``enable_preview``/``disable_preview`` re-pin
'current' instead of forcing the artist out of the tool). This needs a
live Maya retest before being trusted -- known confound: production has
also seen a stale-session-cache bug and a dual-instance (fork vs
open-tools) collision bug layered on top of the original bleed (see
memory), so a clean repro needs a fresh scene and a single Slimfast
instance loaded.

Author: DrWeeny
"""

from __future__ import annotations
import re

from typing import List, Optional, Set

from maya import cmds
from dw_maya.dw_paint.protocol import WeightSource, WeightList
from dw_maya.dw_paint.core.mesh_data import MeshDataFactory
from dw_logger import get_logger
import numpy as np
logger = get_logger()

# Name of the temporary colorSet used for B&W preview
_PREVIEW_SET = '_channel_preview_bw'
# artUserPaintCtx context name (singleton) — must match artisan_maya.CTX_ALPHA
_CTX_NAME = 'dwAlphaPaintCtx'

# channel map name -> (polyColorPerVertex flag, MColor component index)
_CHANNELS = {
    'red':   ('r', 0),
    'green': ('g', 1),
    'blue':  ('b', 2),
    'alpha': ('a', 3),
}

# Maya returns MColor(-1,-1,-1,-1) for vertices that were never assigned a
# color — that -1 is an "unset" sentinel, not a stored value (it would
# otherwise leak into weight ranges as a negative minimum, and into sibling
# channels on write). Unset vertices read as 0.0 (empty map). Stored values
# are returned untouched — including genuine negatives / out-of-0-1 data
# (debug or HDR colorSets): getVertexColors(defaultUnsetColor) substitutes
# only truly unassigned vertices, so no clamping happens anywhere.
_UNSET_VALUE = 0.0

# ---------------------------------------------------------------------------
# MEL callback installation
# ---------------------------------------------------------------------------

_MEL_PROCS_INSTALLED = False


def install_mel_procs() -> None:
    """Register the MEL global procedures used by artUserPaintCtx.

    Based on the proven artUserPaintCtx callback pattern.  The initializeCmd
    returns ``-path 1`` so that ``setValueCommand`` receives the full shape
    path, enabling multi-shape support.
    """
    global _MEL_PROCS_INSTALLED

    from maya import mel

    # Determine the correct MEL→Python bridge command.
    try:
        mel.eval('python("1")')
        py = 'python'
    except Exception:
        py = 'python3'

    ctx = _CTX_NAME
    # MEL procs follow the reference pattern exactly:
    # The object is stored in __main__ as the context name itself.
    # MEL procs call python("contextName.method(...)").
    mel_code = f'''
        global proc string {ctx}_init_cmd(string $shape){{
            return {py}("{ctx}.init_cmd('" + $shape + "')");}}
        global proc {ctx}_on_cmd(){{
            {py}("{ctx}.on_cmd()");}}
        global proc {ctx}_off_cmd(){{
            {py}("{ctx}.off_cmd()");}}
        global proc {ctx}_before_stroke_cmd(){{
            {py}("{ctx}.before_stroke_cmd()");}}
        global proc {ctx}_set_value_cmd(int $shape_id, int $v_id, float $value, string $shape_long){{
            {py}("{ctx}.set_value_cmd(" + $shape_id + "," + $v_id + "," + $value + ",'" + $shape_long + "')");}}
        global proc {ctx}_during_stroke_cmd(){{
            {py}("{ctx}.during_stroke_cmd()");}}
        global proc {ctx}_after_stroke_cmd(){{
            {py}("{ctx}.after_stroke_cmd()");}}
        global proc {ctx}_final_cmd(string $shape){{
            {py}("{ctx}.final_cmd('" + $shape + "')");}}
    '''
    mel.eval(mel_code)
    _MEL_PROCS_INSTALLED = True

def get_icon():
    from dw_ressources import get_resource_path
    return get_resource_path("vertex_alpha_icon.png")

# ---------------------------------------------------------------------------
# Representation debug helper
# ---------------------------------------------------------------------------

def check_channel_isolation(mesh: str, color_set: str) -> bool:
    """Warn if *color_set* cannot store R/G/B/A independently.

    A colorSet created with representation ``'A'`` or ``'RGB'`` only holds
    that many floats per vertex -- Maya mirrors the single stored value
    across the missing components on read/display. Painting or previewing
    one channel on such a colorSet then appears to touch all four, which
    looks like a channel-isolation bug in this module but is actually the
    colorSet's storage shape (a leftover from the old alpha-only tool,
    which always created 'A' colorSets). Call this before painting/preview
    to tell the two cases apart.

    Uses the OpenMaya API rather than ``cmds.polyColorSet(representation=True)``
    -- that flag only reports the CURRENT colorSet's representation when
    queried (``query=True`` demotes ``colorSet`` to a boolean), it cannot
    take a colorSet name in query mode.

    Returns:
        True if the colorSet is RGBA (channels are independent), False if
        it is a narrower representation (a warning is logged in that case).
    """
    try:
        import maya.api.OpenMaya as om2

        fn_mesh = MeshDataFactory.get(mesh)._fn_mesh
        rep = fn_mesh.getColorRepresentation(color_set)
        rgba = om2.MFnMesh.kRGBA
    except Exception as e:
        logger.warning(f"Could not query representation of '{color_set}' on '{mesh}': {e}")
        return True  # unknown -- don't false-alarm

    if rep != rgba:
        logger.warning(
            f"ColorSet '{color_set}' on '{mesh}' has representation '{rep}', "
            f"not RGBA -- it cannot store R/G/B/A independently, so painting "
            f"or previewing any single channel will appear on all four. "
            f"This is Maya's storage shape, not a bug in VertexColorSet. "
            f"Recreate the colorSet with representation='RGBA' "
            f"(cmds.polyColorSet(mesh, create=True, colorSet=name, "
            f"representation='RGBA')) to isolate channels."
        )
        return False
    return True

def _set_geometry_draw_dirty(mesh_name: str) -> None:
    """Force the viewport to redraw *mesh_name*'s vertex colors.

    ``MFnMesh.setVertexColors`` writes the color buffer through the raw
    OpenMaya API, which does not mark the mesh dirty for Viewport 2.0 /
    OGS -- so a batch write (numpy smooth, flood, paste) can land in the
    data with the viewport still drawing the stale colors until some
    unrelated event forces a redraw (hence "after refreshing once it never
    happens again"). Marking the geometry draw-dirty here makes OGS pick up
    the new colorSet stream on the next refresh cycle. Interactive artisan
    strokes don't need this -- the tool already forces its own redraws.
    """
    try:
        import maya.api.OpenMayaRender as omr
        # setGeometryDrawDirty wants the shape MObject, not the MDagPath.
        dag = MeshDataFactory.get(mesh_name)._dag
        omr.MRenderer.setGeometryDrawDirty(dag.node())
    except Exception as e:
        logger.debug(f"setGeometryDrawDirty failed on '{mesh_name}': {e}")


def _ensure_scratch_colorset(mesh: str) -> None:
    """Create the internal scratch colorSet (``_PREVIEW_SET``) if missing.

    Doubles as both the B&W preview canvas and the interactive-paint
    scratch buffer that keeps the real colorSet out of 'current' during a
    brush stroke (see ChannelPaintController.on_cmd). Creating it does not
    force the viewport to display it -- that's still controlled separately
    by ``VertexColorSet._preview_active`` / ``displayColors``.
    """
    existing = cmds.polyColorSet(mesh, q=True, allColorSets=True) or []
    if _PREVIEW_SET not in existing:
        cmds.polyColorSet(mesh, create=True, colorSet=_PREVIEW_SET, representation='RGBA')
        MeshDataFactory.get(mesh).refresh()


# ---------------------------------------------------------------------------
# Artisan paint controller — stored in __main__ for MEL access
# ---------------------------------------------------------------------------

class ChannelPaintController:
    """Manages the artisan paint session for one VertexColorSet channel.

    Stored in ``__main__`` under the context name so the MEL callbacks
    can call its methods.  Follows the same pattern as the proven
    GenericPaint reference implementation.

    The channel is captured at construction time (the source's active map);
    the whole session paints that channel only, RGB(A) siblings are preserved.
    """

    def __init__(self, source: 'VertexColorSet') -> None:
        self.source = source
        self.mesh = source.mesh_name
        self.color_set = source.color_set
        self.channel = source.channel
        self._channel_idx = _CHANNELS[self.channel][1]
        self._channel_flag = _CHANNELS[self.channel][0]

        # Read current channel values as our working buffer (numpy array for fast ops)
        self._values = np.array(source.get_weights(), dtype=np.float64)

        self._stamp_hits = {}
        self._dirty_verts = set()
        self._stroke_completed = False
        # Neighbour cache delegated to MeshDataFactory (shared, already built)
        self._neighbour_cache = {}
        self._batch_mode = False
        # Vertex selection mask — None means all vertices are paintable
        self._vtx_mask: Optional[Set[int]] = None
        # Whole-stroke undo tracking: _flush_dirty writes live (raw API, not
        # undoable per-call, needed for viewport feedback during the drag) —
        # one single undo entry covering the whole stroke is pushed instead,
        # from the values snapshotted here at stroke start.
        self._stroke_start_values: Optional[np.ndarray] = None
        self._stroke_dirty_verts: Set[int] = set()
        # Sibling (non-active) channel snapshot of the REAL colorSet, read
        # ONCE per stroke in before_stroke_cmd — see _flush_dirty for why
        # this must never come from re-reading Maya's 'current' mid-stroke.
        self._sibling_snapshot: Optional[np.ndarray] = None

    def _pin_target(self) -> str:
        """Where 'current' should rest right now: scratch in BW mode, real colorSet otherwise.

        2026-07-24 experiment (see vertex_color.py module docstring):
        BW/preview mode keeps the scratch-buffer + merge-on-flush design
        (native grayscale stamp feedback is harmless there since nothing
        reads the scratch set as real data). Direct mode intentionally
        lets 'current' rest on the real colorSet so the artist sees true
        colors while painting, at the cost of Maya's native per-stamp
        feedback landing there too -- ``_flush_dirty`` immediately
        overwrites with the correct merged RGBA right after each stamp, so
        the corruption is expected to be transient/self-correcting rather
        than persistent. This trade was reverted once before (see
        final_cmd's git history) but that revert was bundled with the
        get_weights()-touches-current bug in the same commit -- with that
        bug now fixed independently, this is worth retesting in isolation.
        """
        return _PREVIEW_SET if self.source._preview_active else self.color_set

    def on_cmd(self) -> None:
        """Context activated — refresh channel cache and pin 'current' to the right target.

        ``artUserPaintCtx`` paints its own grayscale visual feedback
        straight into whatever colorSet is 'current' at the moment of each
        stamp -- that is Maya's native per-vertex paint behavior, not
        something ``setValueCommand`` controls or can suppress. In BW mode
        that native write must never land on the real colorSet (it would
        clobber sibling channels before our own read-modify-write can
        correct it), so 'current' stays pinned to the dedicated scratch
        colorSet for the whole session. In direct mode 'current' is the
        real colorSet on purpose -- see ``_pin_target``.
        """
        self._values = np.array(self.source.get_weights(), dtype=np.float64)
        target = self._pin_target()
        if target == _PREVIEW_SET:
            _ensure_scratch_colorset(self.mesh)
        MeshDataFactory.get(self.mesh)._fn_mesh.setCurrentColorSetName(target)

    def off_cmd(self) -> None:
        """Context deactivated -- safe to restore 'current' to real colors now.

        No more stamps can land once the tool is switched away from, so
        this is the only point (besides the brief controlled window inside
        a flush) where 'current' may rest on the real colorSet -- in
        direct mode it already does (see ``_pin_target``).
        """
        try:
            MeshDataFactory.get(self.mesh)._fn_mesh.setCurrentColorSetName(self._pin_target())
        except Exception as e:
            logger.warning(f"Could not restore colorSet on tool deactivation: {e}")

    def before_stroke_cmd(self) -> None:
        """Click — before first stamp projection."""
        self._stamp_hits = {}
        self._stroke_completed = False
        self._vtx_mask = self._read_selection_mask()
        self._stroke_start_values = self._values.copy()
        self._stroke_dirty_verts = set()
        self._sibling_snapshot = self._read_sibling_snapshot()

    def _read_sibling_snapshot(self) -> 'np.ndarray':
        """Read the real colorSet's full RGBA once, before any stamp can taint it.

        ``getVertexColors`` takes the colorSet name directly -- it never
        needs 'current' pointed at it to read. 'current' is left untouched
        here on purpose: it appears Maya's artUserPaintCtx native paint
        feedback re-snapshots its target any time 'current' rests on the
        real colorSet while the tool is selected, not only at tool
        activation -- switching 'current' to real just to do a read (even
        briefly, even mid-session) re-arms it. Never switch 'current' for a
        read; only the unavoidable ``setVertexColors`` writes may need it
        (that API has no colorSet-name parameter).
        """
        import maya.api.OpenMaya as om2

        fn_mesh = MeshDataFactory.get(self.mesh)._fn_mesh
        unset = om2.MColor((_UNSET_VALUE,) * 4)
        colors = fn_mesh.getVertexColors(self.color_set, unset)
        return np.array([[c.r, c.g, c.b, c.a] for c in colors], dtype=np.float64)

    def _read_selection_mask(self) -> Optional[Set[int]]:
        """Read current vertex selection on this mesh.

        Returns a set of vertex indices if a component selection exists,
        or None if nothing is selected (all vertices are paintable).
        """
        sel_all = cmds.ls(sl=True, fl=True) or []
        vtx_components = [s for s in sel_all if '.' in s]
        if not vtx_components:
            return None
        vtx = cmds.polyListComponentConversion(vtx_components, toVertex=True)
        vtx = cmds.ls(vtx, fl=True) or []
        if not vtx:
            return None
        # Filter to vertices belonging to this mesh (namespace-safe)
        mesh_base = self.mesh.split('|')[-1]
        indices: Set[int] = set()
        for v in vtx:
            if mesh_base in v:
                m = re.search(r'\[(\d+)\]', v)
                if m:
                    indices.add(int(m.group(1)))
        return indices if indices else None

    def init_cmd(self, shape: str) -> str:
        """First stamp hits a shape — must return '-path 1' for artisan."""
        return '-path 1'

    def set_value_cmd(self, shape_id: int, v_id: int,
                      value: float, shape_long: str) -> None:
        """Per vertex per stamp — just accumulate, don't write to Maya yet."""
        self._stamp_hits[v_id] = value

    def during_stroke_cmd(self) -> None:
        """After each stamp during a drag — apply and flush dirty verts."""
        self._apply_stamp()
        self._flush_dirty()

    def after_stroke_cmd(self) -> None:
        """Click/drag release — mark stroke as complete for undo."""
        self._stroke_completed = True

    def final_cmd(self, shape: str = '') -> None:
        """Called on release — apply remaining stamp, flush, commit undo.

        In BW mode, pins 'current' back to the scratch colorSet even
        though no more stamps can land until the next
        ``before_stroke_cmd`` -- the tool is still active/selected at this
        point, and Maya's native artUserPaintCtx feedback appears to
        re-snapshot its paint target at the START of each new stroke (not
        just once at tool activation), so real colors must stay hidden
        from 'current' for the whole BW session (see ``_pin_target``).

        In direct mode 'current' already IS the real colorSet (see
        ``_pin_target``) -- true colors are visible between strokes by
        design, that's the point of direct mode.
        """
        self._apply_stamp()
        self._flush_dirty()
        self._commit_stroke_undo()

        target = self._pin_target()
        if target == _PREVIEW_SET:
            _ensure_scratch_colorset(self.mesh)
        MeshDataFactory.get(self.mesh)._fn_mesh.setCurrentColorSetName(target)

    def _commit_stroke_undo(self) -> None:
        """Make the just-finished stroke undoable with a single Ctrl+Z.

        ``_flush_dirty`` already wrote every stamp straight to Maya via the
        raw OpenMaya API for live feedback -- those writes never touch the
        undo queue. Two things conspire against a naive fix:

        - A command run straight from this callback (``finalizeCmd``) nests
          inside the artisan tool's own executing command and never becomes
          an independently-undoable entry.
        - The internal ``dwPyUndo`` MPxCommand bridge, whether called
          directly or via ``evalDeferred``, did not produce a working undo
          entry here (confirmed live: no ``dwPyUndo`` ever landed on the
          queue, and an ``evalDeferred`` python-callable wrapper journaled
          only itself, not the raw-API work inside it).

        So this instead defers a callable to idle (out of the tool
        callback) that (1) silently rewinds the touched verts to their
        pre-stroke value via raw API, then (2) rewrites them to the final
        value through native ``cmds.polyColorPerVertex`` -- a genuinely
        undoable command. The whole thing is bracketed in one undo chunk,
        so undoing it restores the pre-stroke (rewound) state and redoing
        replays the final. In B&W mode the scratch preview set is committed
        the same way (rewind + undoable write) so Ctrl+Z reverts what the
        viewport actually shows.
        """
        if not self._stroke_dirty_verts or self._stroke_start_values is None:
            return

        source = self.source
        mesh = self.mesh
        color_set = self.color_set
        idx = self._channel_idx
        flag = self._channel_flag
        dirty = list(self._stroke_dirty_verts)
        final_values = self._values.copy()
        start_values = self._stroke_start_values.copy()
        preview = bool(getattr(source, '_preview_active', False))

        self._stroke_dirty_verts = set()
        self._stroke_start_values = None

        def _commit():
            try:
                import maya.api.OpenMaya as om2
                from collections import defaultdict
                from dw_maya.dw_maya_utils.dw_maya_components import create_maya_ranges

                fn_mesh = MeshDataFactory.get(mesh)._fn_mesh
                unset = om2.MColor((_UNSET_VALUE,) * 4)

                def _paint_cmds(values, is_scratch):
                    # One undoable polyColorPerVertex per distinct value,
                    # ranges compressed. Grouping keeps the command count low
                    # even for a big stroke.
                    groups = defaultdict(list)
                    for i in dirty:
                        groups[round(float(values[i]), 5)].append(i)
                    for val, ids in groups.items():
                        for rng in create_maya_ranges(ids):
                            if is_scratch:
                                cmds.polyColorPerVertex(
                                    f'{mesh}.vtx[{rng}]',
                                    r=val, g=val, b=val, a=1.0,
                                    colorDisplayOption=True, representation=4,
                                )
                            else:
                                cmds.polyColorPerVertex(
                                    f'{mesh}.vtx[{rng}]',
                                    colorDisplayOption=True, representation=4,
                                    **{flag: val},
                                )

                cmds.undoInfo(openChunk=True)
                try:
                    # -- real colorSet ---------------------------------
                    base = fn_mesh.getVertexColors(color_set, unset)
                    rewind = om2.MColorArray()
                    for i in dirty:
                        c = base[i] if i < len(base) else unset
                        rgba = [c.r, c.g, c.b, c.a]
                        rgba[idx] = float(start_values[i])
                        rewind.append(om2.MColor(rgba))
                    fn_mesh.setCurrentColorSetName(color_set)
                    fn_mesh.setVertexColors(rewind, dirty)  # silent rewind

                    cmds.polyColorSet(mesh, currentColorSet=True, colorSet=color_set)
                    _paint_cmds(final_values, is_scratch=False)  # undoable

                    # -- B&W scratch set (what the viewport shows) -----
                    if preview:
                        _ensure_scratch_colorset(mesh)
                        srewind = om2.MColorArray()
                        for i in dirty:
                            v = float(start_values[i])
                            srewind.append(om2.MColor((v, v, v, 1.0)))
                        fn_mesh.setCurrentColorSetName(_PREVIEW_SET)
                        fn_mesh.setVertexColors(srewind, dirty)  # silent rewind

                        cmds.polyColorSet(mesh, currentColorSet=True, colorSet=_PREVIEW_SET)
                        _paint_cmds(final_values, is_scratch=True)  # undoable
                        # leave 'current' on scratch -- BW-mode invariant
                finally:
                    cmds.undoInfo(closeChunk=True)

                _set_geometry_draw_dirty(mesh)
            except Exception as exc:
                logger.warning(f"Stroke undo commit failed: {exc}")

        # Run synchronously (NOT deferred): this executes while the artisan's
        # own per-stroke undo chunk is still open, so our polyColorPerVertex
        # writes nest into that single entry -- one clean Ctrl+Z per stroke.
        # Deferring to idle instead landed our entry AFTER the tool's
        # (harmless, no-op) ``artUserSetValues`` entry, so every second undo
        # hit that no-op and only one stroke of two appeared to revert.
        _commit()

    def _apply_stamp(self) -> None:
        """Apply accumulated stamp hits to the in-memory channel buffer."""
        if not self._stamp_hits:
            return

        # Detect current operation mode
        oper = 'additive'
        try:
            oper = cmds.artUserPaintCtx(_CTX_NAME, q=True, selectedattroper=True)
        except Exception:
            pass

        if oper == 'smooth':
            self._apply_smooth()
            return

        artisan_value = 1.0
        try:
            artisan_value = cmds.artUserPaintCtx(_CTX_NAME, q=True, value=True)
        except Exception:
            pass

        for v_id, opacity in self._stamp_hits.items():
            if self._vtx_mask is not None and v_id not in self._vtx_mask:
                continue
            if 0 <= v_id < len(self._values):
                old = self._values[v_id]
                effective_opacity = 1.0 if (abs(artisan_value) < 1e-6 and opacity == 0.0) else opacity
                # No 0-1 clamp: colorSets can hold out-of-range data
                # (negative debug values, HDR) and painting must not eat it.
                self._values[v_id] = old + (artisan_value - old) * effective_opacity
                self._dirty_verts.add(v_id)

        self._stamp_hits.clear()

    def _apply_smooth(self) -> None:
        """Smooth the channel values for hit vertices using neighbour averaging."""
        if not self._neighbour_cache:
            self._build_neighbour_cache()

        opacity = 1.0
        try:
            opacity = cmds.artUserPaintCtx(_CTX_NAME, q=True, opacity=True)
        except Exception:
            pass

        hit_verts = list(self._stamp_hits.keys())
        # numpy copy is faster than list() for the snapshot
        snapshot = self._values.copy()

        for v_id in hit_verts:
            if self._vtx_mask is not None and v_id not in self._vtx_mask:
                continue
            if 0 <= v_id < len(self._values):
                neighbours = self._neighbour_cache.get(v_id, [])
                avg = float(np.mean(snapshot[neighbours])) if neighbours else float(snapshot[v_id])
                old = float(snapshot[v_id])
                # No 0-1 clamp — see _apply_stamp
                self._values[v_id] = old + (avg - old) * opacity
                self._dirty_verts.add(v_id)

        self._stamp_hits.clear()

    def _build_neighbour_cache(self) -> None:
        """Delegate neighbour map to MeshDataFactory (shared, cached across sessions)."""
        md = MeshDataFactory.get(self.mesh)
        cached = md.neighbors
        if cached:
            self._neighbour_cache = cached
            return

        # MeshData cache was empty (mesh not in cache yet) — build via API directly
        # and let MeshDataFactory hold it for future calls.
        import maya.api.OpenMaya as om2
        try:
            it_vtx = om2.MItMeshVertex(md._dag)
            cache = {}
            while not it_vtx.isDone():
                cache[it_vtx.index()] = list(it_vtx.getConnectedVertices())
                it_vtx.next()
            # Store back so MeshData.neighbors is populated
            md._neighbors = cache
            self._neighbour_cache = cache
        except Exception as e:
            logger.warning(f"API neighbour cache failed: {e}. Falling back to cmds.")
            n = len(self._values)
            mesh = self.mesh
            cache = {}
            for i in range(n):
                edges = cmds.polyListComponentConversion(f'{mesh}.vtx[{i}]', toEdge=True) or []
                edges = cmds.ls(edges, fl=True) or []
                neighbours = set()
                for edge in edges:
                    verts = cmds.polyListComponentConversion(edge, toVertex=True) or []
                    for v in cmds.ls(verts, fl=True) or []:
                        vid = int(v.split('[')[-1].rstrip(']'))
                        if vid != i:
                            neighbours.add(vid)
                cache[i] = list(neighbours)
            md._neighbors = cache
            self._neighbour_cache = cache

    def _flush_dirty(self) -> None:
        """Write only the changed vertices to Maya (incremental update).

        BW mode: 'current' is only ever pointed at the real colorSet for
        the brief moment of the write below, then immediately pinned back
        to the scratch/preview set (see on_cmd) so no native
        artUserPaintCtx stamp can land on the real data between flushes.

        Direct mode (see ``_pin_target``): 'current' already IS the real
        colorSet and stays there -- no scratch involved, no pin-back. Any
        native grayscale feedback Maya wrote into the sibling channels for
        this stamp is overwritten right here by the merged RGBA write,
        same as BW mode's correction, just without a scratch buffer to
        hide behind in between.

        Sibling channels come from the once-per-stroke snapshot
        (``_read_sibling_snapshot``), never from re-reading Maya's
        'current' mid-stroke -- that 'current' can be the scratch set's
        uniform grayscale, or real data Maya's own paint feedback already
        bled into, depending on timing.
        """
        if not self._dirty_verts:
            return

        if self._batch_mode:
            self._dirty_verts.clear()
            return

        mesh = self.mesh
        color_set = self.color_set
        dirty_list = list(self._dirty_verts)
        idx = self._channel_idx
        self._stroke_dirty_verts.update(dirty_list)
        bw_mode = self.source._preview_active

        try:
            import maya.api.OpenMaya as om2
            fn_mesh = MeshDataFactory.get(mesh)._fn_mesh

            new_colors = om2.MColorArray()
            for i in dirty_list:
                if self._sibling_snapshot is not None and i < len(self._sibling_snapshot):
                    rgba = list(self._sibling_snapshot[i])
                else:
                    rgba = [_UNSET_VALUE] * 4
                rgba[idx] = float(self._values[i])
                new_colors.append(om2.MColor(rgba))
                # Keep the snapshot in sync so a later flush in this same
                # stroke builds on this write, not stale pre-stroke data.
                if self._sibling_snapshot is not None and i < len(self._sibling_snapshot):
                    self._sibling_snapshot[i][idx] = float(self._values[i])

            fn_mesh.setCurrentColorSetName(color_set)
            fn_mesh.setVertexColors(new_colors, dirty_list)

            if bw_mode:
                fn_mesh.setCurrentColorSetName(_PREVIEW_SET)

                # Live grayscale feedback on the scratch/preview colorSet --
                # this is what the viewport shows during the drag (if
                # displayColors is on), independent of the preview toggle.
                preview_colors = om2.MColorArray()
                for i in dirty_list:
                    v = float(self._values[i])
                    preview_colors.append(om2.MColor((v, v, v, 1.0)))
                fn_mesh.setVertexColors(preview_colors, dirty_list)
            # else: direct mode -- 'current' stays on color_set, real RGBA
            # is already what just got written, nothing more to show.

        except Exception as e:
            logger.warning(f"API flush failed, falling back to cmds. Error: {e}")

            cmds.polyColorSet(mesh, currentColorSet=True, colorSet=color_set)
            flag = self._channel_flag
            for i in dirty_list:
                cmds.polyColorPerVertex(
                    f'{mesh}.vtx[{i}]',
                    colorDisplayOption=True, representation=4,
                    **{flag: float(self._values[i])},
                )

            if bw_mode:
                cmds.polyColorSet(mesh, currentColorSet=True, colorSet=_PREVIEW_SET)
                for i in dirty_list:
                    v = float(self._values[i])
                    cmds.polyColorPerVertex(
                        f'{mesh}.vtx[{i}]',
                        r=v, g=v, b=v, a=1.0,
                        colorDisplayOption=True, representation=4,
                    )

        self._dirty_verts.clear()


def _has_active_paint_session(mesh: str) -> bool:
    """True if the paint tool is genuinely selected right now, for *mesh*.

    Checks BOTH that a ``ChannelPaintController`` exists for this mesh AND
    that Maya's current tool context really is ours -- the controller
    object itself is never cleared (``off_cmd`` is deliberately a no-op,
    so channel-switch retargeting still works across separate paint
    sessions), so checking only its existence would keep reporting a
    session as "active" long after the user switched to the Select tool,
    forcing every later channel switch to pin 'current' onto the scratch/
    grayscale colorSet for no reason -- visually stuck in B&W with no
    stamps ever landing to justify it.

    Used to keep :meth:`VertexColorSet.disable_preview` from deleting the
    scratch colorSet out from under a genuinely in-progress interactive
    paint session -- it doubles as that session's scratch canvas (see
    ``ChannelPaintController.on_cmd``); deleting it mid-session would break
    the invariant that 'current' never idles on the real colorSet between
    stamps.
    """
    import __main__

    controller = __main__.__dict__.get(_CTX_NAME)
    if not (isinstance(controller, ChannelPaintController) and controller.mesh == mesh):
        return False
    try:
        return cmds.currentCtx() == _CTX_NAME
    except Exception:
        return False


class VertexColorSet(WeightSource):
    """Treat each vertex-color channel of a colorSet as a per-vertex weight map.

    Exposes four maps — ``alpha`` (default), ``red``, ``green``, ``blue`` —
    selected via :meth:`use_map`.  Writing one channel never touches the
    other three.

    Args:
        mesh_name:  Transform name of the mesh.
        color_set:  Name of the colorSet to operate on.
                    Defaults to the mesh's current colorSet.

    Example::

        node = VertexColorSet('pSphere1')
        node.get_weights()                  # alpha per vertex (default map)
        node.use_map('red').get_weights()   # red per vertex
        node.set_weights([1.0] * node.vtx_count)
    """

    def __init__(self, mesh_name: str, color_set: str = '') -> None:
        if not color_set:
            current = cmds.polyColorSet(mesh_name, q=True, currentColorSet=True) or []
            color_set = current[0] if current else 'colorSet1'
        # node_name is synthetic — there is no Maya node, we use the colorSet name
        super().__init__(f'{mesh_name}@{color_set}', mesh_name)
        self._color_set = color_set
        self._preview_active = False
        self._batch_mode = False
        # Default to alpha so pre-RGB scripts keep working without use_map()
        self._current_map = 'alpha'

    # ------------------------------------------------------------------
    # Identity helpers
    # ------------------------------------------------------------------

    @property
    def color_set(self) -> str:
        """The colorSet this source operates on."""
        return self._color_set

    @property
    def channel(self) -> str:
        """The active channel name (``red``/``green``/``blue``/``alpha``)."""
        return self._require_map()

    @property
    def vtx_count(self) -> int:
        """Vertex count via MeshDataFactory (cached, avoids cmds.polyEvaluate every call)."""
        return MeshDataFactory.get(self._mesh_name).vertex_count or cmds.polyEvaluate(self._mesh_name, vertex=True)


    # ------------------------------------------------------------------
    # WeightSource abstract interface
    # ------------------------------------------------------------------

    def available_maps(self) -> List[str]:
        """One map per channel — alpha first (the historical default)."""
        return ['alpha', 'red', 'green', 'blue']

    def get_artisan_name(self) -> str:
        """This source paints through ``artUserPaintCtx``, not ``artAttrContext``."""
        return _CTX_NAME

    def use_map(self, map_name: str) -> 'VertexColorSet':
        """Activate a channel, retargeting any live brush/preview session to match.

        ``ChannelPaintController`` captures its channel once, at
        :meth:`_paint` time, and lives on as a singleton in ``__main__`` for
        MEL callback access — switching the channel radio while a brush
        session is already active would otherwise leave the brush silently
        painting the OLD channel while reads/preview correctly follow the
        new one.

        Refreshing the B&W preview here (not only from the UI layer) means
        any caller that switches channel -- the Slimfast radio, a script,
        DynEval's paint handoff -- gets a preview that follows the active
        channel, not just the one UI code path that happened to call
        enable_preview() again.
        """
        super().use_map(map_name)
        self._sync_paint_controller()
        if self._preview_active:
            # Refresh the scratch canvas to the new channel -- in direct
            # mode there's no scratch canvas being shown, so nothing to do
            # (the real colorSet already reflects the new channel's data
            # via _sync_paint_controller).
            self.enable_preview()
        return self

    def _sync_paint_controller(self) -> None:
        """Retarget the live paint controller (if any, and if it's ours) to this channel."""
        import __main__

        controller = __main__.__dict__.get(_CTX_NAME)
        if not isinstance(controller, ChannelPaintController):
            return
        src = controller.source
        if not (isinstance(src, VertexColorSet)
                and src.mesh_name == self.mesh_name
                and src.color_set == self.color_set):
            return
        if controller.channel == self.channel:
            return

        controller.source = self
        controller.channel = self.channel
        controller._channel_idx = _CHANNELS[self.channel][1]
        controller._channel_flag = _CHANNELS[self.channel][0]
        controller._values = np.array(self.get_weights(), dtype=np.float64)
        # get_weights()'s API path doesn't touch 'current' at all -- but
        # re-assert the right pin anyway (BW scratch or real colorSet, see
        # _pin_target) since the controller singleton outlives its tool
        # session (off_cmd never clears it), so a stale controller can be
        # retargeted here without on_cmd having run for THIS mesh (e.g.
        # mesh deleted/recreated under the same name) -- the scratch
        # colorSet is not guaranteed to exist if BW mode needs it.
        target = controller._pin_target()
        if target == _PREVIEW_SET:
            _ensure_scratch_colorset(self.mesh_name)
        MeshDataFactory.get(self.mesh_name)._fn_mesh.setCurrentColorSetName(target)
        # Any in-flight stroke/undo state belongs to the OLD channel.
        controller._stamp_hits = {}
        controller._dirty_verts = set()
        controller._stroke_dirty_verts = set()
        controller._stroke_start_values = None
        controller._sibling_snapshot = None
        logger.info(f"Paint brush retargeted to channel '{self.channel}'.")

    def _resolve_attr(self, map_name: str) -> str:
        # Not used — we override get/set directly.
        return ''

    def _paint(self) -> None:
        """Open an interactive artisan brush that paints only the active channel.

        Uses ``artUserPaintCtx`` with the proven callback pattern:
        initializeCmd returns ``-path 1``, setValueCommand receives per-vertex
        opacity, and finalizeCmd flushes changes to the real colorSet.
        """
        check_channel_isolation(self._mesh_name, self._color_set)

        # Painting is ALWAYS B&W-locked (reverts the 2026-07-24 direct-mode
        # experiment, confirmed unsafe in production): force the grayscale
        # scratch canvas on so artUserPaintCtx's native per-stamp feedback
        # lands on the scratch set, never bleeding the real colorSet's
        # sibling channels. The toggle stays locked for the whole session --
        # see preview_locked / disable_preview.
        if not self._preview_active:
            self.enable_preview()

        import __main__

        # 1. Install MEL procs
        install_mel_procs()

        # 2. Create controller and store in __main__ under context name
        controller = ChannelPaintController(self)
        __main__.__dict__[_CTX_NAME] = controller

        # 3a. Mark the colorSet being painted as the mesh's current one --
        # Slimfast lets a mesh with several colorSets pick which one to
        # work on, and that choice should be reflected outside our own
        # bookkeeping too (Color Set Editor, other tools/scripts reading
        # currentColorSet). This must happen BEFORE 3b below, not instead
        # of it -- see that comment for why.
        cmds.polyColorSet(self._mesh_name, currentColorSet=True,
                          colorSet=self._color_set)

        # 3b. Then immediately pin 'current' to the right target BEFORE the
        # tool activates. artUserPaintCtx's native per-stamp visual
        # feedback appears to target whatever colorSet is 'current' at
        # activation time (cmds.setToolTo below), not whatever 'current'
        # is live during the stroke -- on_cmd (toolOnProc) re-pinning
        # AFTER activation was too late for the scratch case, so pin here
        # too. In BW mode that target is the scratch colorSet (never the
        # real one); in direct mode it's the real colorSet itself (see
        # _pin_target / module docstring on the 2026-07-24 direct-mode
        # experiment).
        if self._preview_active:
            _ensure_scratch_colorset(self._mesh_name)
            cmds.polyColorSet(self._mesh_name, currentColorSet=True,
                              colorSet=_PREVIEW_SET)
        else:
            cmds.polyColorSet(self._mesh_name, currentColorSet=True,
                              colorSet=self._color_set)

        # 4. Create context if it doesn't exist
        context_existed = cmds.artUserPaintCtx(_CTX_NAME, query=True, exists=True)
        if not context_existed:
            cmds.artUserPaintCtx(_CTX_NAME)

        # 5. Configure the context with all callbacks. value/opacity/radius
        # are only seeded on first creation -- re-editing them on every
        # Paint click would reset the artist's last-used brush value and
        # radius each time they re-enter the tool, which is exactly the
        # annoyance this guards against.
        edit_kwargs = dict(
            edit=True,
            fullpaths=True,
            accopacity=False,
            stampProfile='solid',
            selectedattroper='absolute',
            wst='userPaint',
            image1=get_icon(),
            initializeCmd=f'{_CTX_NAME}_init_cmd',
            toolOnProc=f'{_CTX_NAME}_on_cmd',
            toolOffProc=f'{_CTX_NAME}_off_cmd',
            beforeStrokeCmd=f'{_CTX_NAME}_before_stroke_cmd',
            setValueCommand=f'{_CTX_NAME}_set_value_cmd',
            duringStrokeCmd=f'{_CTX_NAME}_during_stroke_cmd',
            afterStrokeCmd=f'{_CTX_NAME}_after_stroke_cmd',
            finalizeCmd=f'{_CTX_NAME}_final_cmd',
        )
        if not context_existed:
            edit_kwargs.update(value=0, opacity=1.0, radius=5)
        cmds.artUserPaintCtx(_CTX_NAME, **edit_kwargs)

        # 6. Select the mesh and activate the context
        cmds.select(self._mesh_name, replace=True)
        cmds.setToolTo(_CTX_NAME)

        logger.info(f"Paint brush active on '{self._color_set}' channel '{self.channel}'.")

    # ------------------------------------------------------------------
    # get / set weights — active channel only
    # ------------------------------------------------------------------

    def get_weights(self) -> WeightList:
        """Read the active channel's per-vertex values from the colorSet.

        Unset vertices (Maya's -1 sentinel) read as ``_UNSET_VALUE`` (0.0).
        """
        n = self.vtx_count
        flag, idx = _CHANNELS[self.channel]
        values = None

        try:
            import maya.api.OpenMaya as om2
            fn_mesh = MeshDataFactory.get(self._mesh_name)._fn_mesh
            # getVertexColors takes the colorSet name directly -- 'current'
            # is deliberately left untouched here. Switching it to the real
            # colorSet just to read (even briefly) appears to re-arm Maya's
            # native artUserPaintCtx paint feedback onto the real colorSet
            # any time it happens while the paint tool is selected, not
            # only at tool activation -- this was happening on every plain
            # channel switch (which calls get_weights internally) even
            # without ever starting a stroke.
            colors = fn_mesh.getVertexColors(self._color_set,
                                             om2.MColor((_UNSET_VALUE,) * 4))
            if len(colors) == n:
                values = [c[idx] for c in colors]
        except Exception as e:
            logger.warning(f"API get_weights failed: {e}. Falling back to cmds.")

        if values is None:
            # cmds.polyColorPerVertex has no colorSet-name parameter -- this
            # fallback path is the one place a 'current' switch is still
            # unavoidable, and only runs if the API path above failed.
            cmds.polyColorSet(self._mesh_name, currentColorSet=True, colorSet=self._color_set)
            try:
                raw = cmds.polyColorPerVertex(
                    f'{self._mesh_name}.vtx[0:{n - 1}]',
                    query=True, colorDisplayOption=True,
                    **{flag: True}
                ) or []
                if len(raw) == n:
                    values = [float(v) for v in raw]
                elif raw:
                    values = self._face_vertex_to_vertex(raw, n)
                # No sentinel mapping here: cmds cannot tell an unset vertex
                # from a stored -1, and stored negatives must be preserved
                # (the API path above is the primary one and does
                # distinguish them).
            except Exception as e:
                logger.warning(f"get_weights '{self.channel}' failed: {e}")

            if values is None:
                values = [_UNSET_VALUE] * n

            # Only the cmds fallback above touches 'current' -- restore it
            # to the scratch set only in BW mode. In direct mode 'current'
            # belongs on the real colorSet (see ChannelPaintController._pin_target),
            # which is exactly where this fallback just left it -- nothing
            # to restore.
            if self._preview_active:
                try:
                    MeshDataFactory.get(self._mesh_name)._fn_mesh.setCurrentColorSetName(_PREVIEW_SET)
                except Exception:
                    cmds.polyColorSet(self._mesh_name, currentColorSet=True, colorSet=_PREVIEW_SET)

        return values

    def set_weights(self, weights: WeightList, **kwargs) -> None:
        """Write the active channel per vertex, leaving the other channels untouched.

        Args:
            weights: One float per vertex.
            **kwargs:
                id_group (bool): If True, group identical weight values to optimize cmds calls.
                maya_api (bool): If True, use OpenMaya API for best performance (default).
                decimals (int): When using id_group, round weights to this many decimals to improve grouping.

        Raises:
            ValueError: If length does not match vtx_count.
        """
        id_group = kwargs.get('id_group', False)
        maya_api = kwargs.get('maya_api', True)
        decimals = kwargs.get('decimals', 3)

        n = self.vtx_count
        if len(weights) != n:
            raise ValueError(
                f"Weight count {len(weights)} != vertex count {n} "
                f"on '{self.node_name}'"
            )

        flag = _CHANNELS[self.channel][0]

        # Batch write: use OpenMaya MFnMesh for speed when available. No
        # 'current' switch here -- _set_weights_api reads by colorSet name
        # and only touches 'current' for its own unavoidable write. See
        # _read_sibling_snapshot for why switching 'current' to the real
        # colorSet outside a tightly-scoped write is risky mid-session.
        try:
            if not maya_api:
                raise RuntimeError("maya_api is False, falling back to cmds.")
            self._set_weights_api(weights)
        except Exception as e:
            if maya_api:
                logger.warning(f"OpenMaya API failed, falling back to cmds. Error: {e}")

            # cmds.polyColorPerVertex has no colorSet-name parameter --
            # this fallback path is the one place a 'current' switch is
            # unavoidable, and only runs if the API path above failed.
            cmds.polyColorSet(self._mesh_name, currentColorSet=True,
                              colorSet=self._color_set)

            # Fallback to cmds per-vertex
            if id_group:
                from dw_maya.dw_maya_utils.dw_maya_components import create_maya_ranges
                from collections import defaultdict

                weight_groups = defaultdict(list)
                for i, w in enumerate(weights):
                    weight_groups[round(w, decimals)].append(i)

                for w_val, indices in weight_groups.items():
                    ranges = create_maya_ranges(indices)
                    for r in ranges:
                        cmds.polyColorPerVertex(
                            f'{self._mesh_name}.vtx[{r}]',
                            colorDisplayOption=True,
                            representation=4,
                            **{flag: float(w_val)},
                        )
            else:
                for i, w in enumerate(weights):
                    cmds.polyColorPerVertex(
                        f'{self._mesh_name}.vtx[{i}]',
                        colorDisplayOption=True,
                        representation=4,
                        **{flag: float(w)},
                    )

            # Restore 'current' to scratch only in BW mode -- only this
            # fallback path touches 'current'. In direct mode it's already
            # sitting on the real colorSet, which is where it belongs.
            if self._preview_active:
                try:
                    MeshDataFactory.get(self._mesh_name)._fn_mesh.setCurrentColorSetName(_PREVIEW_SET)
                except Exception:
                    cmds.polyColorSet(self._mesh_name, currentColorSet=True, colorSet=_PREVIEW_SET)

        # Refresh preview if active (skip during batch mode)
        if self._preview_active and not self._batch_mode:
            self._update_preview(weights)

        # Sync artisan controller if active
        self._sync_artisan_controller(weights)

        # Raw-API writes above don't dirty OGS on their own -- force the
        # viewport to pick up the new colors (numpy smooth/flood/paste).
        _set_geometry_draw_dirty(self._mesh_name)

    def _set_weights_api(self, weights: WeightList) -> None:
        """Write the active channel using OpenMaya API for better performance.

        ``MFnMesh.setVertexColors`` is a raw API call — it never registers
        with Maya's undo queue on its own, unlike ``cmds.polyColorPerVertex``.
        Routed through :func:`push_undo` so Ctrl+Z still works.
        """
        import maya.api.OpenMaya as om2
        from dw_maya.dw_decorators import push_undo

        fn_mesh = MeshDataFactory.get(self._mesh_name)._fn_mesh
        color_set = self._color_set
        idx = _CHANNELS[self.channel][1]
        unset = om2.MColor((_UNSET_VALUE,) * 4)
        try:
            # getVertexColors takes the colorSet name directly -- no
            # 'current' switch needed for this read (see
            # _read_sibling_snapshot for why that matters).
            colors = fn_mesh.getVertexColors(color_set, unset)
        except Exception:
            raise RuntimeError("No existing color data — fallback to cmds")

        n = len(weights)
        vertex_list = list(range(n))
        old_colors = om2.MColorArray()
        new_colors = om2.MColorArray()
        for i in range(n):
            c = colors[i] if i < len(colors) else unset
            old_colors.append(om2.MColor((c.r, c.g, c.b, c.a)))
            rgba = [c.r, c.g, c.b, c.a]
            rgba[idx] = float(weights[i])
            new_colors.append(om2.MColor(rgba))

        # Write immediately — correctness must never depend on the undo
        # bridge. push_undo() is registered separately as a best-effort
        # add-on; if it misbehaves, only undoability is affected.
        # setCurrentColorSetName (API) rather than cmds.polyColorSet keeps
        # the "current colorset" state synchronous with this same fn_mesh.
        # This one touch of 'current' onto the real colorSet is unavoidable
        # (setVertexColors has no colorSet-name parameter) -- restore it to
        # scratch right after only in BW mode, same reasoning as
        # _read_sibling_snapshot. In direct mode 'current' belongs on the
        # real colorSet anyway, nothing to restore.
        fn_mesh.setCurrentColorSetName(color_set)
        fn_mesh.setVertexColors(new_colors, vertex_list)
        if self._preview_active:
            _ensure_scratch_colorset(self._mesh_name)
            fn_mesh.setCurrentColorSetName(_PREVIEW_SET)

        source = self
        mesh_name = self._mesh_name

        def _refresh_scratch(color_arr):
            # In B&W mode the viewport shows the scratch preview, not the
            # real colorSet -- so undo/redo of a batch write (smooth/flood/
            # paste) must also repaint the scratch grayscale, or the change
            # is invisible. Read the LIVE preview flag so a mid-op mode flip
            # is respected. 'current' is left on scratch afterwards (BW
            # invariant); direct mode skips this and leaves 'current' on real.
            if not getattr(source, '_preview_active', False):
                return
            try:
                _ensure_scratch_colorset(mesh_name)
                pv = om2.MColorArray()
                for c in color_arr:
                    v = [c.r, c.g, c.b, c.a][idx]
                    pv.append(om2.MColor((v, v, v, 1.0)))
                fn_mesh.setCurrentColorSetName(_PREVIEW_SET)
                fn_mesh.setVertexColors(pv, vertex_list)
            except Exception as exc:
                logger.debug(f"undo/redo preview refresh failed: {exc}")

        def _redo():
            fn_mesh.setCurrentColorSetName(color_set)
            fn_mesh.setVertexColors(new_colors, vertex_list)
            _refresh_scratch(new_colors)
            _set_geometry_draw_dirty(mesh_name)

        def _undo():
            fn_mesh.setCurrentColorSetName(color_set)
            fn_mesh.setVertexColors(old_colors, vertex_list)
            _refresh_scratch(old_colors)
            _set_geometry_draw_dirty(mesh_name)

        try:
            push_undo(_redo, _undo)
        except Exception as e:
            logger.warning(f"Could not register undo for vertex color write: {e}")

    def _sync_artisan_controller(self, weights: WeightList) -> None:
        """Update the artisan paint controller cache if it targets this channel."""
        import __main__
        controller = __main__.__dict__.get(_CTX_NAME)
        if controller and isinstance(controller, ChannelPaintController):
            if controller.source is self and controller.channel == self.channel:
                controller._values = np.array(weights, dtype=np.float64)

    # ------------------------------------------------------------------
    # Channel preview — B&W visualisation
    # ------------------------------------------------------------------

    @property
    def preview_visible(self) -> bool:
        """True if the viewport is currently showing the grayscale preview.

        Just ``_preview_active`` -- as of the 2026-07-24 direct-mode
        experiment (see module docstring / ``ChannelPaintController._pin_target``),
        an active paint session no longer forces grayscale on its own:
        direct mode shows real colors, BW mode shows the scratch preview,
        and the toggle now works live in both directions mid-session.
        """
        return self._preview_active

    @property
    def preview_locked(self) -> bool:
        """True while the paint tool is active on this mesh -- B&W is forced.

        Painting always happens on the scratch colorSet so artUserPaintCtx's
        native grayscale feedback stays isolated to the active channel;
        painting directly on the real colorSet (direct/color mode) corrupts
        the sibling channels. So the B&W toggle is LOCKED on for the whole
        paint session -- the UI snaps the button back if the artist tries to
        turn it off (see ``wgt_deformer_panel._on_toggled``). Reverts the
        2026-07-24 direct-mode experiment, which production confirmed unsafe.
        """
        return _has_active_paint_session(self._mesh_name)

    def enable_preview(self) -> None:
        """Create a temp colorSet where R=G=B=<active channel> and display it.

        The mesh's ``displayColors`` attribute is turned on so the viewport
        shows the active channel as a greyscale image.
        """
        check_channel_isolation(self._mesh_name, self._color_set)

        values = self.get_weights()

        # Ensure the preview colorSet exists
        existing = cmds.polyColorSet(self._mesh_name, q=True, allColorSets=True) or []
        if _PREVIEW_SET not in existing:
            cmds.polyColorSet(self._mesh_name, create=True, colorSet=_PREVIEW_SET,
                              representation='RGBA')
            # Adding a colorSet via cmds changes the mesh's colorSet list —
            # MeshDataFactory's cached MFnMesh handle doesn't know that on
            # its own and can misbehave on subsequent get/setVertexColors
            # calls (wrong colorset targeted) until rebuilt.
            MeshDataFactory.get(self._mesh_name).refresh()

        cmds.polyColorSet(self._mesh_name, currentColorSet=True,
                          colorSet=_PREVIEW_SET)

        self._update_preview(values)

        cmds.setAttr(f'{self._mesh_name}.displayColors', 1)
        self._preview_active = True
        logger.info(f"Channel preview enabled on '{self._mesh_name}' ({self.channel}).")

    def disable_preview(self) -> None:
        """Turn B&W off, restore the original display, and stop painting.

        Painting is B&W-locked (channel isolation), so leaving B&W means
        leaving paint mode. If the artisan paint tool is still active on
        this mesh, switch back to Maya's Select tool first -- this ends the
        paint session (so the artist never has to pick the Select tool
        manually, and can never end up painting in color mode) -- then tear
        the preview down normally.
        """
        if _has_active_paint_session(self._mesh_name):
            try:
                cmds.setToolTo('selectSuperContext')
            except Exception as e:
                logger.warning(f"Could not switch to the Select tool: {e}")

        existing = cmds.polyColorSet(self._mesh_name, q=True, allColorSets=True) or []
        if _PREVIEW_SET in existing:
            cmds.polyColorSet(self._mesh_name, delete=True, colorSet=_PREVIEW_SET)
            # Same reasoning as enable_preview — removing a colorSet also
            # changes the mesh's colorSet list out from under the cached
            # MFnMesh handle.
            MeshDataFactory.get(self._mesh_name).refresh()

        # Restore original colorSet
        cmds.polyColorSet(self._mesh_name, currentColorSet=True,
                          colorSet=self._color_set)
        self._preview_active = False
        logger.info(f"Channel preview disabled on '{self._mesh_name}'.")

    def _update_preview(self, values: WeightList) -> None:
        """Refresh the preview colorSet with current channel values."""
        n = len(values)
        existing = cmds.polyColorSet(self._mesh_name, q=True, allColorSets=True) or []
        if _PREVIEW_SET not in existing:
            return

        cmds.polyColorSet(self._mesh_name, currentColorSet=True, colorSet=_PREVIEW_SET)

        try:
            import maya.api.OpenMaya as om2
            fn_mesh = MeshDataFactory.get(self._mesh_name)._fn_mesh
            colors = om2.MColorArray()
            vertex_list = list(range(n))
            for i in range(n):
                v = float(values[i])
                colors.append(om2.MColor((v, v, v, 1.0)))
            fn_mesh.setVertexColors(colors, vertex_list)
        except Exception:
            for i, a in enumerate(values):
                v = float(a)
                cmds.polyColorPerVertex(
                    f'{self._mesh_name}.vtx[{i}]',
                    r=v, g=v, b=v, a=1.0,
                    colorDisplayOption=True, representation=4,
                )
    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _face_vertex_to_vertex(self, fv_values: list, n: int) -> WeightList:
        """Average per-face-vertex channel values to per-vertex."""
        accum = [0.0] * n
        counts = [0] * n
        # Build a vtx-to-faceVertex mapping
        for i in range(n):
            faces = cmds.polyListComponentConversion(
                f'{self._mesh_name}.vtx[{i}]', toVertexFace=True
            ) or []
            faces = cmds.ls(faces, fl=True) or []
            for _ in faces:
                if i < len(fv_values):
                    accum[i] += fv_values[i]
                    counts[i] += 1
        result = []
        for i in range(n):
            if counts[i] > 0:
                result.append(accum[i] / counts[i])
            else:
                result.append(1.0)
        return result


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------

def create_alpha_map(mesh: str, color_set: str = '', default_value: float = 0.0) -> 'VertexColorSet':
    """Create a new colorSet on *mesh* and fill its alpha with *default_value*.

    Args:
        mesh:          Transform or shape name.
        color_set:     Name for the new colorSet.  Defaults to ``'alphaMap'``.
        default_value: Initial alpha value for all vertices (0.0 = black).

    Returns:
        A ready-to-use :class:`VertexColorSet` instance (alpha map active).
    """
    if not color_set:
        color_set = 'alphaMap'

    # Resolve to transform
    if cmds.objectType(mesh) == 'mesh':
        parents = cmds.listRelatives(mesh, parent=True, fullPath=True) or [mesh]
        mesh = parents[0]

    # Create the colorSet if it doesn't exist
    existing = cmds.polyColorSet(mesh, q=True, allColorSets=True) or []
    is_new = color_set not in existing
    if is_new:
        cmds.polyColorSet(mesh, create=True, colorSet=color_set, representation='RGBA')
        logger.info(f"Created colorSet '{color_set}' on '{mesh}'.")
    else:
        logger.info(f"ColorSet '{color_set}' already exists on '{mesh}', reusing.")

    source = VertexColorSet(mesh, color_set=color_set)
    n = source.vtx_count

    if is_new:
        # Establish a genuine full-RGBA baseline in one call. Writing only
        # the alpha channel on a brand-new colorSet (polyColorPerVertex
        # with just `a=`) leaves per-vertex color records ambiguously
        # "not really assigned" in Maya's storage — later reads through
        # getVertexColors can then fall back to Maya's own internal default
        # instead of the values actually painted. A single full-channel
        # flood right after creation avoids that ambiguity entirely.
        cmds.polyColorSet(mesh, currentColorSet=True, colorSet=color_set)
        cmds.polyColorPerVertex(
            f'{mesh}.vtx[0:{n - 1}]',
            r=0.0, g=0.0, b=0.0, a=float(default_value),
            colorDisplayOption=True, representation=4,
        )
        source.use_map('alpha')
    else:
        source.use_map('alpha').set_weights([float(default_value)] * n)

    return source