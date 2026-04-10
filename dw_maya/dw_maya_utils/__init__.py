# Explicit imports for clarity and maintainability
print(1)
from dw_maya.dw_maya_utils.dw_maya_attrs import get_type_io, add_attr, lock_attr
print(2)
from dw_maya.dw_maya_utils.dw_maya_data import flags, unique_name, convert_list_to_mel_str, merge_two_dicts
print(3)
from dw_maya.dw_maya_utils.dw_lsTr import lsTr
print(4)
from dw_maya.dw_maya_utils.dw_maya_components import (component_in_list, chunks, mag, get_next_free_multi_index,
                                 create_maya_ranges, get_vtx_pos, invert_selection, extract_id)
print(5)
from dw_maya.dw_maya_utils.dw_maya_time import current_timerange
print(6)
from dw_maya.dw_maya_utils.dw_maya_message import message, warning, error
print(7)
from dw_maya.dw_maya_utils.dw_maya_prefs import MayaVersionInfo
print(8)
from dw_maya.dw_maya_utils.dw_uv import closest_uv_on_mesh, nearest_uv_on_mesh, get_uv_from_vtx
print(9)
from dw_maya.dw_maya_utils.dw_mesh_utils import extract_faces, separate_mesh
print(0)
from dw_maya.dw_maya_utils.dw_vtx import change_curve_pivot, get_common_roots
