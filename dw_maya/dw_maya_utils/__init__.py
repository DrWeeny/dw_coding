import sys
import os

# ----- Edit sysPath Dynamically -----
rdPath = os.path.join(os.path.dirname(__file__), "..", "dw_open_tools")
if rdPath not in sys.path:
    print(f"Add {rdPath} to sysPath")
    sys.path.insert(0, rdPath)

try:
    from maya import cmds, mel
    print("Maya commands loaded successfully.")
except ImportError as e:
    print("Maya commands not available. Error:", e)

# Explicit imports for clarity and maintainability
from .dw_maya_attrs import get_type_io, add_attr, lock_attr
from .dw_maya_components import chunks, mag, get_next_free_multi_index
from .dw_maya_data import Flags, unique_name, convert_list_to_mel_str
from .dw_maya_time import current_timerange
from .dw_maya_message import m_warning, m_error, m_message
from .dw_lsTr import lsTr
from .dw_maya_prefs import cache_maya_internal_data, os_build, maya_version
from .dw_maya_raycast import nearest_uv_on_mesh, test_if_inside_mesh
from .dw_mesh_utils import extractFaces, uncombineMesh
from .dw_vtx import change_curve_pivot, get_common_roots
