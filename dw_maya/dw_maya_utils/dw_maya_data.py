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

import re

# internal
from maya import cmds, mel
import itertools
import maya.OpenMaya as om
from dw_maya.dw_decorators import acceptString


#----------------------------------------------------------------------------#
#--------------------------------------------------------------- FUNCTIONS --#

def flattenlist(nested_lists=list):
    return list(itertools.chain(*nested_lists))

@acceptString('sel')
def unique_name(sel=list, prefix='', suffix='', **kwargs):
    """ used to give a unique name with frame + version

    Args:
        sel: can give unique name on a list of object
        prefix: can give a prefix
        suffix: can give a suffix
        **kwargs: not implemented

    Returns:
        list: nested lists with index 0 = src, index 1 = new_name

    """
    output = []

    frame = '{:03d}'.format(int(cmds.currentTime(q=True)))
    dup_pattern = re.compile('_\d{3}_v\d{1,2}$')
    for s in sel:
        if kwargs.get('pattern'):
            pattern = kwargs['pattern']
        else:
            # name : strip any .attr and any ::namespace
            name = s.split('.')[0].split(':')[-1]
            if re.search('_{frame}_v\d{{1}}$'.format(frame=frame), name):
                name = '_'.join(name.split('_')[:-2])
            pattern = '^{name}_{frame}_v\d{{1,2}}$'.format(name=name,
                                                           frame=frame)

        if not kwargs.get('forbiddenName'):
            exists = cmds.ls(type='transform')
        else:
            exists = cmds.ls(type='transform') + kwargs['forbiddenName']

        p = re.compile(pattern)
        detect = sorted([i[-1] for i in exists if p.search(i)])
        if detect:
            _iter = int(detect[-1]) + 1
        else:
            _iter = '1'

        if dup_pattern.search(s.split(':')[-1]):
            new = dup_pattern.sub(
                '_{frame}_v{iter}'.format(frame=frame, iter=_iter),
                s.split(':')[-1])
        else:
            new = '{name}_{frame}_v{iter}'.format(name=s.split(':')[-1],
                                                  frame=frame,
                                                  iter=_iter)
        if prefix != '':
            new = '{0}_{1}'.format(prefix, new)
        if suffix != '':
            new = '{0}_{1}'.format(new, suffix)

        recipe = re.compile('_recipe_')
        new = recipe.sub('_', new)

        output.append([s, new])

    return output


def convert_list_to_mel_str(_input=list):
    output = []
    for i in _input:
        if type(i) is float or type(i) is int:
            output.append(str(i))
        elif type(i) is list:
            # {"sphere", "cube", "torus"}
            '{' + ','.join(['"{0}"'.format(k) for k in i]) + '}'
        else:
            output.append('"{}"'.format(i))

    return '{' + ','.join(output) + '}'


def merge_two_dicts(x, y):
    """
    Merges two dictionaries. Uses the more efficient syntax in Python 3.5+.
    """
    # Python 3.5+ has the {**x, **y} syntax for merging dicts.
    try:
        return {**x, **y}  # For Python 3.5+
    except TypeError:
        # Fallback for older Python versions (including Python 2)
        z = x.copy()  # start with x's keys and values
        z.update(y)   # modifies z with y's keys and values
        return z


def Flags(kwarg_dic=dict, default_value=None, label_long=str, *args, **kwargs):
    """
    Function to handle flags and keyword arguments, returning either a dictionary
    of flags or the value of a specific flag.

    Args:
        kwarg_dic (dict): The dictionary of keyword arguments to process.
        default_value: The default value to return if no flag is found.
        label_long (str): The primary flag label to search for in the dictionary.
        *args: Additional flag labels to search for in the dictionary.
        **kwargs: Optional settings for dictionary processing, such as 'key' and 'dic'.

    Returns:
        dict: A dictionary of processed flags or a single flag value.
    """
    if kwarg_dic is None:
        kwarg_dic = {}

    used_key = None
    CURRENT_KEY = None
    flags = {}

    # handling the case where only key has been given
    keyKey = kwargs.get('key') or kwargs.get('k') or None
    keyDic = kwargs.get('dic') or kwargs.get('dictionnary') or None

    if keyKey and not keyDic:
        kwargs['dic'] = {}

    # If there is a dic specified in the command, lets sort this out
    # and output at the end a dicionnary
    # if there is no label detected to update,
    # it will create a default entry with the labelLong
    # We can also update another key by specifying the key
    if 'dic' in kwargs or 'dictionnary' in kwargs:
        used_key = 'dic' or 'dictionnary' in kwargs
        all_labels = [label_long]
        if args:
            all_labels += args
        detected = []

        for lb in all_labels:
            if lb in kwargs[used_key]:
                value = kwargs[used_key].get(lb)
                if 'key' in kwargs or 'k' in kwargs:
                    KEY = kwargs.get('key') or kwargs.get('k')
                    CURRENT_KEY = KEY
                else:
                    CURRENT_KEY = lb
                flags[CURRENT_KEY] = value
                detected.append(lb)
        if len(detected) > 1:
            cmds.error('found multiple key to update')
    if not flags:
        if 'key' in kwargs or 'k' in kwargs:
            KEY = kwargs.get('key') or kwargs.get('k')
            CURRENT_KEY = KEY
        else:
            CURRENT_KEY = label_long

    # do the merge if a dictionnary has been input
    if used_key:
        if CURRENT_KEY:
            dic_input = kwargs.get(used_key) or {}
            flags = merge_two_dicts(dic_input, flags)
        else:
            cmds.error('you must specify a key in the command'
                       ' with kwargs "key" or "k"')

    # Check if argument is not used twice
    if args:
        if any(a in kwarg_dic for a in args) and label_long in kwarg_dic:
            cmds.error("Same flag used two times")

    # check the flags or return the default value
    # each if return a straight value or a dictionnary
    # for dictionnary, it will return the key only if there is a value,
    # False or 0
    if label_long in kwarg_dic:
        if used_key:
            if kwarg_dic.get(label_long) is not None:
                flags[CURRENT_KEY] = kwarg_dic.get(label_long)
                return flags
        else:
            return kwarg_dic.get(label_long)

    for a in args:
        if a in kwarg_dic:
            if not flags and not used_key:
                return kwarg_dic.get(a)
            else:
                if kwarg_dic.get(a) is not None:
                    flags[CURRENT_KEY] = kwarg_dic.get(a)
                return flags

    if not flags and not kwargs:
        return default_value
    else:
        if default_value is not None:
            flags[CURRENT_KEY] = default_value
        return flags