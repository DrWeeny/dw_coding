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

# Validate resources directory exists
if not RESOURCES_DIR.exists():
    raise ImportError(f"Resources directory not found at {RESOURCES_DIR}")