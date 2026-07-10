from pathlib import Path

# Get the package root directory
PACKAGE_ROOT = Path(__file__).parent
RESOURCES_DIR = PACKAGE_ROOT / 'ressources'


def _find_resource(resource_name: str, root: Path = None) -> Path:
    """
    Recursively search a resource file by name under `root`.

    Matches on filename stem; if `resource_name` carries an extension,
    the extension must match too (case-insensitive). First hit wins.

    Args:
        resource_name (str): File name, with or without extension.
        root (Path): Directory to search. Defaults to RESOURCES_DIR.

    Returns:
        Path: Path of the first matching file, or None if not found.
    """
    root = root or RESOURCES_DIR
    name = Path(resource_name)

    if name.suffix:
        ext = name.suffix
        stem = name.stem
    else:
        stem = name.name
        ext = None

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.stem != stem:
            continue
        if ext is not None and path.suffix.lower() != ext.lower():
            continue
        return path

    return None


def get_resource_path(resource_name: str) -> Path:
    """
    Get absolute path for a resource file or folder.

    Resolution order:
        1. Direct join `ressources/<resource_name>` if it exists
           (works for folders and explicit relative paths).
        2. Recursive search by file name anywhere under `ressources/`
           (so callers don't need to know the sub-hierarchy).
        3. Fallback to the direct join (non-existing) so the caller
           always gets a Path, never None.

    Args:
        resource_name (str): Resource file/folder name or relative path.

    Returns:
        Path: Absolute path to the resource.
    """
    direct = RESOURCES_DIR / resource_name
    if direct.exists():
        return direct

    found = _find_resource(resource_name)
    if found is not None:
        return found

    return direct


# Deprecated: typo alias kept for backward compatibility.
get_ressource_path = get_resource_path


def get_icon_path(resource_name: str, ext: str = None) -> Path:
    if ext and not Path(resource_name).suffix:
        resource_name = f"{resource_name}{ext if ext.startswith('.') else '.' + ext}"
    return _find_resource(resource_name,
                          root=RESOURCES_DIR / "pic_files")


# Validate resources directory exists
if not RESOURCES_DIR.exists():
    raise ImportError(f"Resources directory not found at {RESOURCES_DIR}")


def _as_fs_path(value) -> str:
    """Return a Qt-friendly filesystem path string (handles pathlib paths)."""
    import os
    if not value:
        return ''
    return str(os.fspath(value))