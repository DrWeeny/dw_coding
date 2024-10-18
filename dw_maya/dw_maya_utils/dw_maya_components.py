#!/usr/bin/env python
#----------------------------------------------------------------------------#
#------------------------------------------------------------------ HEADER --#

"""
@author:
    abtidona

@description:
    this is a description

@applications:
    - groom
    - cfx
    - fur
"""

#----------------------------------------------------------------------------#
#----------------------------------------------------------------- IMPORTS --#

# built-in
import sys, os

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools\\maya'
if not rdPath in sys.path:
    print("Add {} to sysPath".format(rdPath))
    sys.path.insert(0, rdPath)

import re, itertools, math
from typing import Iterable, List, Generator, Tuple, Optional

# internal
from maya import cmds, mel

# internal

# external
from dw_maya.dw_decorators import acceptString

#----------------------------------------------------------------------------#
#--------------------------------------------------------------- FUNCTIONS --#

def chunks(l: Iterable, n: int) -> Generator:
    """
    Yield successive n-sized chunks from the given iterable.

    Args:
        l (Iterable): The iterable (e.g., list, tuple, string) to split into chunks.
        n (int): The size of each chunk.

    Yields:
        Generator: n-sized chunks from the iterable.

    Example:
        list(chunks([1, 2, 3, 4, 5], 2))
        [[1, 2], [3, 4], [5]]
    """
    # Validate inputs
    if n <= 0:
        raise ValueError("Chunk size 'n' must be greater than 0.")

    l = list(l)  # Convert to list if it's an iterable like a string
    for i in range(0, len(l), n):
        yield l[i:i + n]


def mag(p1: List[float], p2: List[float]) -> float:
    """
    Calculate the Euclidean distance between two 3D points.

    Args:
        p1 (list or tuple of floats): A list or tuple of x, y, z positions.
        p2 (list or tuple of floats): A list or tuple of x, y, z positions.

    Returns:
        float: The Euclidean distance between the two points.

    Example:
        mag([1, 2, 3], [4, 5, 6])
        5.196152422706632
    """
    # Validate that both points have 3 coordinates
    if len(p1) != 3 or len(p2) != 3:
        raise ValueError("Both p1 and p2 must be 3D points (x, y, z).")

    # Calculate the Euclidean distance
    return math.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2 + (p1[2] - p2[2]) ** 2)


def get_next_free_multi_index(attr: str, max_index: int = 10000000) -> int:
    """
    Finds the next unconnected multi-index for the given Maya attribute.

    Args:
        attr (str): The name of the multi-index attribute to check (e.g., 'node.attr').
        max_index (int): The maximum index to check (default is 10 million).

    Returns:
        int: The next available index that is unconnected.
    """
    i = 0
    # assume a max of 10 million connections
    p = re.compile('\[\d+]$')
    attr = p.sub('', attr)

    # Check each index from 0 up to max_index
    for i in range(max_index):
        # Query the connection status of the current index
        connection = cmds.connectionInfo(f"{attr}[{i}]", sfd=True)

        # If no connection is found, return the current index
        if not connection:
            return i

    # If no free index is found within the range, raise an error
    raise RuntimeError(f"No free index found in the range 0 to {max_index} for attribute {attr}.")


def get_vtx_pos(mesh: str) -> List[Tuple[float, float, float]]:
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
    xOrig = cmds.xform(f"{mesh}.vtx[*]", q=True, ws=True, t=True)
    # Group every three values (x, y, z) into tuples using zip
    origPts = zip(xOrig[0::3], xOrig[1::3], xOrig[2::3])
    return list(origPts)


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


def extract_id(sel: List[str], component: Optional[str] = None) -> List[int]:
    """
    Extract the IDs (indices) of the specified component type from a list of selected Maya components.

    Args:
        sel (list of str): A list of selected Maya objects with components (e.g., 'pSphere1.vtx[0]').
        component (str, optional): The component type to extract (e.g., 'vtx', 'e', 'f').
                                   If not provided, it matches generic components.

    Returns:
        list of int: A list of extracted IDs (indices) from the selected components.

    Example:
        extract_id(['pSphere1.vtx[0]', 'pSphere1.vtx[1]', 'pSphere1.vtx[2]'], component='vtx')
        [0, 1, 2]
    """

    if not component:
        pattern = re.compile('\.\w{1,3}\[\d{1,}:?\d{1,}?\]')
    else:
        pattern = '\.{0}\[\d{{1,}}\]'.format(component)

    p = re.compile(pattern)

    # List to store the extracted indices
    ids = []

    # Iterate over the selection and extract the indices
    for s in sel:
        match = p.search(s)
        if match:
            # Extract the number inside the brackets
            ids.append(int(match.group(1)))

    return ids


def create_maya_ranges(indices: List[int]) -> List[str]:
    """
    Convert a list of integers into Maya-style range strings.

    Args:
        indices (list of int): A list of integers to be converted into range strings.

    Returns:
        list of str: A list of Maya-style range strings (e.g., ["0:3", "5:7"]).

    Example:
        create_maya_ranges([0, 1, 2, 3, 5, 6, 7])
        ['0:3', '5:7']
    """
    output = []

    # Group the indices by consecutive sequences
    for _, group in itertools.groupby(enumerate(indices), lambda x_y: x_y[1] - x_y[0]):
        group = list(group)
        start = group[0][1]
        end = group[-1][1]

        # If start == end, just append the single number; otherwise, append a range
        if start == end:
            output.append(f"{start}")
        else:
            output.append(f"{start}:{end}")

    return output