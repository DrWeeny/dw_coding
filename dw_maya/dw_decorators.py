# -*- coding: utf-8 -*-
"""Example Google style docstrings.

This module provide a list of decorators that can be used in other scripts

Example:
      ``@timeIt
        @acceptString('objSel')
        def createOffsetGrp(test, objSel=['pSphere1']):
            for obj in objSel:
                p = cmds.listRelatives(obj)
                print (p)

        createOffsetGrp(0, 'pSphere1')``

        $ https://gist.github.com/kissgyorgy/d080ad6d1aba50d89f76

Section breaks are created by resuming unindented text. Section breaks
are also implicitly created anytime a new section starts.

Attributes:
    module_level_variable1 (int): Module level variables may be documented in
        either the ``Attributes`` section of the module docstring, or in an
        inline docstring immediately following the variable.

        Either form is acceptable, but the two should not be mixed. Choose
        one convention to document module level variables and be consistent
        with it.

Todo:
    * For module TODOs
    * You have to also use ``sphinx.ext.todo`` extension

.. _Google Python Style Guide:
   http://google.github.io/styleguide/pyguide.html

"""

import sys, os

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print("Add {} to sysPath".format(rdPath))
    sys.path.insert(0, rdPath)

import inspect
import time
from functools import wraps
import os
import maya.mel as mel
import datetime
import random
import maya.cmds as cmds

from dw_maya.dw_widgets import ErrorWin
from dw_linux.dw_sound import sox_play


def acceptString(*list_args):
    """
    Convert given parameter to a list if it is provided as a string.

    Args:
        *list_args (str): The argument names to convert to a list if they are strings.

    Returns:
        A decorator that ensures the specified arguments are converted to a list.
    """

    def convert_params_to_list(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Get the signature of the function and bind the arguments
            sig = inspect.signature(func)
            bound_args = sig.bind(*args, **kwargs)
            bound_args.apply_defaults()

            # Iterate over the specified list_args
            for list_arg in list_args:
                if list_arg in bound_args.arguments:
                    value = bound_args.arguments[list_arg]

                    # Convert the argument to a list if it's a string
                    if isinstance(value, str):
                        bound_args.arguments[list_arg] = [value]

            # Call the original function with modified arguments
            return func(*bound_args.args, **bound_args.kwargs)

        return wrapper

    return convert_params_to_list


def viewportOff(func):
    """
    Decorator to turn off Maya's viewport while the decorated function runs.
    If the function raises an error, the error is propagated, but the viewport
    will always be turned back on at the end, ensuring Maya's display is not left off.

    Args:
        func (function): The function to wrap.

    Returns:
        function: The wrapped function with the viewport off during its execution.
    """

    @wraps(func)
    def wrap(*args, **kwargs):
        try:
            # Turn the viewport (gMainPane) off
            mel.eval("paneLayout -e -manage false $gMainPane")

            # Execute the wrapped function
            return func(*args, **kwargs)

        except Exception as e:
            # Optionally log the error here if needed
            print(f"Error during execution of {func.__name__}: {e}")
            raise  # Re-raise the original error

        finally:
            # Turn the viewport back on
            mel.eval("paneLayout -e -manage true $gMainPane")

    return wrap


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

def timeIt(func):
    """
    Decorator to measure and print the execution time of a function in milliseconds.

    Args:
        func (function): The function to be wrapped.

    Returns:
        function: The wrapped function that prints its execution time after running.
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.time()  # Start the timer
        result = func(*args, **kwargs)  # Execute the function
        end = time.time()  # End the timer

        elapsed = (end - start) * 1000  # Calculate elapsed time in milliseconds
        print(f'{func.__name__} took {elapsed:.4f} ms to execute.')
        return result

    return wrapper


def printDate(func):
    """
    Decorator to print the current date and time after a function has finished executing.

    Args:
        func (function): The function to wrap.

    Returns:
        function: The wrapped function with a date and time printout after execution.
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        # Execute the wrapped function
        result = func(*args, **kwargs)

        # Get the current date and time
        t = datetime.datetime.now()

        # Print the function name and the current date and time
        print(f'# Function "{func.__name__}" finished on: {t:%d, %b %Y} at {t:%H:%M:%S}')
        return result

    return wrapper


def returnNodeDiff(func):
    """
    Decorator that tracks the difference in Maya nodes before and after
    the execution of the wrapped function, returning any newly created nodes.

    Args:
        func (function): The function to wrap.

    Returns:
        function: The wrapped function with a list of new nodes created.
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        # Get the list of nodes before the function runs
        nodes_before = set(cmds.ls())

        # Execute the wrapped function
        result = func(*args, **kwargs)

        # Get the list of nodes after the function runs
        nodes_after = set(cmds.ls())

        # Calculate the difference (new nodes created)
        node_diff = list(nodes_after - nodes_before)

        # Return both the function result and the list of new nodes
        return result, node_diff

    return wrapper


def singleUndoChunk(func):
    """
    Decorator to group the wrapped function's operations into a single Maya Undo chunk.
    This ensures that all operations performed by the function can be undone in a single
    step in Maya's undo queue.

    Args:
        func (function): The function to wrap.

    Returns:
        function: The wrapped function that executes within a single undo chunk.
    """
    @wraps(func)
    def _undofunc(*args, **kwargs):
        try:
            # start an undo chunk
            cmds.undoInfo(openChunk=True)
            return func(*args, **kwargs)
        finally:
            # after calling the func, end the undo chunk and undo
            cmds.undoInfo(closeChunk=True)

    return _undofunc
    # return lambda *args, **kwargs: executeDeferred(wrap, *args, **kwargs)


def repeatable(function):
    """
    A decorator that makes commands repeatable in Maya.

    Source: http://blog.3dkris.com/2011/08/python-in-maya-how-to-make-commands.html

    Args:
        function (function): The function to wrap and make repeatable.

    Returns:
        function: The wrapped function.
    """

    @wraps(function)
    def decoratorCode(*args, **kwargs):
        # Generate the argument string for the repeatable command
        arg_list = [repr(arg) for arg in args]
        kwarg_list = [f'{key}={repr(value)}' for key, value in kwargs.items()]
        argString = ', '.join(arg_list + kwarg_list)

        # Construct the command string for repeatLast
        commandToRepeat = f'python("{__name__}.{function.__name__}({argString})")'

        # Execute the original function
        functionReturn = function(*args, **kwargs)

        try:
            # Register the repeatable command in Maya's repeatLast
            cmds.repeatLast(ac=commandToRepeat, acl=function.__name__)
        except Exception as e:
            print(f"Error registering command to repeatLast: {e}")

        return functionReturn

    return decoratorCode


def vtxAnimDetection(argument):
    """
    Decorator to detect vertex animation on a given mesh.

    If vertex animation is detected, it cancels the deformer command.

    Args:
        argument (str): The name of the mesh you want to detect vertex animation on.

    Returns:
        function: The wrapped function, if no vertex animation is detected.
    """

    def decorator(function):
        @wraps(function)
        def wrapper(*args, **kwargs):
            msg_error = "Vertex animation detected, canceling deformer command"

            # Check if the argument has a valid shape node
            mesh_shape = cmds.listRelatives(argument, s=True)
            if not mesh_shape:
                print(f"Error: {argument} does not have a valid shape node.")
                return
            mesh_shape = mesh_shape[0]

            vtx_component  = cmds.ls(f"{mesh_shape}_pnts_*__pntx", fl=1)
            # check on tweak level too because you could be evil
            tweak_node = cmds.listConnections(mesh_shape, type='tweak')

            if vtx_component:
                print(msg_error)
                err = ErrorWin()
                return

                cmds.error()
            elif tweak_node:
                tweak_vtx_component = cmds.ls(f"{tweak_node[-1]}_vlist_*__xVertex", fl=1)
                if tweak_vtx_component:
                    print(msg_error)
                    err = ErrorWin()
                    return

            return function(*args, **kwargs)
        return wrapper
    return decorator


def load_plugin(argument=str):
    """
    Decorator to ensure that a specific Maya plugin is loaded before executing the function.

    Args:
        argument (str): The name of the Maya plugin to check and load if necessary.

    Returns:
        function: The wrapped function that ensures the plugin is loaded.
    """

    def decorator(function):
        @wraps(function)
        def wrapper(*args, **kwargs):
            # Check if the plugin is already loaded
            is_loaded = cmds.pluginInfo(argument, query=True, loaded=True)

            # If not loaded, try to load the plugin
            if not is_loaded:
                try:
                    cmds.loadPlugin(argument, quiet=True)
                    is_loaded = cmds.pluginInfo(argument, query=True, loaded=True)

                    # Provide feedback if the plugin failed to load
                    if not is_loaded:
                        raise RuntimeError(f"Failed to load plugin: {argument}")

                except RuntimeError as e:
                    print(f"Error loading plugin '{argument}': {e}")
                    cmds.error(f"Could not load required plugin: {argument}")
                    return None

            # If the plugin is loaded, proceed with the function
            return function(*args, **kwargs)

        return wrapper

    return decorator
