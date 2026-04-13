import re
import itertools
import math
from typing import Iterable, List, Generator, Tuple, Optional, Set

import maya.cmds
from dw_maya.dw_constants.node_re_mappings import COMPONENT_PATTERN
from maya import cmds  # legacy alias kept for existing functions

from dw_maya.dw_decorators import acceptString

# Regex to detect any Maya component type from a component string (vtx, f, e, cv, …)
_COMP_TYPE_RE = re.compile(r'\.(\w+)\[')
_CV_RE = re.compile(r'^(.+\.cv)\[(\d+)(?::(\d+))?]$')

# polyListComponentConversion kwargs per target type
_TO_COMP_FLAGS = {
    'vtx': {'toVertex': True},
    'f':   {'toFace': True},
    'e':   {'toEdge': True},
}

# Type aliases for clarity
Point3D = Tuple[float, float, float]
MayaComponent = str
ComponentID = int
ComponentRange = str

def selectBorder():
    """ Select components next to selected ones. """

    sel = cmds.filterExpand(selectionMask=[31, 32, 34])
    if not sel:
        cmds.warning("Wrong selection. (Must be a components selection.)")
    else:
        cmds.GrowPolygonSelectionRegion()
        cmds.select(sel, deselect=True)

def component_in_list(node_list):
    for name in node_list:
        component = COMPONENT_PATTERN.match(name)
        if component:
            component_type = component.group(2)
            return component_type
    return False

def chunks(iterable: Iterable, size: int) -> Generator[List, None, None]:
    """
    Split iterable into fixed-size chunks.

    Args:
        iterable: Input sequence to chunk
        size: Size of each chunk

    Yields:
        Chunks of specified size

    Example:
        >>> list(chunks([1, 2, 3, 4, 5], 2))
        [[1, 2], [3, 4], [5]]
    """
    if size <= 0:
        raise ValueError("Chunk size must be positive")

    items = list(iterable)
    return (items[i:i + size] for i in range(0, len(items), size))


def mag(p1: Point3D, p2: Point3D) -> float:
    """
    Calculate distance between two 3D points.

    Args:
        p1: First point (x, y, z)
        p2: Second point (x, y, z)

    Returns:
        Euclidean distance

    Example:
        >>> mag((1, 2, 3), (4, 5, 6))
        5.196152422706632
    """
    if not (len(p1) == len(p2) == 3):
        raise ValueError("Points must be 3D")

    return math.sqrt(sum((a - b) ** 2 for a, b in zip(p1, p2)))


def get_next_free_multi_index(attr: str, max_index: int = 10000000) -> int:
    """
    Finds the next unconnected multi-index for the given Maya attribute.

    Args:
        attr (str): The name of the multi-index attribute to check (e.g., 'node.attr').
        max_index (int): The maximum index to check (default is 10 million).

    Returns:
        int: The next available index that is unconnected.
    """
    # Clean attribute name
    attr = re.sub(r'\[\d+]$', '', attr)

    # Check each index
    for i in range(max_index):
        if not cmds.connectionInfo(f"{attr}[{i}]", sfd=True):
            return i

    raise RuntimeError(f"No free index found for {attr} up to {max_index}")


def get_vtx_pos(mesh: str, world_space=True) -> List[Tuple[float, float, float]]:
    """
    Get the world space positions of all vertices for a given mesh.

    Args:
        mesh (str): The name of the mesh to query vertex positions for.

    Returns:
        List[Tuple[float, float, float]]: A list of tuples, where each tuple contains the (x, y, z)
        world space coordinates of a vertex.

    Example:
        get_vtx_pos('pSphere1')
        [(1.0, 2.0, 3.0), (4.0, 5.0, 6.0), ...]
    """
    positions = cmds.xform(f"{mesh}.vtx[*]", q=True, ws=world_space, t=True)
    return list(zip(positions[0::3], positions[1::3], positions[2::3]))



@acceptString('crvs')
def get_crv_average_bbox(crvs: List[str]) -> float:
    """
    Calculate the average length of the provided NURBS curves with BBOX.

    Args:
        crvs (list of str): A list of curve names.

    Returns:
        float: The average length of the curves.
    """
    bboxs = [cmds.xform(i, q=True, bb=True) for i in crvs]
    coords = [chunks(bb, 3) for bb in bboxs]
    aver = sum([mag(*co) for co in coords]) / float(len(crvs))
    return aver


def extract_id(components: List[str],
               component_type: Optional[str] = None) -> List[int]:
    """
    Extract indices from Maya component names, including range notation.

    Args:
        components: List of component names (e.g., ['pSphere1.vtx[0]', 'pSphere1.vtx[5:9]'])
        component_type: Optional type filter ('vtx', 'e', 'f')

    Returns:
        List of component indices, expanded from ranges

    Examples:
        >>> extract_id(['pSphere1.vtx[0]', 'pSphere1.vtx[5:9]'], 'vtx')
        [0, 5, 6, 7, 8, 9]

        >>> extract_id(['pSphere1.f[1]', 'pSphere1.f[3:5]'], 'f')
        [1, 3, 4, 5]
    """
    # Build regex pattern for both single indices and ranges
    if component_type:
        pattern = fr'\.{component_type}\[(\d+:?\d*)]'
    else:
        pattern = r'\.\w+\[(\d+:?\d*)]'

    indices: Set[int] = set()

    for comp in components:
        match = re.search(pattern, comp)
        if match:
            index_str = match.group(1)

            # Handle range notation
            if ':' in index_str:
                start, end = map(int, index_str.split(':'))
                indices.update(range(start, end + 1))
            else:
                indices.add(int(index_str))

    return sorted(indices)


def create_maya_ranges(indices: List[ComponentID]) -> List[ComponentRange]:
    """
    Convert indices to Maya range notation.

    Args:
        indices: List of component indices

    Returns:
        List of range strings

    Example:
        >>> create_maya_ranges([0, 1, 2, 3, 5, 6, 7])
        ['0:3', '5:7']
    """
    ranges = []
    for _, group in itertools.groupby(enumerate(sorted(indices)), lambda x: x[1] - x[0]):
        group = list(group)
        start = group[0][1]
        end = group[-1][1]

        ranges.append(
            f"{start}" if start == end else f"{start}:{end}")

    return ranges

def invert_selection(select=True, range_opti=True):
    """
    Invert selection of components
    Args:
        select (bool): Select the inverted components
        range_opti (bool): Use range notation for optimization
    Returns:
        list: Inverted component list
    """
    from .dw_lsTr import lsTr

    sel = cmds.ls(sl=True, flatten=True)
    objs = lsTr(sl=True, o=True)
    if not sel and objs:
        new_list = [f"{o}.vtx[:]" for o in objs]
        if select:
            cmds.select(new_list)
        return new_list
    compo_type = COMPONENT_PATTERN.match(sel[0]).group(2)
    new_list = []
    for o in objs:
        sel_filter = f"{o}.{compo_type}[:]"
        _all = cmds.ls(sel_filter, flatten=True)
        inverse = list(set(_all) - set(sel))

        if range_opti:
            _range = create_maya_ranges(extract_id(inverse))
            inverse_opti = [f"{o}.{compo_type}[{r}]" for r in _range]
            new_list += inverse_opti
        else:
            new_list += inverse
    if select:
        cmds.select(new_list, r=True)
    return new_list


# ---------------------------------------------------------------------------
# Component grow utilities
# ---------------------------------------------------------------------------

def _grow_cv_selection(sel: List[str]) -> List[str]:
    """Grow NURBS CV selection by ±1 index on each side, clamped to valid range.

    Args:
        sel: CV component strings, e.g. ``['curveShape1.cv[2]', 'curveShape1.cv[4:6]']``.

    Returns:
        Grown CV component strings.
    """
    # cache max cv index per shape to avoid repeated getAttr calls
    _max_cv_cache = {}

    def _max_cv(shape: str) -> int:
        if shape not in _max_cv_cache:
            spans = maya.cmds.getAttr(f"{shape}.spans")
            degree = maya.cmds.getAttr(f"{shape}.degree")
            _max_cv_cache[shape] = spans + degree - 1
        return _max_cv_cache[shape]

    result = []
    for item in sel:
        m = _CV_RE.match(item)
        if not m:
            result.append(item)
            continue
        base = m.group(1)                          # e.g. 'curveShape1.cv'
        shape = base.rsplit('.', 1)[0]
        start = int(m.group(2))
        end = int(m.group(3)) if m.group(3) else start
        start = max(start - 1, 0)
        end = min(end + 1, _max_cv(shape))
        result.append(f"{base}[{start}:{end}]")
    return result


def grow_component_selection(sel: list = None, select: bool = True) -> list:
    """Grow component selection by one topological step.

    For mesh components (vtx / f / e): converts to vertices, expands via edge
    connectivity (vtx → edge → vtx), then converts back to the original type.
    For NURBS curve CVs: expands each index range by ±1 (clamped).

    Args:
        sel (list): Component list. Uses current selection if None.
        select (bool): Apply the result as the active Maya selection.

    Returns:
        list: Grown component list (flattened strings).

    Example:
        import dw_maya.dw_maya_utils.dw_maya_components as dw_maya_components
        grown = dw_maya_components.grow_component_selection()
    """
    if sel is None:
        sel = maya.cmds.ls(selection=True, flatten=True)
    if not sel:
        return []

    m = _COMP_TYPE_RE.search(sel[0])
    if not m:
        return list(sel)
    orig_type = m.group(1)  # 'vtx', 'f', 'e', 'cv', …

    # NURBS curve: index expansion
    if orig_type == 'cv':
        result = _grow_cv_selection(sel)

    else:
        # Mesh: vtx → edge → vtx → original type
        as_vtx = maya.cmds.ls(
            maya.cmds.polyListComponentConversion(sel, toVertex=True),
            flatten=True,
        )
        as_edge = maya.cmds.polyListComponentConversion(as_vtx, toEdge=True)
        grown_vtx = maya.cmds.ls(
            maya.cmds.polyListComponentConversion(as_edge, toVertex=True),
            flatten=True,
        )

        conv_flags = _TO_COMP_FLAGS.get(orig_type, {'toVertex': True})
        result = maya.cmds.ls(
            maya.cmds.polyListComponentConversion(grown_vtx, **conv_flags),
            flatten=True,
        )

    if select and result:
        maya.cmds.select(result, replace=True)
    return result


def grow_component_selection_max(sel: list = None, select: bool = True) -> list:
    """Grow component selection repeatedly until it no longer changes.

    Calls :func:`grow_component_selection` in a loop until the selection set is
    stable (i.e. the whole connected region is selected).

    Args:
        sel (list): Component list. Uses current selection if None.
        select (bool): Apply the result as the active Maya selection.

    Returns:
        list: Maximally grown component list.

    Example:
        import dw_maya.dw_maya_utils.dw_maya_components as dw_maya_components
        all_vtx = dw_maya_components.grow_component_selection_max()
    """
    if sel is None:
        sel = maya.cmds.ls(selection=True, flatten=True)
    if not sel:
        return []

    current = set(sel)
    while True:
        grown = grow_component_selection(list(current), select=False)
        grown_set = set(grown)
        if grown_set == current:
            break
        current = grown_set

    result = sorted(current)
    if select and result:
        maya.cmds.select(result, replace=True)
    return result
