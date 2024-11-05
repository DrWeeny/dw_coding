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
rdPath = '/user_data/AMJB/coding/dw_tools/maya/DNEG2'
if not os.path.isdir(rdPath):
    rdPath = '/people/abtidona/public/dw_tools/maya/'
if not rdPath in sys.path:
    print "Add %r to sysPath" % rdPath
    sys.path.insert(0, rdPath)

# internal
from maya import cmds, mel
from collections import defaultdict

# internal

# external
import dw_alembic_utils as dwabc
import dw_json
import dw_ziva_utils as dwziva
#----------------------------------------------------------------------------#
#--------------------------------------------------------------- FUNCTIONS --#

def rfx_sys():

    ziva_dic = defaultdict(dict)
    if 'zSolver' not in cmds.ls(nt=True):
        return {}
    zsolver = cmds.ls(type='zSolver')

    for zs in zsolver:

        a7 = zs.split(':')[0]
        if not ziva_dic[a7]:
            ziva_dic[a7] = defaultdict(list)

        if 'muscle' in zs or 'fascia' in zs:
            ziva_dic[a7]['muscle'].append(zs)
        else:
            ziva_dic[a7]['skin'].append(zs)

    return ziva_dic

def create_cache(file=str, nodes=list, time_range=[], **kwargs):
    if '.abc' not in file:
        cmds.error('need a fullpath')

    limi = len(file.split('/')) - 4

    dw_json.make_chmod_dir(file.rsplit('/', 1)[0],
                           limiter = limi)
    dwabc.exportAbc(file, nodes, frameRange=time_range, samplesPerFrame=1)
    os.chmod(file, 0777)
    return file

def materialize(path):

    return dwabc.importAbc(path)

def cache_is_attached(cache_node=str, cache_name=str):
    """
    used to change the color of the cache_tree if it is connected
    Args:
        nxnode (str):
        cache_name (str):

    Returns:

    """

    nnode = cmds.ls(cache_node, type=['AlembicNode', 'rfxAlembicCacheDeformer'])
    filename_extension = ['abc_File', 'filename']
    attrs = [n + '.' + ext for ext in filename_extension for n in nnode]
    attrs = cmds.ls(attrs)
    if attrs:
        for a in attrs:
            value = cmds.getAttr(a)
            if cache_name in value:
                return True
    return False


def assign_cache(abc_target=str, file=str):
    abc_node = cmds.setAttr(abc_target + '.filename', file)
    return True


def get_preset(zsolver):
    zs = dwziva.ZSolver(zsolver)
    preset = zs.attrPreset(1)  # remove node_type dict formatting
    return preset


def load_preset(zsolver, preset=dict, blend=1):
    ns = ':'
    if ':' in zsolver:
        ns = zsolver.split(':')[0]
    zs = dwziva.ZSolver(zsolver)
    zs.loadPreset(preset=preset, blend=blend, targ_ns=ns)
