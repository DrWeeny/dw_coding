import sys, os
import random
from functools import wraps

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print("Add {} to sysPath".format(rdPath))
    sys.path.insert(0, rdPath)

import maya.mel as mel
from dw_linux.dw_sound import sox_play


def complete_sound(func):
    """
    Decorator that plays a success sound when the wrapped function completes successfully,
    and plays a failure sound when the function raises an exception.

    Args:
        func (function): The function to wrap.

    Returns:
        function: The wrapped function with success/failure sound effects.
    """
    # Get the directory path where this script is located
    dir_path = os.path.dirname(os.path.realpath(__file__))
    _ress_path = os.path.join('ressources', 'audio_files', 'BattleblockTheater')
    _sound_path = os.path.join(dir_path, '..', _ress_path)

    # Fallback path handling in case the first path is incorrect
    if not os.path.isdir(_sound_path):
        _sound_path = os.path.join(rdPath, '..', '..', '..', _ress_path)

    # Get the success and failure sounds from respective directories
    try:
        _success = [os.path.join(_sound_path, '_happy', i) for i in os.listdir(os.path.join(_sound_path, '_happy')) if i.endswith('.wav')]
        _fail = [os.path.join(_sound_path, '_death', i) for i in os.listdir(os.path.join(_sound_path, '_death')) if i.endswith('.wav')]
    except FileNotFoundError as e:
        raise FileNotFoundError(f"Error: Could not find audio files. {e}")

    # Randomly select sound files
    r = random.SystemRandom()

    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            # Call the wrapped function
            result = func(*args, **kwargs)

            # Play a random success sound
            sox_play(r.choice(_success))
            return result
        except Exception as e:
            # Play a random failure sound in case of an exception
            sox_play(r.choice(_fail))
            raise e

    return wrapper
