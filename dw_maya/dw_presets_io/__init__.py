"""Maya presets I/O package for managing node attributes, connections and deformers.

This package provides functionality for saving, loading, and managing Maya node presets,
including attribute values, connections, and deformers. Supports JSON serialization
and namespace handling.

Core Functionality:
    - JSON file operations (save/load/merge/update)
    - Directory management for preset files
    - Node attribute preset creation and blending
    - Connection preset handling
    - Deformer weight management

Key Components:
    dw_folder.py:
        - Directory path management
        - User-specific folders
        - Maya project integration

    dw_json.py:
        - JSON file operations
        - Thread-safe Maya operations
        - Dictionary merging utilities

    dw_preset.py:
        - Node attribute presets
        - Connection mapping
        - Attribute blending
        - Set/group management

    dw_deformer_json.py:
        - Deformer weight export/import
        - Weight mapping and transfer
        - Multi-connection support

Example Usage:
    >>> # Save node attributes
    >>> preset = createAttrPreset(['pCube1'])
    >>> save_json('/path/preset.json', preset)
    >>>
    >>> # Load and blend attributes
    >>> data = load_json('/path/preset.json')
    >>> blendAttrDic('pCube1', 'pCube2', data, 0.5)

Functions:
    File Operations:
        get_folder(): Get preset directory path
        make_dir(): Create directory structure
        save_json(): Save data to JSON file
        load_json(): Load data from JSON file
        merge_json(): Merge data with existing JSON
        update_json(): Update specific JSON keys

    Preset Management:
        createAttrPreset(): Create node attribute preset
        blendAttrDic(): Blend attribute values between nodes
        createConnectionPreset(): Create connection mapping
        reconnectPreset(): Restore connections from preset

Author: DrWeeny
Version: 1.0.0
"""

from .dw_folder import get_folder, make_dir
from .dw_json import save_json, load_json, merge_json, update_json
from .dw_preset import createAttrPreset, blendAttrDic

__all__ = ['get_folder', 'make_dir', 'save_json', 'load_json',
           'merge_json', 'update_json', 'createAttrPreset', 'blendAttrDic']
