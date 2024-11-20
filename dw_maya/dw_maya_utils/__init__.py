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
from .dw_maya_components import chunks, mag, get_next_free_multi_index, create_maya_ranges
from .dw_maya_data import flags, unique_name, convert_list_to_mel_str, merge_two_dicts
from .dw_maya_time import current_timerange
from .dw_maya_message import message, warning, error
from .dw_lsTr import lsTr
from .dw_maya_prefs import MayaVersionInfo
from .dw_uv import closest_uv_on_mesh, nearest_uv_on_mesh, get_uv_from_vtx
from .dw_mesh_utils import extract_faces, separate_mesh
from .dw_vtx import change_curve_pivot, get_common_roots
