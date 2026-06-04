from pathlib import Path

# Get the package root directory
PACKAGE_ROOT = Path(__file__).parent
RESOURCES_DIR = PACKAGE_ROOT / 'ressources'

def get_resource_path(resource_name: str) -> Path:
    """
    Get absolute path for a resource file
    Args:
        resource_name (str): Name of resource file/folder
    Returns:
        Path: Absolute path to the resource
    """
    return RESOURCES_DIR / resource_name

def get_icon_path(resource_name: str, ext:str=None) -> Path:
    resource_path = get_resource_path("pic_files")
    
    name = Path(resource_name)
    if name.suffix:
        ext = name.suffix
        stem = name.stem
    else:
        stem = name.name

    for path in resource_path.rglob("*"):
        if not path.is_file():
            continue

        if path.stem != stem:
            continue

        if ext is not None and path.suffix.lower() != ext.lower():
            continue

        return path

    return None


# Validate resources directory exists
if not RESOURCES_DIR.exists():
    raise ImportError(f"Resources directory not found at {RESOURCES_DIR}")