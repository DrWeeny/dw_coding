from krita import Krita
from pathlib import Path
import os
folder_to_export = r""
folder_to_process = os.path.join(folder_to_export, "src")
list_files = os.listdir(folder_to_process)

_instance = Krita.instance()
for file in list_files:
    # open image
    doc = _instance.openDocument(os.path.join(folder_to_process, file))
    Krita.instance().activeWindow().addView(doc)
    height = doc.height()
    width = doc.width()
    if width < height:
        # need to change it to 4x5
        target_w = int(height * 4 / 5.95)

        if width < target_w:
            extra = target_w - width

            # Center the existing image
            left = extra // 2

            doc.resizeImage(
                (width-target_w)//2,
                0,
                target_w,
                height
            )

            print(target_w, height)
            doc.setBatchmode(True)
            doc.saveAs(os.path.join(folder_to_export, file))
