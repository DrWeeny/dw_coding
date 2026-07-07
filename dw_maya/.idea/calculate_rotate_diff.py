from maya import cmds
from maya.api import OpenMaya as om


def _frame_matrix(a, b, c):
    a, b, c = om.MVector(*a), om.MVector(*b), om.MVector(*c)
    x = (b - a).normalize()
    z = (x ^ (c - a)).normalize()
    y = (z ^ x).normalize()
    # Maya row-vector convention: basis vectors are the matrix rows
    return om.MMatrix([x.x, x.y, x.z, 0,
                       y.x, y.y, y.z, 0,
                       z.x, z.y, z.z, 0,
                       0, 0, 0, 1])


def find_offset(tpose_mesh, abc_mesh, vtx_ids):
    """Return the worldspace matrix that moves tpose_mesh onto abc_mesh."""
    p = [cmds.pointPosition(f"{tpose_mesh}.vtx[{i}]", world=True) for i in vtx_ids]
    q = [cmds.pointPosition(f"{abc_mesh}.vtx[{i}]", world=True) for i in vtx_ids]

    m = _frame_matrix(*p).inverse() * _frame_matrix(*q)
    t = om.MVector(*q[0]) - om.MVector(*p[0]) * m
    m = list(m)
    m[12:15] = [t.x, t.y, t.z]
    return m


# --- usage: pick 3 well-spread, non-collinear vertices ---
mat = find_offset("tpose_body", "abc_body", [12, 850, 4021])

# apply to the rig top group (or a locator to inspect the values)
cmds.xform("rig_top_grp", worldSpace=True, matrix=mat)

# or just read translate/rotate values:
tmp = cmds.createNode("transform", name="offset_check")
cmds.xform(tmp, worldSpace=True, matrix=mat)
print(cmds.getAttr(tmp + ".translate")[0], cmds.getAttr(tmp + ".rotate")[0])