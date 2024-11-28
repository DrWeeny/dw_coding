import re, itertools, math
from typing import Iterable, List, Generator, Tuple, Optional, Union, Set
from dw_maya.dw_constants.node_re_mappings import COMPONENT_PATTERN
from maya import cmds

from dw_maya.dw_decorators import acceptString

# Type aliases for clarity
Point3D = Tuple[float, float, float]
MayaComponent = str
ComponentID = int
ComponentRange = str

def component_in_list(node_list):
    if any([COMPONENT_PATTERN.match(name) for name in node_list]):
        return True
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
        if match := re.search(pattern, comp):
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



