"""
Maya Data Utilities

Collection of utilities for manipulating and processing data in Maya environments.
Includes functions for name generation, list flattening, dictionary operations, and flag handling.
"""

import re
from maya import cmds
from typing import List, Dict, Any, Union, Optional, Tuple
import itertools
from dw_maya.dw_decorators import acceptString


#----------------------------------------------------------------------------#
#--------------------------------------------------------------- FUNCTIONS --#


def flatten_list(nested_lists: List[Any]) -> List[Any]:
    """
    Flatten a list of nested lists into a single list.

    Args:
        nested_lists: List containing other lists

    Returns:
        Flattened list

    Example:
        >>> flatten_list([[1, 2], [3, 4]])
        [1, 2, 3, 4]
    """
    return list(itertools.chain(*nested_lists))

@acceptString('sel')
def unique_name(sel: Union[str, List[str]],
                prefix: str = '',
                suffix: str = '',
                **kwargs) -> List[Tuple[str, str]]:
    """
    Generate unique names for Maya objects with frame number and version.

    Args:
        sel: Object(s) to rename
        prefix: Optional prefix for new names
        suffix: Optional suffix for new names
        **kwargs:
            pattern: Custom regex pattern for name matching
            forbiddenName: Additional names to consider taken

    Returns:
        List of [original_name, new_name] pairs

    Example:
        >>> unique_name(['pSphere1'], prefix='sim')
        [['pSphere1', 'sim_pSphere1_001_v1']]
    """
    output: List[Tuple[str, str]] = []

    frame = f"{int(cmds.currentTime(q=True)):03d}"
    dup_pattern = re.compile('_\d{3}_v\d{1,2}$')

    for obj in sel:
        # Handle custom pattern or generate default
        if pattern := kwargs.get('pattern'):
            name_pattern = pattern
        else:
            # Strip namespace and attributes
            base_name = obj.split('.')[-1].split(':')[-1]
            if re.search(f'_{frame}_v\\d{{1}}$', base_name):
                base_name = '_'.join(base_name.split('_')[:-2])
            name_pattern = f'^{base_name}_{frame}_v\\d{{1,2}}$'

        # Get existing objects to check against
        existing = (kwargs.get('forbiddenName', []) +
                    cmds.ls(type='transform'))

        # Find highest version number
        pattern = re.compile(name_pattern)
        versions = [
            int(i[-1]) for i in existing
            if pattern.search(i)
        ]
        version = max(versions, default=0) + 1

        # Generate new name
        if dup_pattern.search(obj.split(':')[-1]):
            new_name = dup_pattern.sub(
                f'_{frame}_v{version}',
                obj.split(':')[-1]
            )
        else:
            new_name = f'{obj.split(":")[-1]}_{frame}_v{version}'

        # Add prefix/suffix
        if prefix:
            new_name = f'{prefix}_{new_name}'
        if suffix:
            new_name = f'{new_name}_{suffix}'

        # Clean up recipe tag if present
        new_name = new_name.replace('_recipe_', '_')

        output.append([obj, new_name])

    return output


def convert_list_to_mel_str(items: List[Any]) -> str:
    """
    Convert Python list to MEL array string format.

    Args:
        items: List of items to convert

    Returns:
        MEL array string

    Example:
        >>> convert_to_mel_array([1, "sphere", 2.5])
        '{1,"sphere",2.5}'
    """
    output = []
    for i in items:
        if isinstance(i, (float, int)):
            output.append(str(i))
        elif isinstance(i, list):
            # {"sphere", "cube", "torus"}
            '{' + ','.join(['"{0}"'.format(k) for k in i]) + '}'
        else:
            output.append('"{}"'.format(i))

    return '{' + ','.join(output) + '}'


def merge_two_dicts(x, y):
    """
    Merge two dictionaries, with dict2 taking precedence.

    Args:
        dict1: First dictionary
        dict2: Second dictionary (overrides dict1)

    Returns:
        Merged dictionary

    Example:
        >>> merge_dicts({'a': 1}, {'b': 2})
        {'a': 1, 'b': 2}
    """
    try:
        return {**x, **y}  # For Python 3.5+
    except TypeError:
        # Fallback for older Python versions (including Python 2)
        z = x.copy()  # start with x's keys and values
        z.update(y)   # modifies z with y's keys and values
        return z


def flags(kwarg_dic: dict,
          default_value=None,
          label_long: str = "",
          label_short: str = "",
          *args,
          **kwargs):
    """
    Advanced flag handler supporting merging, key selection, and duplicate checks.

    Args:
        kwarg_dic: Dictionary containing flags
        default_value: Default value if flag not found
        label_long: Long name of the flag
        label_short: Short name of the flag
        dic or dictionnary : for merging
        k or key : for key selection
        *args: Additional flag name aliases
        **kwargs
    Returns:
        Flag value, or dictionary with merged values

    Examples:
        # Basic flag lookup
        flags({'name': 'sphere1'}, None, 'name')  # Returns 'sphere1'

        # Using short name alternative
        flags({'n': 'sphere1'}, 'default', 'name', 'n')  # Returns 'sphere1'

        # Dictionary merging
        flags({'name': 'sphere1'}, None, 'name', dic={'material': 'lambert'})
        # Returns {'name': 'sphere1', 'material': 'lambert'}

        # Key renaming
        flags({'name': 'sphere1'}, None, 'name', key='object_name', dic={})
        # Returns {'object_name': 'sphere1'}
    """

    flags = {}
    used_key = None
    CURRENT_KEY = None

    # Handle key/dic logic
    keyKey = kwargs.get('key') or kwargs.get('k')
    keyDic = kwargs.get('dic') or kwargs.get('dictionnary')
    if keyKey and not keyDic:
        kwargs['dic'] = {}

    # Dictionary merging functionality
    if 'dic' in kwargs or 'dictionnary' in kwargs:
        used_key = 'dic' if 'dic' in kwargs else 'dictionnary'
        all_labels = [label_long, label_short] + list(args)
        all_labels = [lb for lb in all_labels if lb]
        detected = []
        for lb in all_labels:
            if lb and lb in kwargs[used_key]:
                value = kwargs[used_key].get(lb)
                CURRENT_KEY = keyKey or lb
                flags[CURRENT_KEY] = value
                detected.append(lb)
        if len(detected) > 1:
            cmds.error('Found multiple keys to update')
    if not flags:
        CURRENT_KEY = keyKey or label_long

    # Merge dictionary input
    if used_key:
        if CURRENT_KEY:
            dic_input = kwargs.get(used_key) or {}
            flags = merge_two_dicts(dic_input, flags)
        else:
            cmds.error('You must specify a key with "key" or "k"')

    # Check flags or return default
    if label_long and label_long in kwarg_dic:
        if used_key:
            if kwarg_dic.get(label_long) is not None:
                flags[CURRENT_KEY] = kwarg_dic.get(label_long)
                return flags
        else:
            return kwarg_dic.get(label_long)
    elif label_short and label_short in kwarg_dic:
        if used_key:
            if kwarg_dic.get(label_short) is not None:
                flags[CURRENT_KEY] = kwarg_dic.get(label_short)
                return flags
        else:
            return kwarg_dic.get(label_short)
    elif any([a in kwarg_dic for a in args if a]):
        for a in args:
            if a and a in kwarg_dic:
                if not flags and not used_key:
                    return kwarg_dic.get(a)
                else:
                    if kwarg_dic.get(a) is not None:
                        flags[CURRENT_KEY] = kwarg_dic.get(a)
                    return flags

    if not flags and not used_key:
        return default_value
    else:
        if default_value is not None and CURRENT_KEY and CURRENT_KEY not in flags:
            flags[CURRENT_KEY] = default_value
        return flags