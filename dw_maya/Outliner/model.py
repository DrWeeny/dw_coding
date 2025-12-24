from Qt import QtCore, QtGui
import maya.cmds as cmds
import maya.api.OpenMaya as om
from collections import defaultdict
from dw_maya.dw_decorators import timeIt
from .cmds import get_exportable_type_list, get_exportable_transforms, count_types

class SceneTreeNode:
    """
    Represents a node in the scene hierarchy tree.

    Attributes:
        name: Short node name (without namespace prefix)
        full_path: Complete DAG path
        parent: Parent SceneTreeNode
        children: List of child SceneTreeNode objects
    """
    def __init__(self, name="", full_path="", node_type="transform"):
        self.name = name
        self.full_path = full_path
        self.parent = None
        self.children = []
        self.node_type = node_type
        self.shape_count = 0
        self.shape_type = None  # Primary shape type (mesh, nurbsCurve, etc.)
        self.in_cache = False
        self.namespace = ""

    def add_child(self, child):
        """Add a child node."""
        child.parent = self
        self.children.append(child)

    def row(self):
        """Get row index in parent's children list."""
        if self.parent:
            return self.parent.children.index(self)
        return 0

    def child_count(self):
        """Get number of children."""
        return len(self.children)

    def get_badge_text(self):
        """Get badge text showing content count."""
        if self.shape_count > 0 and self.shape_type:
            type_name = {
                "mesh": "meshes",
                "nurbsCurve": "curves",
                "pgYetiMaya": "yeti",
                "AlembicNode": "alembic"
            }.get(self.shape_type, "shapes")
            return f"[{self.shape_count} {type_name}]"
        return ""


class SceneTreeModel(QtCore.QAbstractItemModel):
    """
    Qt model for scene hierarchy tree view.

    Provides color-coded display with cache status indicators.
    Supports minimal (cache-only) and full hierarchy modes.

    Attributes:
        root_node: Root SceneTreeNode
        minimal_mode: Whether to show only cache-related nodes
        asset_namespaces: List of asset namespaces to filter
        node_to_ops_map: Dict mapping node paths to cache Ops
    """

    # Color scheme
    COLORS = {
        "root":"#FFD700",
        "in_cache": "#FFFFFF",  # Bold white
        "not_in_cache": "#A0A0A0",  # Light gray
        "unsupported": "#707070",  # Darker gray
        "mesh": "#FF6B6B",  # Light red for mesh children
        "nurbsCurve": "#9B59B6",  # Purple for curves
        "pgYetiMaya": "#E67E22",  # Orange for Yeti
        "AlembicNode": "#16A085",  # Teal for Alembic
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.root_node = SceneTreeNode(name="Root")
        self.minimal_mode = False
        self.asset_namespaces = []
        self.node_to_ops_map = {}  # {full_path: [Op, ...]}
        self._path_to_node_cache = {}  # Cache for full tree restoration
        self._full_tree_children_cache = {}  # {full_path: [child_paths]} for restoration

    def set_shot_context(self, asset_namespaces=None):
        """
        Set shot context for namespace filtering.

        Args:
            asset_namespaces: List of asset namespaces (e.g., ["sofiaSTD_01"])
        """
        self.asset_namespaces = asset_namespaces or []

    def set_minimal_mode(self, minimal_mode):
        """Toggle minimal mode by filtering existing tree (no rebuild)."""
        if self.minimal_mode == minimal_mode:
            return

        self.minimal_mode = minimal_mode
        self.beginResetModel()

        if minimal_mode:
            # Cache full tree structure before filtering
            self._cache_full_tree_structure()
            self._filter_to_cache_only()
        else:
            # Restore full tree from cache (faster than rebuilding)
            self._restore_full_tree()

        self.endResetModel()

    def _cache_full_tree_structure(self):
        """Cache the full tree children relationships before filtering."""
        self._full_tree_children_cache = {}
        self._cache_node_children(self.root_node)

    def _cache_node_children(self, node):
        """Recursively cache children for a node."""
        # Store list of child nodes (not just paths) for this node
        self._full_tree_children_cache[node.full_path if node.full_path else "ROOT"] = list(node.children)
        for child in node.children:
            self._cache_node_children(child)

    def _restore_full_tree(self):
        """Restore the full tree from cache."""
        if not self._full_tree_children_cache:
            # No cache, need to rebuild
            self._build_hierarchy()
            return
        self._restore_node_children(self.root_node)

    def _restore_node_children(self, node):
        """Recursively restore children for a node from cache."""
        cache_key = node.full_path if node.full_path else "ROOT"
        if cache_key in self._full_tree_children_cache:
            node.children = self._full_tree_children_cache[cache_key]
            for child in node.children:
                self._restore_node_children(child)

    def _filter_to_cache_only(self):
        """Filter existing tree to show only cache-related nodes."""
        # Build set of paths to keep
        paths_to_keep = set(self.node_to_ops_map.keys())

        # Add all ancestors of cache nodes
        for path in list(paths_to_keep):
            parts = path.split("|")
            for i in range(1, len(parts)):
                paths_to_keep.add("|".join(parts[:i + 1]))

        # Recursively filter children
        self._filter_node_children(self.root_node, paths_to_keep)

    def _filter_node_children(self, node, paths_to_keep):
        """Recursively filter node's children."""
        node.children = [
            child for child in node.children
            if child.full_path in paths_to_keep
        ]
        for child in node.children:
            self._filter_node_children(child, paths_to_keep)

    def rebuild(self, minimal_mode=False, do_count:bool=True):
        """
        Rebuild the tree model from current Maya scene.

        Args:
            minimal_mode: If True, show only cache-related nodes
        """
        self.beginResetModel()
        self.minimal_mode = False

        # Clear existing tree and cache
        self.root_node = SceneTreeNode(name="Root")
        self._full_tree_children_cache = {}

        # Build cache mapping first
        self._build_cache_map(do_count=do_count)

        # Build hierarchy
        self._build_hierarchy()

        self.endResetModel()

    @timeIt(normal_print=True)
    def _build_cache_map(self, to_export:list=None, do_count=True):
        """Used to tag export list with type and count shapes"""
        self.node_to_ops_map = defaultdict(list)
        self.__cache_direct = []

        if not to_export:
            return

        if do_count:
            self.__cache_counter = defaultdict(lambda: defaultdict(int))

        op_list = []
        if self.asset_namespaces:
            for a in self.asset_namespaces:
                op_list.extend([c for c in to_export if f"{a}:" in c])
        else:
            op_list = to_export

        # Pre-create selection list for batch processing
        sel_list = om.MSelectionList()

        # Collect all leaf paths first
        leaf_paths_to_process = []

        # Batch convert short names to long paths using OpenMaya
        path_mapping = {}  # short_name -> long_path
        for leaf_str in op_list:
            if leaf_str not in path_mapping:
                try:
                    sel_list.clear()
                    sel_list.add(leaf_str)
                    dag_path = sel_list.getDagPath(0)
                    path_mapping[leaf_str] = dag_path.fullPathName()
                except:
                    path_mapping[leaf_str] = None

        # Process each leaf
        for leaf_str, op in leaf_paths_to_process:
            long_path = path_mapping.get(leaf_str)
            if not long_path:
                continue

            leaf_children = get_exportable_transforms(long_path, intermediate_transforms=True)

            if do_count:
                short_name = long_path.split("|")[-1]
                namespace = short_name.split(":")[0] if ":" in short_name else ""

            if op not in self.node_to_ops_map[long_path]:
                self.node_to_ops_map[long_path].append(op)
                self.__cache_direct.append(long_path)
                if not leaf_children and do_count:
                    self._count_shapes_api(long_path, namespace)

            for lc in leaf_children:
                if op not in self.node_to_ops_map[lc]:
                    self.node_to_ops_map[lc].append(op)

            if leaf_children and do_count:
                # Batch count for all children
                shapes = cmds.listRelatives(leaf_children, shapes=True, noIntermediate=True) or []
                if shapes:
                    shape_type_list = [cmds.nodeType(s) for s in shapes]
                    self.__cache_counter = count_types(namespace, self.__cache_counter, shape_type_list)

    def _count_shapes_api(self, long_path, namespace):
        """Count shapes using OpenMaya API."""
        try:
            sel_list = om.MSelectionList()
            sel_list.add(long_path)
            dag_path = sel_list.getDagPath(0)
            shape_count = dag_path.numberOfShapesDirectlyBelow()
            if shape_count > 0:
                dag_path.extendToShape(0)
                api_type = dag_path.node().apiTypeStr
                shape_type = {"kMesh": "mesh", "kNurbsCurve": "nurbsCurve"}.get(api_type)
                if shape_type is None:
                    shapes = cmds.listRelatives(long_path, shapes=True, noIntermediate=True) or []
                    if shapes:
                        shape_type = cmds.nodeType(shapes[0])
                if shape_type:
                    self.__cache_counter[namespace][shape_type] += 1
        except:
            pass

    @timeIt(normal_print=True)
    def _build_hierarchy(self):
        """Build scene hierarchy using OpenMaya API."""
        dag_iter = om.MItDag(om.MItDag.kDepthFirst, om.MFn.kTransform)

        path_to_node = {}  # {full_path: SceneTreeNode}

        # Pre-build ancestor paths set for minimal mode (O(n) instead of O(n²))
        cache_ancestors = set()
        if self.minimal_mode:
            for path in self.node_to_ops_map.keys():
                # Add all ancestor paths
                parts = path.split("|")
                for i in range(1, len(parts)):
                    ancestor = "|".join(parts[:i+1])
                    cache_ancestors.add(ancestor)

        # Convert asset_namespaces to set for faster lookup
        asset_ns_set = set(self.asset_namespaces) if self.asset_namespaces else None

        while not dag_iter.isDone():
            dag_path = dag_iter.getPath()
            full_path = dag_path.fullPathName()

            # Get node info - extract short_name and namespace once
            short_name = dag_path.partialPathName()
            namespace = short_name.split(":")[0] if ":" in short_name else ""

            # Skip if namespace filtering enabled and doesn't match
            if asset_ns_set and namespace not in asset_ns_set:
                dag_iter.next()
                continue

            is_root = full_path.count("|") == 1

            # Check cache status
            in_cache = full_path in self.node_to_ops_map
            cache_ops = self.node_to_ops_map.get(full_path, [])

            # In minimal mode, skip nodes not in cache and not ancestors of cache nodes
            if self.minimal_mode and not in_cache:
                if full_path not in cache_ancestors:
                    dag_iter.next()
                    continue

            # Get shape info using OpenMaya API (faster than cmds.listRelatives)
            shape_count = dag_path.numberOfShapesDirectlyBelow()
            shape_type = None
            if shape_count > 0:
                # Get first shape type using OpenMaya
                try:
                    dag_path_shape = om.MDagPath(dag_path)
                    dag_path_shape.extendToShape(0)
                    shape_type = dag_path_shape.node().apiTypeStr
                    # Map API type to Maya node type
                    shape_type = {
                        "kMesh": "mesh",
                        "kNurbsCurve": "nurbsCurve",
                        "kNurbsSurface": "nurbsSurface",
                        "kPluginShape": None,  # Need cmds for plugin types
                    }.get(shape_type, None)
                    # Fallback to cmds for plugin shapes (Yeti, Alembic)
                    if shape_type is None:
                        shapes = cmds.listRelatives(full_path, shapes=True, noIntermediate=True) or []
                        if shapes:
                            shape_type = cmds.nodeType(shapes[0])
                except:
                    pass

            # Create node
            node = SceneTreeNode(
                name=short_name,
                full_path=full_path,
                node_type="transform"
            )
            node.namespace = namespace
            node.shape_count = shape_count
            node.shape_type = shape_type
            node.in_cache = in_cache
            node.cache_ops = cache_ops
            node.is_root = is_root

            path_to_node[full_path] = node

            # Build parent-child relationship
            parent_path = full_path.rsplit("|", 1)[0] if "|" in full_path else ""
            if parent_path and parent_path in path_to_node:
                parent_node = path_to_node[parent_path]
                parent_node.add_child(node)
            else:
                # Top-level node
                self.root_node.add_child(node)

            dag_iter.next()

    # ========================================================================
    # Qt Model Interface
    # ========================================================================

    def index(self, row, column, parent=QtCore.QModelIndex()):
        """Create model index for given row/column/parent."""
        if not self.hasIndex(row, column, parent):
            return QtCore.QModelIndex()

        parent_node = self._get_node(parent)
        if row < len(parent_node.children):
            child_node = parent_node.children[row]
            return self.createIndex(row, column, child_node)

        return QtCore.QModelIndex()

    def parent(self, index):
        """Get parent index for given index."""
        if not index.isValid():
            return QtCore.QModelIndex()

        node = self._get_node(index)
        parent_node = node.parent

        if parent_node == self.root_node or parent_node is None:
            return QtCore.QModelIndex()

        return self.createIndex(parent_node.row(), 0, parent_node)

    def rowCount(self, parent=QtCore.QModelIndex()):
        """Get number of rows under parent."""
        parent_node = self._get_node(parent)
        return parent_node.child_count()

    def columnCount(self, parent=QtCore.QModelIndex()):
        """Get number of columns."""
        return 1  # Single column tree

    def data(self, index, role=QtCore.Qt.DisplayRole):
        """Provide data for display roles."""
        if not index.isValid():
            return None

        node = self._get_node(index)

        if role == QtCore.Qt.DisplayRole:
            # Build display text with badge
            display_text = node.name
            badge = "●" if node.in_cache else ""
            if badge:
                display_text += f" {badge}"
            if node.is_root and node.namespace in self.__cache_counter:
                counts = self.__cache_counter[node.namespace]
                if counts:
                    parts = []
                    for type_name in self.__cache_counter[node.namespace]:
                        c  = self.__cache_counter[node.namespace].get(type_name, 0)
                        if c > 0:
                            parts.append(f"{c} {type_name}")
                    if parts:
                        display_text += f" [{', '.join(parts)}]"

            return display_text

        elif role == QtCore.Qt.ForegroundRole:
            # Color based on cache status and node type
            if node.is_root:
                return QtGui.QColor(self.COLORS["root"])
            elif node.in_cache:
                return QtGui.QColor(self.COLORS.get(node.shape_type, "#FFFFFF"))
            else:
                # Check if it's a shape-holding transform
                if node.shape_type in self.COLORS:
                    return QtGui.QColor(self.COLORS[node.shape_type])
                return QtGui.QColor(self.COLORS["not_in_cache"])

        elif role == QtCore.Qt.FontRole:
            font = QtGui.QFont()
            if not node.in_cache:
                font.setItalic(True)

            if node.is_root or node.full_path in self.__cache_direct:
                font.setBold(True)

            return font

        elif role == QtCore.Qt.DecorationRole:
            # Status indicator: ● or ○
            if node.in_cache:
                return "●"
            else:
                return "○"

        elif role == QtCore.Qt.ToolTipRole:
            return self._build_tooltip(node)

        elif role == QtCore.Qt.UserRole:
            # Store node data for access
            return {
                "node": node,
                "full_path": node.full_path,
                "node_type": node.node_type,
                "shape_type": node.shape_type,
                "in_cache": node.in_cache,
                "cache_ops": node.cache_ops,
                "namespace": node.namespace
            }

        return None

    def flags(self, index):
        """Set item flags."""
        if not index.isValid():
            return QtCore.Qt.NoItemFlags

        node = self._get_node(index)

        # Make selectable only if it's a supported type
        if node.shape_type in get_exportable_type_list():
            return QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable
        else:
            # Non-shape transforms are enabled but not selectable
            return QtCore.Qt.ItemIsEnabled

    def _get_node(self, index):
        """Get SceneTreeNode from QModelIndex."""
        if index.isValid():
            return index.internalPointer()
        return self.root_node

    def _build_tooltip(self, node):
        """Build tooltip for node."""
        lines = [
            f"<b>{node.name}</b>",
            "<hr>",
            f"<b>Type:</b> {node.node_type}",
        ]

        if node.shape_type:
            lines.append(f"<b>Shape Type:</b> {node.shape_type}")

        if node.shape_count > 0:
            lines.append(f"<b>Shape Count:</b> {node.shape_count}")

        lines.append("<hr>")

        if node.in_cache:
            lines.append("<b>Status:</b> <span style='color: #27AE60;'>✓ In Bakeops</span>")
            if node.cache_ops:
                op_names = [op.name for op in node.cache_ops]
                lines.append(f"<b>Operators:</b> {', '.join(op_names)}")
        else:
            lines.append("<b>Status:</b> <span style='color: #E74C3C;'>✗ Not in Bakeops</span>")

        lines.append("<hr>")
        lines.append(f"<span style='color: #888; font-size: 9pt;'>{node.full_path}</span>")

        return "<div style='font-family: monospace;'>" + "<br>".join(lines) + "</div>"