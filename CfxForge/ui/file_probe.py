"""Probe a geometry file's hierarchy for the recipe editor.

Summary:
    The editor runs outside Maya, so it cannot open an .abc/.ma itself.
    ``probe(path)`` shells the dump part of this module out to mayapy
    (found via the DW_MAYAPY env var or a Program Files glob) and caches
    the result keyed on path+mtime.

    Two dump strategies: .abc files are walked with the PyAlembic
    bindings mayapy ships (``import alembic`` - NO maya.standalone boot,
    seconds instead of tens of seconds); .ma/.mb fall back to a real
    standalone scene import. (For reference, the wider alembic tool
    ecosystem: abcls/abctree/abcecho CLIs, AbcView GUI, and the `cask`
    python wrapper - none installed on this machine, and pip's `alembic`
    is the unrelated SQL migration tool.)

    Run BY mayapy (internal): mayapy file_probe.py <file> <out_json>

Functions:
    probe, cached_probe_path, find_mayapy

Author:
    DrWeeny
"""

import glob
import hashlib
import json
import os
import subprocess
import sys
import tempfile


def find_mayapy() -> str:
    """Locate mayapy: DW_MAYAPY env var first, newest Maya otherwise."""
    env = os.environ.get('DW_MAYAPY')
    if env and os.path.isfile(env):
        return env
    hits = sorted(glob.glob(
        r'C:\Program Files\Autodesk\Maya*\bin\mayapy.exe'))
    return hits[-1] if hits else ''


def cached_probe_path(path: str) -> str:
    """Cache file keyed on absolute path + mtime."""
    key = f'{os.path.abspath(path)}|{os.path.getmtime(path)}'
    digest = hashlib.md5(key.encode('utf-8')).hexdigest()
    folder = os.path.join(tempfile.gettempdir(), 'dw_file_probe')
    if not os.path.isdir(folder):
        os.makedirs(folder)
    return os.path.join(folder, digest + '.json')


def probe(path: str, timeout: int = 240) -> dict:
    """Return {'entries': [{'path', 'type', 'verts'?}]}; raises on failure."""
    if not os.path.isfile(path):
        raise ValueError(f'file not found: {path}')
    cache = cached_probe_path(path)
    if os.path.isfile(cache):
        with open(cache, 'r') as f:
            return json.load(f)
    mayapy = find_mayapy()
    if not mayapy:
        raise RuntimeError('mayapy not found - set the DW_MAYAPY env var')
    result = subprocess.run([mayapy, os.path.abspath(__file__), path, cache],
                            capture_output=True,
                            text=True,
                            timeout=timeout)
    if not os.path.isfile(cache):
        raise RuntimeError(f'probe failed:\n{result.stdout}\n{result.stderr}')
    with open(cache, 'r') as f:
        return json.load(f)


def _dump_abc(path: str) -> list:
    """PyAlembic walk - no standalone boot, fast."""
    from alembic import Abc, AbcGeom

    entries = []

    def walk(obj):
        for i in range(obj.getNumChildren()):
            child = obj.getChild(i)
            md = child.getMetaData()
            if AbcGeom.IPolyMesh.matches(md):
                mesh = AbcGeom.IPolyMesh(
                    child, Abc.WrapExistingFlag.kWrapExisting)
                sample = mesh.getSchema().getValue()
                entries.append({'path': child.getFullName(),
                                'type': 'mesh',
                                'verts': len(sample.getPositions())})
            elif AbcGeom.ICurves.matches(md):
                entries.append({'path': child.getFullName(),
                                'type': 'nurbsCurve'})
            elif AbcGeom.IXform.matches(md):
                entries.append({'path': child.getFullName(),
                                'type': 'group'})
            else:
                entries.append({'path': child.getFullName(),
                                'type': md.get('schema') or 'unknown'})
            walk(child)

    walk(Abc.IArchive(path).getTop())
    # a leaf shape sharing its parent xform's intent reads better as the
    # parent typed by its shape (matches how Maya displays it)
    by_path = {e['path']: e for e in entries}
    merged = []
    for entry in entries:
        parent, _, _ = entry['path'].rpartition('/')
        holder = by_path.get(parent)
        if (entry['type'] != 'group' and holder
                and holder.get('type') == 'group'):
            holder['type'] = entry['type']
            if 'verts' in entry:
                holder['verts'] = entry['verts']
            continue
        merged.append(entry)
    return merged


def _dump_scene(path: str) -> list:
    """maya.standalone scene import - .ma/.mb fallback."""
    import maya.standalone
    maya.standalone.initialize(name='python')
    from maya import cmds
    cmds.file(new=True, force=True)
    nodes = cmds.file(path, i=True, returnNewNodes=True) or []
    entries = []
    for transform in cmds.ls(nodes, type='transform', long=True) or []:
        shapes = cmds.listRelatives(transform,
                                    shapes=True,
                                    noIntermediate=True,
                                    fullPath=True) or []
        node_type = cmds.nodeType(shapes[0]) if shapes else 'group'
        entry = {'path': transform.replace('|', '/'), 'type': node_type}
        if node_type == 'mesh':
            entry['verts'] = cmds.polyEvaluate(transform, vertex=True)
        entries.append(entry)
    maya.standalone.uninitialize()
    return entries


def _dump(path: str, out_path: str):
    if path.lower().endswith('.abc'):
        entries = _dump_abc(path)
    else:
        entries = _dump_scene(path)
    with open(out_path, 'w') as f:
        json.dump({'file': path, 'entries': entries}, f, indent=2)


if __name__ == '__main__':
    _dump(sys.argv[1], sys.argv[2])