import maya.cmds as cmds
import maya.api.OpenMaya as om
from PySide6 import QtWidgets, QtCore, QtGui
import maya.OpenMayaUI as omui
from shiboken6 import wrapInstance


class QRangeSlider(QtWidgets.QWidget):
    """Custom range slider with two handles"""

    valueChanged = QtCore.Signal(float, float)
    sliderReleased = QtCore.Signal()

    def __init__(self, parent=None):
        super(QRangeSlider, self).__init__(parent)
        self.min_value = 0
        self.max_value = 100
        self.min_pos = 0
        self.max_pos = 100
        self.margin = 10
        self.pressed_control = None
        self.hover_control = None
        self.minimum_position = 0
        self.maximum_position = 0
        self.setFixedHeight(30)

    def setRange(self, minimum, maximum):
        self.min_value = minimum
        self.max_value = maximum
        self.min_pos = minimum
        self.max_pos = maximum
        self.update()

    def getRange(self):
        return self.min_pos, self.max_pos

    def setMinimum(self, value):
        self.min_pos = max(self.min_value, min(self.max_pos, value))
        self.update()

    def setMaximum(self, value):
        self.max_pos = min(self.max_value, max(self.min_pos, value))
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)

        # Draw background
        bg_rect = QtCore.QRectF(self.margin, self.height() / 3,
                                self.width() - 2 * self.margin, self.height() / 3)
        painter.setBrush(QtGui.QBrush(QtGui.QColor(200, 200, 200)))
        painter.setPen(QtCore.Qt.NoPen)
        painter.drawRoundedRect(bg_rect, 2, 2)

        # Draw selected range
        if self.max_value > self.min_value:
            interval = self.width() - 2 * self.margin
            range_rect = QtCore.QRectF(
                self.margin + (self.min_pos - self.min_value) * interval / (self.max_value - self.min_value),
                self.height() / 3,
                (self.max_pos - self.min_pos) * interval / (self.max_value - self.min_value),
                self.height() / 3
            )
            painter.setBrush(QtGui.QBrush(QtGui.QColor(100, 150, 255)))
            painter.drawRoundedRect(range_rect, 2, 2)

        # Draw handles
        painter.setBrush(QtGui.QBrush(QtGui.QColor(255, 255, 255)))
        painter.setPen(QtGui.QPen(QtGui.QColor(150, 150, 150)))

        handle_width = 10
        handle_height = 20

        for value, hover in [(self.min_pos, self.hover_control == "min"),
                             (self.max_pos, self.hover_control == "max")]:
            if self.max_value > self.min_value:
                handle_x = (self.margin +
                            (value - self.min_value) *
                            (self.width() - 2 * self.margin) /
                            (self.max_value - self.min_value))
                handle_rect = QtCore.QRectF(
                    handle_x - handle_width / 2,
                    self.height() / 2 - handle_height / 2,
                    handle_width,
                    handle_height
                )
                if hover:
                    painter.setBrush(QtGui.QBrush(QtGui.QColor(220, 220, 220)))
                painter.drawRoundedRect(handle_rect, 2, 2)
                painter.setBrush(QtGui.QBrush(QtGui.QColor(255, 255, 255)))

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            handle_width = 10
            pos = self._value_from_pos(event.pos().x())
            min_handle_pos = self._pos_from_value(self.min_pos)
            max_handle_pos = self._pos_from_value(self.max_pos)

            if abs(pos - self.min_pos) < abs(pos - self.max_pos):
                if abs(event.pos().x() - min_handle_pos) < handle_width:
                    self.pressed_control = "min"
            else:
                if abs(event.pos().x() - max_handle_pos) < handle_width:
                    self.pressed_control = "max"

    def mouseMoveEvent(self, event):
        if self.pressed_control:
            pos = self._value_from_pos(event.pos().x())
            if self.pressed_control == "min":
                self.setMinimum(pos)
            else:
                self.setMaximum(pos)
            self.valueChanged.emit(self.min_pos, self.max_pos)

    def mouseReleaseEvent(self, event):
        if self.pressed_control:
            self.sliderReleased.emit()
        self.pressed_control = None

    def enterEvent(self, event):
        self.hover_control = None
        self.update()

    def leaveEvent(self, event):
        self.hover_control = None
        self.update()

    def _value_from_pos(self, x):
        return ((x - self.margin) * (self.max_value - self.min_value) /
                (self.width() - 2 * self.margin) + self.min_value)

    def _pos_from_value(self, value):
        return (self.margin + (value - self.min_value) *
                (self.width() - 2 * self.margin) / (self.max_value - self.min_value))


class EdgeLengthTool(QtWidgets.QDialog):
    def __init__(self, parent=maya_main_window()):
        super(EdgeLengthTool, self).__init__(parent)

        self.setWindowTitle("Edge Length Visualization Tool")
        self.setMinimumWidth(300)
        self.setWindowFlags(self.windowFlags() ^ QtCore.Qt.WindowContextHelpButtonHint)
        # Add dictionary to store edge lengths
        self.edge_lengths = {}

        # Store mesh data
        self.vertex_max_lengths = {}
        self.min_length = 0
        self.max_length = 0

        self.create_widgets()
        self.create_layouts()
        self.create_connections()

    def create_widgets(self):
        # Power value spinbox
        self.power_label = QtWidgets.QLabel("Power Value:")
        self.power_spinbox = QtWidgets.QDoubleSpinBox()
        self.power_spinbox.setRange(0, 10.0)
        self.power_spinbox.setValue(.4)
        self.power_spinbox.setSingleStep(0.1)

        # Create ramp button
        self.create_ramp_btn = QtWidgets.QPushButton("Create Color Ramp")

        # Length range slider
        self.length_label = QtWidgets.QLabel("Edge Length Range:")
        self.length_slider = QRangeSlider()

        # Min/Max labels
        self.min_length_label = QtWidgets.QLabel("Min: 0.0")
        self.max_length_label = QtWidgets.QLabel("Max: 0.0")

        self.select_edges_btn = QtWidgets.QPushButton("Select Red Edges")

    def create_layouts(self):
        main_layout = QtWidgets.QVBoxLayout(self)

        # Power layout
        power_layout = QtWidgets.QHBoxLayout()
        power_layout.addWidget(self.power_label)
        power_layout.addWidget(self.power_spinbox)

        # Slider layout
        slider_layout = QtWidgets.QVBoxLayout()
        slider_layout.addWidget(self.length_label)

        range_layout = QtWidgets.QHBoxLayout()
        range_layout.addWidget(self.min_length_label)
        range_layout.addWidget(self.max_length_label)
        slider_layout.addLayout(range_layout)
        slider_layout.addWidget(self.length_slider)

        # Add all to main layout
        main_layout.addLayout(power_layout)
        main_layout.addWidget(self.create_ramp_btn)
        main_layout.addLayout(slider_layout)
        main_layout.addWidget(self.select_edges_btn)

    def create_connections(self):
        self.create_ramp_btn.clicked.connect(self.create_color_ramp)
        self.length_slider.sliderReleased.connect(self.update_colors_from_range)
        self.length_slider.valueChanged.connect(self.update_range_labels)
        self.select_edges_btn.clicked.connect(self.select_red_edges)  # Moved here

    def update_range_labels(self, min_val, max_val):
        self.min_length_label.setText(f"Min: {min_val:.3f}")
        self.max_length_label.setText(f"Max: {max_val:.3f}")

    def create_color_ramp(self):
        selection = cmds.ls(selection=True, o=True)
        if not selection:
            QtWidgets.QMessageBox.warning(self, "Warning", "Please select a mesh")
            return

        mesh_name = selection[0]

        # Get mesh data
        sel_list = om.MSelectionList()
        sel_list.add(mesh_name)
        dag_path = sel_list.getDagPath(0)
        mesh = om.MFnMesh(dag_path)

        # Calculate edge lengths
        self.vertex_max_lengths.clear()
        self.edge_lengths.clear()

        for i in range(mesh.numEdges):
            vtx1, vtx2 = mesh.getEdgeVertices(i)
            point1 = mesh.getPoint(vtx1)
            point2 = mesh.getPoint(vtx2)
            length = om.MVector(point2 - point1).length()

            # Store edge length
            self.edge_lengths[i] = length

            # Update vertex max lengths
            self.vertex_max_lengths[vtx1] = max(self.vertex_max_lengths.get(vtx1, 0), length)
            self.vertex_max_lengths[vtx2] = max(self.vertex_max_lengths.get(vtx2, 0), length)

        edge_min_max = [y for x, y in self.edge_lengths.items()]
        # Calculate overall min/max
        self.min_length = min(edge_min_max)
        self.max_length = max(edge_min_max)

        # Update UI with correct values
        self.min_length_label.setText(f"Min: {self.min_length:.3f}")
        self.max_length_label.setText(f"Max: {self.max_length:.3f}")
        self.length_slider.setRange(self.min_length, self.max_length)

        # Create color set
        color_set_name = "edgeLength"
        if not cmds.polyColorSet(mesh_name, q=True, allColorSets=True) or color_set_name not in cmds.polyColorSet(
                mesh_name, q=True, allColorSets=True):
            cmds.polyColorSet(mesh_name, create=True, colorSet=color_set_name, representation="RGB")

        cmds.polyColorSet(mesh_name, currentColorSet=True, colorSet=color_set_name)

        # Apply initial colors
        self.update_vertex_colors(mesh_name)

        # Enable display
        cmds.setAttr(f"{mesh_name}.displayColors", 1)

    def update_colors_from_range(self):
        selection = cmds.ls(selection=True, o=True)
        if not selection:
            return

        self.update_vertex_colors(selection[0])

    def select_red_edges(self):

        selection = cmds.ls(selection=True, o=True)
        if not selection or not self.edge_lengths:
            return

        mesh_name = selection[0]
        min_threshold, max_threshold = self.length_slider.getRange()

        # Create list of edge indices that fall within range
        edge_indices = [i for i, length in self.edge_lengths.items()
                        if min_threshold <= length <= max_threshold]
        print(self.edge_lengths.items())

        if edge_indices:
            # Clear current selection
            cmds.select(clear=True)

            # Select edges all at once using Maya's range syntax when possible
            try:
                # Try to create ranges of consecutive indices
                ranges = []
                current_range = [edge_indices[0]]

                for idx in edge_indices[1:]:
                    if idx == current_range[-1] + 1:
                        current_range.append(idx)
                    else:
                        if len(current_range) > 1:
                            ranges.append(f"{mesh_name}.e[{current_range[0]}:{current_range[-1]}]")
                        else:
                            ranges.append(f"{mesh_name}.e[{current_range[0]}]")
                        current_range = [idx]

                # Add the last range
                if len(current_range) > 1:
                    ranges.append(f"{mesh_name}.e[{current_range[0]}:{current_range[-1]}]")
                else:
                    ranges.append(f"{mesh_name}.e[{current_range[0]}]")

                cmds.select(ranges)

            except:
                # Fallback: select edges one by one
                for edge_id in edge_indices:
                    try:
                        cmds.select(f"{mesh_name}.e[{edge_id}]", add=True)
                    except:
                        continue

            print(
                f"Selected {len(edge_indices)} edges with lengths between {min_threshold:.3f} and {max_threshold:.3f}")
        else:
            cmds.select(clear=True)
            print("No edges found within the selected length range")

    def update_vertex_colors(self, mesh_name):
        min_threshold, max_threshold = self.length_slider.getRange()
        power = self.power_spinbox.value()

        # Process each vertex only once
        for vertex_id, max_length in self.vertex_max_lengths.items():
            # Calculate color
            if min_threshold <= max_length <= max_threshold:
                normalized_length = (max_length - min_threshold) / (max_threshold - min_threshold)
                normalized_length = pow(normalized_length, power)
                red = 1.0 - normalized_length
                color = [red, 0.0, 0.0]
            else:
                color = [0.0, 0.0, 0.0]  # Black for vertices outside range

            try:
                cmds.polyColorPerVertex(f"{mesh_name}.vtx[{vertex_id}]", rgb=color)
            except:
                # If single vertex fails, try updating all vertices at once
                all_vertices = [f"{mesh_name}.vtx[{i}]" for i in range(len(self.vertex_max_lengths))]
                cmds.polyColorPerVertex(all_vertices, rgb=color)
                break


def maya_main_window():
    """Return Maya's main window"""
    main_window = omui.MQtUtil.mainWindow()
    return wrapInstance(int(main_window), QtWidgets.QWidget)


def show():
    """Show the UI"""
    global edge_length_tool
    try:
        edge_length_tool.close()
        edge_length_tool.deleteLater()
    except:
        pass

    edge_length_tool = EdgeLengthTool()
    edge_length_tool.show()


show()