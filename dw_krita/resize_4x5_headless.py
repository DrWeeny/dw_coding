import os
import shutil
import subprocess
import sys
from pathlib import Path

KRITARUNNER_CANDIDATES = [
    "kritarunner",
    r"C:\Program Files\Krita (x64)\bin\kritarunner.exe",
    r"C:\Program Files\Krita\bin\kritarunner.exe",
]

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".kra"}


def find_kritarunner_executable():
    env_override = os.environ.get("KRITARUNNER_EXE")
    if env_override:
        return env_override

    for candidate in KRITARUNNER_CANDIDATES:
        resolved = shutil.which(candidate) if not os.path.isabs(candidate) else candidate
        if resolved and Path(resolved).is_file():
            return resolved

    raise FileNotFoundError(
        "Could not find kritarunner. Set the KRITARUNNER_EXE environment "
        "variable to its full path and run this script again."
    )


def relaunch_in_krita():
    script_path = Path(__file__).resolve()
    kritarunner_exe = find_kritarunner_executable()
    print(f"Relaunching under kritarunner: {kritarunner_exe}")
    # kritarunner wants the script name without the .py extension,
    # and resolves it relative to the working directory.
    result = subprocess.run(
        [kritarunner_exe, "--script", script_path.stem],
        cwd=script_path.parent,
    )
    sys.exit(result.returncode)


def process_images():
    from krita import Krita

    folder_to_process = Path(__file__).resolve().parent
    folder_to_export = folder_to_process / "out"
    folder_to_export.mkdir(exist_ok=True)

    _instance = Krita.instance()

    for file in sorted(os.listdir(folder_to_process)):
        file_path = folder_to_process / file

        if not file_path.is_file() or file_path.suffix.lower() not in IMAGE_EXTS:
            continue

        doc = _instance.openDocument(str(file_path))
        if doc is None:
            print(f"Skipped (failed to open): {file}")
            continue

        height = doc.height()
        width = doc.width()

        if width >= height:
            # landscape: skip entirely for now
            print(f"Skipped (landscape): {file}")
            doc.close()
            continue

        # need to change it to 4x5
        target_w = int(height * 4 / 5.95)

        if width < target_w:
            doc.resizeImage(
                (width - target_w) // 2,
                0,
                target_w,
                height
            )
            print(f"Resized {file}: {width}x{height} -> {target_w}x{height}")

        doc.setBatchmode(True)
        doc.saveAs(str(folder_to_export / file))
        doc.close()

    print("Done.")


try:
    import krita  # noqa: F401
except ImportError:
    relaunch_in_krita()
else:
    process_images()
