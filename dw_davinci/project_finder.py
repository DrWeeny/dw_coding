"""
find_davinci_libraries.py

Locates DaVinci Resolve "Disk Database" project libraries buried inside your
workspace folders, so you can re-add them via:
    Project Manager -> Project Libraries panel -> "+" -> Add Existing Library
    (then browse to the LIBRARY ROOT path this script prints)

Background:
    A Resolve disk-database library is just a folder. Inside it, projects live
    at:
        <library root>\\Resolve Projects\\Users\\<user>\\Projects\\<ProjectName>\\Project.db
    The "Local Database" entry you see in the Projects panel points at
    <library root> -- NOT at the Project.db file itself. If you point Resolve
    at the wrong level (e.g. straight at "Resolve Projects", or one level too
    high), it doesn't recognize the existing structure and quietly creates a
    fresh empty one instead -- that's the "empty hierarchy" you're seeing.

This script finds every "Resolve Projects" folder under your given roots,
reports the library root (its parent), and lists every real project
(Project.db) found inside, so you know exactly what path to feed back into
Resolve and what should show up once you do.

Usage:
    python find_davinci_libraries.py
    python find_davinci_libraries.py --roots "D:\\other_path" "D:\\dw_workspace\\davinci"
"""

import argparse
import os
import sys
from pathlib import Path

DEFAULT_ROOTS = [
    r"D:\dw_workspace\davinci",
    r"D:\dw_workspace\davinci_workspace",
]

RESOLVE_PROJECTS_DIRNAME = "resolve projects"
PROJECT_DB_FILENAME = "project.db"

# Directory the script itself lives in, regardless of the current working
# directory the user launched python from.
SCRIPT_DIR = Path(__file__).resolve().parent
REPORT_DIR = SCRIPT_DIR / "report"


def find_libraries(root: Path):
    """Yield (library_root, resolve_projects_dir) for any 'Resolve Projects' folder under root."""
    root = root.resolve()
    if not root.exists():
        print(f"  [!] Root does not exist, skipping: {root}", file=sys.stderr)
        return

    for dirpath, dirnames, _filenames in os.walk(root):
        for d in dirnames:
            if d.lower() == RESOLVE_PROJECTS_DIRNAME:
                lib_root = Path(dirpath)
                yield lib_root, Path(dirpath) / d


def find_orphan_project_dbs(root: Path, known_lib_roots):
    """Find Project.db files not sitting under any already-detected library root."""
    root = root.resolve()
    if not root.exists():
        return

    known_prefixes = [str(r).lower() for r in known_lib_roots]

    for dirpath, _dirnames, filenames in os.walk(root):
        for fname in filenames:
            if fname.lower() == PROJECT_DB_FILENAME:
                full = Path(dirpath) / fname
                if not any(str(full).lower().startswith(p) for p in known_prefixes):
                    yield full


def list_projects_under(resolve_projects_dir: Path):
    """Walk a 'Resolve Projects' folder and return list of (project_name, project_db_path)."""
    projects = []
    for dirpath, _dirnames, filenames in os.walk(resolve_projects_dir):
        for fname in filenames:
            if fname.lower() == PROJECT_DB_FILENAME:
                project_folder = Path(dirpath)
                projects.append((project_folder.name, project_folder / fname))
    return projects


WRAPPER_NAME_PREFIX = "resolve project library"


def find_wrapper_folders(root: Path):
    """Yield every folder whose name starts with 'Resolve Project Library'
    (the auto-created wrapper Resolve makes when you Add Library and point it
    at a plain folder -- it creates 'Resolve Project Library', then
    'Resolve Project Library 2', '3', etc. if the name is already taken)."""
    root = root.resolve()
    if not root.exists():
        return
    for dirpath, dirnames, _filenames in os.walk(root):
        for d in dirnames:
            if d.lower().startswith(WRAPPER_NAME_PREFIX):
                yield Path(dirpath) / d


def count_projects_anywhere_under(folder: Path) -> int:
    count = 0
    for _dirpath, _dirnames, filenames in os.walk(folder):
        for fname in filenames:
            if fname.lower() == PROJECT_DB_FILENAME:
                count += 1
    return count


HOWTO_TEXT = """\
=== HOW TO ADD ONE OF THESE AS A LIBRARY IN RESOLVE ===
1. Project Manager -> Project Libraries panel -> "+" -> Add Library.
2. Browse to and select the plain workspace folder itself
   (e.g. D:\\dw_workspace\\davinci_workspace) -- NOT a "Resolve Projects" or
   "Resolve Project Library*" folder.
3. Resolve will create its OWN wrapper subfolder inside it, named
   "Resolve Project Library" (or "Resolve Project Library 2", "3", etc. if
   that name is already taken by a stale leftover -- see below).
4. If you're restoring a backup: copy your real "Resolve Projects" folder
   INSIDE that newly created wrapper folder, so the path becomes:
       <picked folder>\\Resolve Project Library <N>\\Resolve Projects\\...
   Resolve should then recognize all the projects inside it.
5. Verify all expected projects show up before deleting anything.

Stale "Resolve Project Library*" wrapper folders (from earlier failed
attempts) keep incrementing the number each time you Add Library again.
Clean those up first (see STALE WRAPPER FOLDERS section below, and/or
cleanup_empty_davinci_libraries.py) so you don't end up chasing a growing
number forever.
"""


def main():
    parser = argparse.ArgumentParser(description="Find DaVinci Resolve disk-database libraries.")
    parser.add_argument("--roots", nargs="+", default=DEFAULT_ROOTS,
                         help="Root folders to scan (default: the two dw_workspace paths).")
    parser.add_argument("--out", default=None,
                         help="Report output file. Default: <script_dir>/report/davinci_libraries_report.txt")
    args = parser.parse_args()

    if args.out is None:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        out_path = REPORT_DIR / "davinci_libraries_report.txt"
    else:
        # If the user passes --out explicitly, respect it as given (relative
        # to CWD, or absolute) rather than forcing it under REPORT_DIR.
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)

    report_lines = [HOWTO_TEXT]
    all_lib_roots = []

    for root_str in args.roots:
        root = Path(root_str)
        print(f"Scanning: {root}")
        report_lines.append(f"=== SCANNED ROOT: {root} ===\n")

        found_any = False
        for lib_root, resolve_projects_dir in find_libraries(root):
            found_any = True
            all_lib_roots.append(lib_root)
            projects = list_projects_under(resolve_projects_dir)

            report_lines.append(f"LIBRARY ROOT (this is what you browse to in Resolve):")
            report_lines.append(f"    {lib_root}")
            report_lines.append(f"  Projects found ({len(projects)}):")
            for name, dbpath in sorted(projects):
                report_lines.append(f"    - {name}   ({dbpath})")
            report_lines.append("")

        if not found_any:
            report_lines.append("  (no 'Resolve Projects' folder found under this root)\n")

    # Second pass: any Project.db not accounted for above (different / older structure)
    orphans = []
    for root_str in args.roots:
        orphans.extend(find_orphan_project_dbs(Path(root_str), all_lib_roots))

    if orphans:
        report_lines.append("=== Project.db files found OUTSIDE any 'Resolve Projects' folder ===")
        report_lines.append("(older/custom structure -- the library root here is likely just the")
        report_lines.append(" project's parent folder; inspect manually)\n")
        for p in orphans:
            report_lines.append(f"  - {p}")
        report_lines.append("")

    # Wrapper folders (Resolve's own "Resolve Project Library*" dirs) that
    # contain zero projects anywhere inside them -- stale leftovers from
    # earlier failed Add Library attempts.
    stale_wrappers = []
    live_wrappers = []
    for root_str in args.roots:
        for wrapper in find_wrapper_folders(Path(root_str)):
            n = count_projects_anywhere_under(wrapper)
            if n == 0:
                stale_wrappers.append(wrapper)
            else:
                live_wrappers.append((wrapper, n))

    report_lines.append("=== 'Resolve Project Library*' WRAPPER FOLDERS ===")
    if live_wrappers:
        report_lines.append("In use (contains projects -- keep):")
        for wrapper, n in sorted(live_wrappers, key=lambda x: str(x[0])):
            report_lines.append(f"  - {wrapper}   ({n} project{'s' if n != 1 else ''})")
    if stale_wrappers:
        report_lines.append("Stale / empty (safe candidates to delete):")
        for wrapper in sorted(stale_wrappers, key=str):
            report_lines.append(f"  - {wrapper}")
    if not live_wrappers and not stale_wrappers:
        report_lines.append("  (none found)")
    report_lines.append("")

    report_text = "\n".join(report_lines)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report_text)

    print("\n" + report_text)
    print(f"\nReport written to: {out_path}")
    if not all_lib_roots and not orphans:
        print("\nNo Project.db or 'Resolve Projects' folder found at all under the given roots.")
        print("Either the projects use PostgreSQL (not disk database), or the folder names")
        print("differ from what's expected -- tell me what's actually inside one of those")
        print("D:\\dw_workspace\\... folders and I'll adjust the detection.")


if __name__ == "__main__":
    main()