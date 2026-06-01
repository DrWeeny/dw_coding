# Slimfast — Developer & Contributor Guide

Slimfast is a modular weight painting and weight management UI. By default, it supports standard Maya deformers, nCloth/nRigid nodes, and Vertex Color Alphas out of the box. 

However, **Slimfast is designed to be fully extensible**. If your studio uses custom solvers (like Ziva, custom skinning solutions, or proprietary wrap deformers), you can easily inject custom UI panels into Slimfast without modifying the core codebase.

The back-end API for reading/writing weights is detailed in `../dw_paint/CONTRIBUTING.md`. This document explains how to integrate your custom back-end into the **Slimfast Front-End UI**.

---

## 🏗 Understanding the UI Architecture

Slimfast's UI is split into two parts:
1. **Core UI (`main_ui.py`)**: Handles the mesh picker, source dropdown, copy/paste, flood weights, clamp, smooth, and selection utilities. You don't need to rewrite this!
2. **Sub-Panels (`wgt_deformer_panel.py`)**: A dynamic section injected right below the source dropdown. It changes dynamically depending on the selected deformer type.

To add a new tool, you just need to write a compact **Sub-Panel** class and map it to your node type via the **Registry**.

---

## 🛠 Step-by-Step Guide: Adding a Custom Panel

Let's imagine you have a custom deformer called `myMuscleNode` and you want to add a UI to select bones or specific targets when repainting it.

### 1. Create a `DeformerPanelBase` subclass

Create a new python file, e.g., `custom_muscle_panel.py`.

```python
from PySide6 import QtWidgets
from dw_maya.Slimfast import wgt_deformer_panel

class MusclePanel(wgt_deformer_panel.DeformerPanelBase):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Build your custom UI widgets here
        self.label = QtWidgets.QLabel("Select Muscle Target:")
        self.combo = QtWidgets.QComboBox()
        self.combo.currentIndexChanged.connect(self._on_target_picked)
        
        layout.addWidget(self.label)
        layout.addWidget(self.combo)

    def _on_target_picked(self, index: int):
        target_name = self.combo.currentText()
        if target_name:
            # Tell Slimfast internal controller to switch the active map!
            self.map_selected.emit(target_name)

    # --- Lifecycle Hooks ---

    def on_combo_changed(self, node_type: str, maps: list[str]) -> None:
        """Called automatically when the user picks a 'myMuscleNode' in the main Slimfast dropdown."""
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItems(maps)   # Fill dropdown with available maps
        self.combo.blockSignals(False)

    def on_source_changed(self, source, active_map: str, ctrl) -> None:
        """Called when the active map/source is officially switched."""
        self.combo.setCurrentText(active_map)

    # --- UI Feature Flags ---

    def has_envelope(self) -> bool:
        """Does your node use an 'envelope' attribute? (Default: True)"""
        return True

    def has_paint(self) -> bool:
        """Does your node support the Maya Artisan Paint brush? (Default: True)"""
        return True
```

### 2. Register Your Panel

At the bottom of your file, register your class. This creates a radio button in Slimfast's mode selector and tells it to load your UI whenever a `myMuscleNode` is found.

```python
wgt_deformer_panel.register_deformer_panel(
    mode_key='muscle',              # Unique ID for the tool
    label='Muscle',                 # The text shown on the radio button
    panel_class=MusclePanel,        # Your custom UI class
    ctrl_mode='all',                # Mode passed to resolve_weight_sources
    node_types=['myMuscleNode'],    # Maya node types that trigger this UI
    order=50,                       # Order placement for the radio button
)
```

### 3. Load it into Slimfast!

To make sure your tool is available, Python simply needs to read your file **before or during** Slimfast startup.

**If you are adding a tool inside `dw_open_tools`:**
Simply import your new file inside `dw_maya/Slimfast/__init__.py`.

```python
# dw_maya/Slimfast/__init__.py
import dw_maya.Slimfast.main_ui
import dw_maya.Slimfast.wgt_deformer_panel

# Add your panel here:
from . import custom_muscle_panel
```

**If you are at a different studio using `dw_open_tools` as a library:**
You don't need to modify this repo! You can put your custom script in your own pipeline package. When you build your shelf button to launch Slimfast, just import your script first:

```python
# Studio Shelf Button snippet
import my_studio.pipeline.custom_muscle_panel  # Runs the registration

from dw_maya.Slimfast.main_ui import SlimfastWidget
SlimfastWidget.show_window()
```

---

## 📌 Quick Summary of Panel Methods

| Method | Purpose |
| ------ | ------- |
| `__init__(self, parent)` | Build your PySide6 layout. You must define this. |
| `on_combo_changed(node_type, maps)` | Hook: Triggered before switching to a new node, good for pre-filling lists with the `maps` arguments. |
| `on_source_changed(source, active_map, ctrl)` | Hook: Triggered when the backend officially updates the active node. Use it to refresh bone lists, UI badges, or tracking. |
| `self.map_selected.emit(map_name)` | Signal: Call this to tell the Slimfast Controller that the user picked a different channel (e.g., clicked a bone). |
| `has_envelope()` | Flag: Return False if you want Slimfast to hide the `envelope` slider. |
| `has_paint()` | Flag: Return False if you want Slimfast to hide/disable the `Paint` button. |

