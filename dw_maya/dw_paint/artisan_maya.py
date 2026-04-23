"""
artisan_maya.py
---------------
Low-level helpers for Maya's Artisan paint contexts.

All context-routing logic lives here so controllers and UI layers
never have to branch on context type themselves.
"""
from maya import cmds, mel
from typing import Optional, Tuple

# ---------------------------------------------------------------------------
# Artisan context name constants
# ---------------------------------------------------------------------------
CTX_ALPHA    = 'dwAlphaPaintCtx'        # artUserPaintCtx cmd — vertex color alpha
CTX_NUCLEUS  = 'artAttrNClothContext'   # artAttrCtx cmd      — nCloth / nRigid
CTX_DEFORMER = 'artAttrContext'         # artAttrCtx cmd      — cluster, deltaMush…
# BlendShape reports its own ctx name via WeightSource.get_artisan_name().
# The MEL *command* for all artAttrCtx-family contexts is always 'artAttrCtx';
# the default *instance* name Maya assigns is 'artAttrContext'.
CTX_DEFORMER_CMD = 'artAttrCtx'        # used for artAttrUpdatePaintValueSlider

# Keep old private names as aliases for backward-compat
_CTX_ALPHA        = CTX_ALPHA
_CTX_NUCLEUS      = CTX_NUCLEUS
_CTX_DEFORMER     = CTX_DEFORMER
_CTX_DEFORMER_CMD = CTX_DEFORMER_CMD


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_cmd(context_name: str):
    """Return the correct cmds function for *context_name*.

    ``artUserPaintCtx`` for the vertex-alpha context, ``artAttrCtx`` for
    everything else (nucleus, deformers, blendshapes…).
    """
    return cmds.artUserPaintCtx if context_name == CTX_ALPHA else cmds.artAttrCtx


def _ensure_ctx(context_name: Optional[str] = None) -> Optional[str]:
    """Return *context_name*, falling back to ``currentCtx()``.

    Returns ``None`` when no context can be determined.
    """
    if not context_name:
        context_name = cmds.currentCtx()
    return context_name or None


# ---------------------------------------------------------------------------
# Nucleus helpers (kept for backward-compat)
# ---------------------------------------------------------------------------

def artisan_nucx_open() -> None:
    """Open the Tool Settings window and switch to the nCloth paint context."""
    mel.eval('toolPropertyWindow;')
    mel.eval('setToolTo "artAttrNClothContext";')


def set_brush_val(val: float, mod: str = 'absolute',
                  context_name: str = CTX_DEFORMER) -> None:
    """Set *val* and operation *mod* on *context_name* (artAttrCtx family).

    Args:
        val:          Brush value.
        mod:          ``'absolute'``, ``'additive'``, or ``'scale'``.
        context_name: Target context instance name.
    """
    cmds.artAttrCtx(context_name, edit=True, value=val)
    cmds.artAttrCtx(context_name, edit=True, selectedattroper=mod)


def flood_smooth_vtx_map(context_name: str = CTX_DEFORMER) -> None:
    """Flood a single smooth pass on *context_name* and refresh the viewport."""
    cmds.artAttrCtx(context_name, edit=True, selectedattroper='smooth')
    cmds.refresh()
    cmds.artAttrCtx(context_name, edit=True, clear=True)


# ---------------------------------------------------------------------------
# Clamp
# ---------------------------------------------------------------------------

def get_artisan_clamp(context_name: Optional[str] = None
                      ) -> Optional[Tuple[str, float, float]]:
    """Read clamp settings from *context_name* (or ``currentCtx()``).

    Returns:
        ``(clamp_mode, lower, upper)`` tuple, or ``None`` on failure.
    """
    context_name = _ensure_ctx(context_name)
    if context_name is None:
        return None
    cmd = _resolve_cmd(context_name)
    try:
        if cmd(context_name, exists=True):
            clamp_mode = cmd(context_name, query=True, clamp=True) or 'none'
            lower_v    = cmd(context_name, query=True, clamplower=True)
            upper_v    = cmd(context_name, query=True, clampupper=True)
            return (clamp_mode, lower_v, upper_v)
    except Exception:
        pass
    return None


def set_artisan_clamp(clamp_mode: str, min_value: float, max_value: float,
                      context_name: Optional[str] = None) -> None:
    """Push clamp settings to *context_name* (or ``currentCtx()``).

    Also syncs the ``artAttrClampField`` floatFieldGrp in the Tool Settings
    window when it is open.

    Args:
        clamp_mode:   ``'none'``, ``'lower'``, ``'upper'``, or ``'both'``.
        min_value:    Lower clamp value.
        max_value:    Upper clamp value.
        context_name: Target context instance name.  Defaults to ``currentCtx()``.
    """
    context_name = _ensure_ctx(context_name)
    if context_name is None:
        return
    cmd = _resolve_cmd(context_name)
    try:
        if cmd(context_name, exists=True):
            cmd(context_name, edit=True,
                clamp=clamp_mode, clamplower=min_value, clampupper=max_value)
    except Exception:
        pass
    # Sync Tool Settings floatFieldGrp
    try:
        if mel.eval('floatFieldGrp -exists artAttrClampField'):
            mel.eval(f'floatFieldGrp -e -v1 {min_value} -v2 {max_value} artAttrClampField')
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Color / display range
# ---------------------------------------------------------------------------

def set_artisan_color_range(lo: float = 0.0, hi: float = 1.0,
                            context_name: Optional[str] = None) -> None:
    """Set the viewport colour-gradient display range on *context_name*.

    Sets ``colorrangelower`` / ``colorrangeupper``.  *Not* the same as the
    clamp bounds (``clamplower`` / ``clampupper``).

    Silently skipped for :data:`CTX_ALPHA` (vertex alpha uses a different
    display mechanism).

    Args:
        lo:           Lower display bound.
        hi:           Upper display bound.
        context_name: Target context instance name.  Defaults to ``currentCtx()``.
    """
    context_name = _ensure_ctx(context_name)
    if context_name is None or context_name == CTX_ALPHA:
        return
    cmd = _resolve_cmd(context_name)
    try:
        if cmd(context_name, exists=True):
            cmd(context_name, edit=True, colorrangelower=lo, colorrangeupper=hi)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Paint value (brush value + slider range)
# ---------------------------------------------------------------------------

def get_artisan_value_range(context_name: Optional[str] = None
                            ) -> Optional[Tuple[float, float]]:
    """Return ``(minvalue, maxvalue)`` slider bounds from *context_name*.

    Returns ``None`` when the context does not exist or an error occurs.
    """
    context_name = _ensure_ctx(context_name)
    if context_name is None:
        return None
    cmd = _resolve_cmd(context_name)
    try:
        if cmd(context_name, exists=True):
            lo = cmd(context_name, query=True, minvalue=True)
            hi = cmd(context_name, query=True, maxvalue=True)
            return (lo, hi)
    except Exception:
        pass
    return None


def set_artisan_value(value: float, context_name: Optional[str] = None) -> None:
    """Push *value* to the paint brush and auto-extend the slider range.

    For ``artAttrCtx``-family contexts, ``minvalue`` / ``maxvalue`` are
    extended when *value* falls outside the current slider range, and
    ``artAttrUpdatePaintValueSlider`` is called so the Tool Settings slider
    stays in sync.

    For :data:`CTX_ALPHA` (``artUserPaintCtx``), only the value is set —
    that context does not support ``minvalue`` / ``maxvalue``.

    Args:
        value:        Brush value to set.
        context_name: Target context instance name.  Defaults to ``currentCtx()``.
    """
    context_name = _ensure_ctx(context_name)
    if context_name is None:
        return
    cmd = _resolve_cmd(context_name)
    try:
        if not cmd(context_name, exists=True):
            return
        if context_name == CTX_ALPHA:
            cmd(context_name, edit=True, value=value)
            return
        # Extend slider bounds when needed
        cur_min = cmd(context_name, query=True, minvalue=True)
        cur_max = cmd(context_name, query=True, maxvalue=True)
        new_min = min(cur_min, value)
        new_max = max(cur_max, value)
        cmd(context_name, edit=True, value=value,
            minvalue=new_min, maxvalue=new_max)
    except Exception:
        pass
