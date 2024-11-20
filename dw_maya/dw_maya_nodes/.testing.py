"""Unit tests for MayaNode class.

Tests various aspects of the MayaNode wrapper including:
- Node creation and access
- Attribute manipulation
- Transform/Shape handling
- Compound attributes
- Cluster weights
- Preset handling

Note:
    Requires Maya to be running in test mode.
    Tests create and clean up temporary Maya nodes.

Version: 1.0.0

Author:
    DrWeeny
"""

import unittest
from typing import List
import maya.cmds as cmds
import maya.mel as mel

from dw_maya.dw_maya_nodes import MayaNode


class TestMayaNode(unittest.TestCase):
    """Test cases for MayaNode class."""

    def setUp(self):
        """Create test nodes before each test."""
        # Create basic nodes
        self.cube = cmds.polyCube(name='testCube')[0]
        self.sphere = cmds.polySphere(name='testSphere')[0]

        # Create cluster for weight tests
        cmds.select(self.sphere + '.vtx[0:10]')
        self.cluster = cmds.cluster(name='testCluster')[1]

        # Store initial selection and clear it
        self.initial_selection = cmds.ls(selection=True)
        cmds.select(clear=True)

    def tearDown(self):
        """Clean up test nodes after each test."""
        # Delete test nodes
        for node in [self.cube, self.sphere, self.cluster]:
            if cmds.objExists(node):
                cmds.delete(node)

        # Restore initial selection
        if self.initial_selection:
            cmds.select(self.initial_selection)

    def test_basic_node_access(self):
        """Test basic node creation and access."""
        node = MayaNode(self.cube)

        # Test transform access
        self.assertEqual(node[0].node, self.cube)

        # Test shape access
        shape = cmds.listRelatives(self.cube, shapes=True)[0]
        self.assertEqual(node[1].node, shape)

        # Test node type
        self.assertEqual(node.nodeType, 'mesh')

    def test_attribute_access(self):
        """Test attribute getting and setting."""
        node = MayaNode(self.cube)

        # Test direct attribute setting
        node.translateX = 5.0
        self.assertEqual(cmds.getAttr(f"{self.cube}.translateX"), 5.0)

        # Test attribute object
        tx_attr = node.translateX
        self.assertIsInstance(tx_attr, MAttr)
        self.assertEqual(tx_attr.getAttr(), 5.0)

        # Test compound attribute
        node.translate = [1.0, 2.0, 3.0]
        self.assertEqual(cmds.getAttr(f"{self.cube}.translate")[0],
                         (1.0, 2.0, 3.0))

    def test_custom_attributes(self):
        """Test adding and accessing custom attributes."""
        node = MayaNode(self.cube)

        # Add custom attribute
        attr = node.addAttr("testAttr",
                            value=1.0,
                            attr_type='double',
                            keyable=True)

        # Test attribute creation
        self.assertTrue(cmds.objExists(f"{self.cube}.testAttr"))
        self.assertIsInstance(attr, MAttr)

        # Test value setting
        attr.setAttr(2.0)
        self.assertEqual(cmds.getAttr(f"{self.cube}.testAttr"), 2.0)

    def test_cluster_weights(self):
        """Test cluster weight attribute handling."""
        cluster = MayaNode(self.cluster)

        # Test weight list access
        weights = cluster.weightList[0].weights
        self.assertIsInstance(weights, MAttr)

        # Test getting weight values
        initial_weights = weights.getAttr()
        self.assertIsInstance(initial_weights, list)

        # Test setting specific weights
        weights[0].setAttr(0.5)
        self.assertEqual(
            cmds.getAttr(f"{self.cluster}.weightList[0].weights[0]"),
            0.5
        )

        # Test weight range setting
        weights[0:3].setAttr([0.1, 0.2, 0.3])
        for i, val in enumerate([0.1, 0.2, 0.3]):
            self.assertEqual(
                cmds.getAttr(f"{self.cluster}.weightList[0].weights[{i}]"),
                val
            )

    def test_node_rename(self):
        """Test node renaming functionality."""
        node = MayaNode(self.cube)

        # Test basic rename
        new_name = node.rename("newCube")
        self.assertEqual(new_name, "newCube")
        self.assertTrue(cmds.objExists("newCube"))
        self.assertTrue(cmds.objExists("newCubeShape"))

        # Test shape pattern rename
        shape_name = node.rename("customShape1")
        self.assertEqual(shape_name, "customShape1")

    def test_node_connections(self):
        """Test node connection handling."""
        source = MayaNode(self.cube)
        target = MayaNode(self.sphere)

        # Test operator connection
        source.translateX > target.translateX
        self.assertTrue(
            cmds.isConnected(f"{self.cube}.translateX",
                             f"{self.sphere}.translateX")
        )

        # Test connection method
        source.rotateX.connectAttr([f"{self.sphere}.rotateX"])
        self.assertTrue(
            cmds.isConnected(f"{self.cube}.rotateX",
                             f"{self.sphere}.rotateX")
        )

    def test_node_preset(self):
        """Test node preset creation and loading."""
        node = MayaNode(self.cube)

        # Modify some attributes
        node.translateX = 1.0
        node.translateY = 2.0
        node.rotateZ = 45.0

        # Create preset
        preset = node.attrPreset()

        # Create new node from preset
        new_node = MayaNode("newCube", preset=preset)

        # Verify attributes were transferred
        self.assertEqual(new_node.translateX.getAttr(), 1.0)
        self.assertEqual(new_node.translateY.getAttr(), 2.0)
        self.assertEqual(new_node.rotateZ.getAttr(), 45.0)

    def test_error_handling(self):
        """Test error handling for invalid operations."""
        node = MayaNode(self.cube)

        # Test invalid attribute access
        with self.assertWarns(Warning):
            result = node.nonexistentAttr
            self.assertIsNone(result)

        # Test invalid node creation
        with self.assertRaises(ValueError):
            MayaNode("nonexistentNode")

        # Test invalid attribute setting
        with self.assertRaises(Exception):
            node.translateX = "invalid"


def run_tests():
    """Run the test suite."""
    suite = unittest.TestLoader().loadTestsFromTestCase(TestMayaNode)
    unittest.TextTestRunner(verbosity=2).run(suite)


if __name__ == '__main__':
    run_tests()