import subprocess
import os.path
import re


def abcls_inspect(abc_path, object_path="/", recursive=True, verbose=False):
    """
    Run abcls command to inspect Alembic file at a specific path.

    Args:
        abc_path: Path to Alembic file
        object_path: Internal object path to inspect (default: "/" for root)
        recursive: List hierarchy recursively with -r flag
        verbose: Show detailed property info with -v flag

    Returns:
        list: Lines of abcls output (cleaned of ANSI codes)
    """
    cmd = ["abcls"]

    if recursive:
        cmd.append("-r")  # -r for recursive, -l is just long format
    if verbose:
        cmd.append("-v")

    # Combine file path and object path
    cmd.append(f"{abc_path}{object_path}")

    try:
        output = subprocess.check_output(cmd)
        # Clean ANSI escape codes from output
        clean_output = re.sub(r'\x1b\[[0-9;]*m', '', output)
        return [line for line in clean_output.strip().split('\n') if line.strip()]
    except Exception as e:
        print(f"Failed to inspect {abc_path}: {e}")
        return []


def get_alembic_hierarchy(abc_path):
    """
    Get full hierarchy of objects in an Alembic file.

    Args:
        abc_path: Path to Alembic file

    Returns:
        list: All object paths in the archive
    """
    return abcls_inspect(abc_path, object_path="/", recursive=True)


def find_yeti_objects(abc_path):
    """
    Find Yeti-related objects in an Alembic file.

    Searches for objects with 'yeti', 'pgYeti', 'fur', 'hair', 'curve' in their names
    or schemas that indicate Yeti/groom data.

    Args:
        abc_path: Path to Alembic file

    Returns:
        list: Object paths that may contain Yeti data
    """
    hierarchy = get_alembic_hierarchy(abc_path)

    yeti_keywords = ['yeti', 'pgyeti', 'fur', 'groom', 'guide']
    curve_keywords = ['curve', 'nurbscurve']

    yeti_objects = []
    curve_objects = []

    for line in hierarchy:
        lower_line = line.lower()

        # Check for Yeti-specific naming
        if any(keyword in lower_line for keyword in yeti_keywords):
            yeti_objects.append(line)
        # Check for curve data (Yeti often exports as curves)
        elif any(keyword in lower_line for keyword in curve_keywords):
            curve_objects.append(line)

    return {
        'yeti': yeti_objects,
        'curves': curve_objects,
        'full_hierarchy': hierarchy
    }


def inspect_alembic_contents(abc_path):
    """
    Detailed inspection of Alembic file contents for CFX validation.

    Args:
        abc_path: Path to Alembic file

    Returns:
        dict: Inspection results with hierarchy, yeti objects, and mesh info
    """
    print(f"Inspecting: {abc_path}")
    print("=" * 60)

    # Get full hierarchy
    hierarchy = get_alembic_hierarchy(abc_path)

    # Categorize objects
    results = {
        'path': abc_path,
        'yeti': [],
        'curves': [],
        'meshes': [],
        'xforms': [],
        'other': []
    }

    for line in hierarchy:
        lower_line = line.lower()

        if 'yeti' in lower_line or 'pgyeti' in lower_line:
            results['yeti'].append(line)
        elif 'curve' in lower_line:
            results['curves'].append(line)
        elif 'polymesh' in lower_line or 'subdiv' in lower_line:
            results['meshes'].append(line)
        elif 'xform' in lower_line:
            results['xforms'].append(line)
        else:
            results['other'].append(line)

    # Print summary
    print(f"Yeti objects: {len(results['yeti'])}")
    for obj in results['yeti']:
        print(f"  - {obj}")

    print(f"\nCurves: {len(results['curves'])}")
    for obj in results['curves'][:10]:  # Limit output
        print(f"  - {obj}")
    if len(results['curves']) > 10:
        print(f"  ... and {len(results['curves']) - 10} more")

    print(f"\nMeshes: {len(results['meshes'])}")
    for obj in results['meshes'][:10]:
        print(f"  - {obj}")
    if len(results['meshes']) > 10:
        print(f"  ... and {len(results['meshes']) - 10} more")

    print("=" * 60)

    return results


#
# # Get full hierarchy
# hierarchy = get_alembic_hierarchy(abc_file)
# for item in hierarchy:
#     print(item)
#
# # Find Yeti-specific objects
# yeti_info = find_yeti_objects(abc_file)
# print(f"Yeti objects found: {yeti_info['yeti']}")
#
# # Full inspection with summary
# results = inspect_alembic_contents(abc_file)
