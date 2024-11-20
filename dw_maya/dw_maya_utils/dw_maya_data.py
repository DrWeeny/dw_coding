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


def flags(kwargs: dict,
          default: Any = None,
          long_name: str = "",
          short_name: str = "") -> Any:
    """
    Get flag value from kwargs, supporting Maya-style short/long flags.

    Args:
        kwargs: Keyword arguments dictionary
        long_name: Long version of flag name
        short_name: Short version of flag name
        default: Default value if flag not found

    Returns:
        Flag value or default

    Example:
        >>> flags({'l': True}, 'long', 'l', False)
        True
    """
    # Check for long name first
    if long_name in kwargs:
        if short_name in kwargs:
            raise ValueError(f"Flag used twice: {long_name} and {short_name}")
        return kwargs[long_name]

    # Check short name
    if short_name in kwargs:
        return kwargs[short_name]

    return default