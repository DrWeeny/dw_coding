"""Provides utilities for mesh manipulation operations in Maya.

A module focused on mesh operations like face extraction and mesh separation,
with robust error handling and progress tracking for large operations.

Functions:
    extract_faces(): Extract and separate faces from a mesh
    separate_mesh(): Split combined mesh into individual objects

Main Features:
    - Face extraction with validation
    - Mesh separation with history control
    - Progress tracking for large operations
    - Robust error handling and logging

Version: 1.0.0

Author:
    DrWeeny
"""

from typing import List, Optional, Union
from pathlib import Path

from maya import cmds

from dw_logger import get_logger

logger = get_logger()


def extract_faces(faces: Union[List[str], str],
                  source_mesh: str,
                  keep_history: bool = False,
                  offset: float = 0.0) -> List[str]:
    """Extract and separate faces from a mesh into new objects.

    Extracts specified faces from a mesh and creates new mesh objects.
    Handles both single and multiple face selections.

    Args:
        faces: Face components to extract (e.g., ["pSphere1.f[0:5]"])
        source_mesh: Source mesh to extract faces from
        keep_history: Keep construction history on resulting meshes
        offset: Offset amount for extracted faces

    Returns:
        List of newly created mesh transform nodes

    Raises:
        ValueError: If no valid faces are provided
        RuntimeError: If source mesh doesn't exist
    """
    try:
        # Validate inputs
        if isinstance(faces, str):
            faces = [faces]

        if not faces:
            raise ValueError("No faces provided for extraction")

        if not cmds.objExists(source_mesh):
            raise RuntimeError(f"Source mesh '{source_mesh}' does not exist")

        # Validate each face component
        for face in faces:
            if not cmds.objExists(face):
                logger.warning(f"Face component '{face}' does not exist")

        logger.info(f"Extracting {len(faces)} face(s) from {source_mesh}")

        # Perform extraction
        cmds.polyChipOff(
            faces,
            constructionHistory=keep_history,
            keepFacesTogether=True,
            duplicate=False,
            offset=offset
        )

        # Separate into objects
        cmds.polySeparate(
            faces[0].split('.')[0],
            removeShells=True,
            constructionHistory=keep_history
        )

        # Get resulting meshes
        result_meshes = list(set([
            cmds.listRelatives(mesh, parent=True)[0]
            for mesh in cmds.ls(source_mesh, dagObjects=True, type="mesh")
        ]))

        # Clean up history if not keeping
        if not keep_history:
            for mesh in result_meshes:
                cmds.delete(mesh, constructionHistory=True)

        logger.info(f"Successfully created {len(result_meshes)} mesh(es)")
        return result_meshes

    except Exception as e:
        logger.error(f"Error during face extraction: {e}")
        raise


def separate_mesh(mesh: str,
                  keep_history: bool = False,
                  rename_parts: bool = True,
                  prefix: Optional[str] = None) -> List[str]:
    """Separate a combined mesh into individual mesh objects.

    Splits a combined mesh into its constituent parts, with options for
    history preservation and naming.

    Args:
        mesh: Mesh to separate
        keep_history: Keep construction history on resulting meshes
        rename_parts: Automatically rename separated parts
        prefix: Optional prefix for renamed parts

    Returns:
        List of separated mesh transform nodes

    Raises:
        RuntimeError: If source mesh doesn't exist
    """
    try:
        # Validate input mesh
        if not cmds.objExists(mesh):
            raise RuntimeError(f"Mesh '{mesh}' does not exist")

        logger.info(f"Separating mesh: {mesh}")

        # Get initial state
        orig_parts = cmds.ls(type="mesh")

        # Perform separation
        separated = cmds.polySeparate(
            mesh,
            constructionHistory=keep_history
        )

        # Get actual new meshes by comparing with initial state
        new_parts = [
            mesh for mesh in cmds.ls(type="mesh")
            if mesh not in orig_parts
        ]

        # Get transform nodes
        result_meshes = [
            cmds.listRelatives(part, parent=True)[0]
            for part in new_parts
        ]

        # Clean up history if not keeping
        if not keep_history:
            for mesh in result_meshes:
                cmds.delete(mesh, constructionHistory=True)

        # Rename parts if requested
        if rename_parts:
            prefix = prefix or f"{mesh}_part"
            for i, part in enumerate(result_meshes):
                new_name = f"{prefix}_{i + 1}"
                result_meshes[i] = cmds.rename(part, new_name)

        logger.info(f"Successfully separated into {len(result_meshes)} mesh(es)")
        return result_meshes

    except Exception as e:
        logger.error(f"Error during mesh separation: {e}")
        raise
