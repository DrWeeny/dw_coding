"""Find the vertices a topology edit appended to a painted mesh.

Summary:
    When an artist inserts edge loops or smooths a mesh that already carries
    weight maps, the new vertices come in at the attribute's default value.
    This module decides which vertices those are, so they can be re-derived
    from their neighbours (see ``hammer_weights``). Two detectors, reported
    in order of trust:

    ``exact``
        Maya never resizes a per-vertex attribute on a topology change and
        every modelling op appends at the tail, so a stored element count
        below the vertex count identifies the new vertices exactly:
        ``range(stored, vtx_count)``. Survives history deletion.

    ``trailing``
        Once something rewrote the whole map (a plugin that pads on load,
        any full ``set_weights``) the stored count matches the mesh and the
        only trace left is the padding itself: a constant run at the tail of
        the array. The run is bounded by the last old vertex that happens to
        share the padding value - so the boundary of the block deserves a
        look before hammering. A map that is constant end to end is
        ambiguous and reports nothing.

    Neither detector can see a reorder (delete loop, merge, retopo): those
    scramble the map rather than hole it, and only a spatial transfer from a
    saved copy repairs them.

Classes:
    HoleReport -- result of a detection: method, indices, description.

Functions:
    find_appended_vertices(source) -- run both detectors on a WeightSource.

Example::

    src = resolve_weight_sources('ROBE_cluster_edited')[0]
    report = find_appended_vertices(src)
    if report.indices:
        cmds.select([f'{src.mesh_name}.vtx[{i}]' for i in report.indices])

Author: DrWeeny
"""

from typing import List, Optional

from dw_maya.dw_paint.protocol import WeightSource


class HoleReport:
    """What :func:`find_appended_vertices` found on one map.

    Attributes:
        method:      ``'exact'`` | ``'trailing'`` | ``'none'``.
        indices:     Vertex ids believed to be appended (ascending).
        vtx_count:   Live vertex count of the mesh.
        stored:      Stored element count of the map, or None if unknown.
        block_value: For ``'trailing'``, the constant value of the tail run.
        note:        Why ``'none'`` was returned, when it was.
    """

    def __init__(self,
                 method: str,
                 indices: List[int],
                 vtx_count: int,
                 stored: Optional[int] = None,
                 block_value: Optional[float] = None,
                 note: str = ''):
        self.method = method
        self.indices = indices
        self.vtx_count = vtx_count
        self.stored = stored
        self.block_value = block_value
        self.note = note

    @property
    def start(self) -> Optional[int]:
        """First appended index, or None."""
        return self.indices[0] if self.indices else None

    def describe(self) -> str:
        """One line for the UI / log."""
        n = len(self.indices)
        if self.method == 'exact':
            return (f"{n} appended vertices (exact: the map stores "
                    f"{self.stored} of {self.vtx_count})")
        if self.method == 'trailing':
            return (f"{n} candidates (inferred: constant tail of "
                    f"{self.block_value:g} from vertex {self.start} - check the "
                    f"boundary before hammering)")
        if self.note:
            return f"no appended vertices found ({self.note})"
        return "no appended vertices found"

    def __repr__(self) -> str:
        return f"HoleReport({self.method}, {len(self.indices)} idx, start={self.start})"


def find_appended_vertices(source: WeightSource,
                           min_block: int = 2) -> HoleReport:
    """Detect the vertices appended to *source*'s mesh since its map was written.

    Args:
        source:    Weight source with an active map.
        min_block: Shortest constant tail run the ``'trailing'`` detector
                   accepts. A single trailing vertex at some value is just a
                   vertex; an edge loop is never shorter than a few.

    Returns:
        :class:`HoleReport`. ``indices`` is empty when nothing was found.
    """
    n = source.vtx_count
    stored = source.stored_count()

    if stored is not None and stored < n:
        return HoleReport('exact', list(range(stored, n)), n, stored=stored)
    if stored is not None and stored > n:
        return HoleReport('none', [], n, stored=stored,
                          note=f"the map stores {stored} values for {n} vertices - "
                               f"vertices were removed or reordered, not added")

    weights = source.get_weights()
    if len(weights) != n or n == 0:
        return HoleReport('none', [], n, stored=stored,
                          note="could not read a full-length map")

    last = weights[-1]
    start = n
    while start > 0 and weights[start - 1] == last:
        start -= 1
    block = n - start
    if block == n:
        return HoleReport('none', [], n, stored=stored, block_value=last,
                          note=f"the whole map is {last:g} - nothing to tell "
                               f"appended vertices from painted ones")
    if block < min_block:
        return HoleReport('none', [], n, stored=stored,
                          note="no constant run at the tail of the map")
    return HoleReport('trailing', list(range(start, n)), n, stored=stored, block_value=last)
