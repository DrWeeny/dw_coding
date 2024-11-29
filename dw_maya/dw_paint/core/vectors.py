from maya import cmds
import numpy as np
from typing import Union, Tuple, Literal, Optional, Dict
from enum import Enum
from maya.api import OpenMaya as om
from dw_logger import get_logger

logger = get_logger()

# Type aliases
Vector3D = Union[Tuple[float, float, float], np.ndarray]
Matrix3D = np.ndarray  # 3x3 matrix


class VectorDirection(Enum):
    """Predefined vector directions"""
    X = "x"
    NEG_X = "-x"
    Y = "y"
    NEG_Y = "-y"
    Z = "z"
    NEG_Z = "-z"
    XY = "xy"
    NEG_XY = "-xy"
    XZ = "xz"
    NEG_XZ = "-xz"
    YZ = "yz"
    NEG_YZ = "-yz"
    RADIAL_OUT = "radial_out"
    RADIAL_IN = "radial_in"


class VectorUtils:
    """Utility class for vector operations"""

    _PREDEFINED_VECTORS: Dict[str, Vector3D] = {
        VectorDirection.X.value: (1, 0, 0),
        VectorDirection.NEG_X.value: (-1, 0, 0),
        VectorDirection.Y.value: (0, 1, 0),
        VectorDirection.NEG_Y.value: (0, -1, 0),
        VectorDirection.Z.value: (0, 0, 1),
        VectorDirection.NEG_Z.value: (0, 0, -1)
    }

    @staticmethod
    def normalize(vector: Vector3D) -> np.ndarray:
        """Normalize vector to unit length"""
        vector = np.array(vector, dtype=np.float32)
        magnitude = np.linalg.norm(vector)
        return np.zeros(3) if magnitude == 0 else vector / magnitude

    @staticmethod
    def get_direction_vector(direction: Union[str, Vector3D]) -> np.ndarray:
        """Get normalized direction vector from predefined direction or custom vector"""
        if isinstance(direction, str):
            # Handle composite directions
            if direction in ["xy", "yx"]:
                return VectorUtils.normalize((1, 1, 0))
            elif direction in ["-xy", "-yx"]:
                return VectorUtils.normalize((-1, -1, 0))
            elif direction in ["xz", "zx"]:
                return VectorUtils.normalize((1, 0, 1))
            elif direction in ["-xz", "-zx"]:
                return VectorUtils.normalize((-1, 0, -1))
            elif direction in ["yz", "zy"]:
                return VectorUtils.normalize((0, 1, 1))
            elif direction in ["-yz", "-zy"]:
                return VectorUtils.normalize((0, -1, -1))

            # Handle predefined directions
            return np.array(VectorUtils._PREDEFINED_VECTORS.get(direction, (1, 0, 0)))

        return VectorUtils.normalize(direction)

    @staticmethod
    def dot_product(v1: Vector3D, v2: Vector3D) -> float:
        """Calculate dot product of two vectors"""
        return float(np.dot(np.array(v1), np.array(v2)))

    @staticmethod
    def cross_product(v1: Vector3D, v2: Vector3D) -> np.ndarray:
        """Calculate cross product of two vectors"""
        return np.cross(np.array(v1), np.array(v2))

    @staticmethod
    def angle_between(v1: Vector3D, v2: Vector3D) -> float:
        """Calculate angle between two vectors in radians"""
        v1_u = VectorUtils.normalize(v1)
        v2_u = VectorUtils.normalize(v2)
        return np.arccos(np.clip(np.dot(v1_u, v2_u), -1.0, 1.0))

    @staticmethod
    def project_vector(vector: Vector3D, onto: Vector3D) -> np.ndarray:
        """Project vector onto another vector"""
        onto = np.array(onto)
        return onto * np.dot(vector, onto) / np.dot(onto, onto)

    @staticmethod
    def distance_along_vector(point: Vector3D,
                              vector: Vector3D,
                              origin: Optional[Vector3D] = None,
                              mode: Literal['projection', 'distance'] = 'projection') -> float:
        """Calculate signed distance of point along vector"""
        if origin is None:
            origin = np.zeros(3)

        point = np.array(point)
        vector = VectorUtils.normalize(vector)
        origin = np.array(origin)

        to_point = point - origin

        if mode == 'projection':
            return float(np.dot(to_point, vector))
        return float(np.linalg.norm(to_point))

    @staticmethod
    def get_perpendicular(vector: Vector3D) -> np.ndarray:
        """Get a vector perpendicular to input vector"""
        v = np.array(vector)
        # Find least significant component
        min_idx = np.argmin(np.abs(v))
        # Create perpendicular vector by cross product with unit vector
        unit = np.zeros(3)
        unit[min_idx] = 1.0
        return VectorUtils.normalize(np.cross(v, unit))


class MayaVectorUtils:
    """Maya-specific vector utilities"""

    @staticmethod
    def to_mvector(vector: Vector3D) -> om.MVector:
        """Convert to Maya vector"""
        return om.MVector(vector[0], vector[1], vector[2])

    @staticmethod
    def from_mvector(mvector: om.MVector) -> np.ndarray:
        """Convert from Maya vector"""
        return np.array([mvector.x, mvector.y, mvector.z])

    @staticmethod
    def transform_vector(vector: Vector3D,
                         matrix: Union[om.MMatrix, om.MTransformationMatrix]) -> np.ndarray:
        """Transform vector by Maya matrix"""
        mv = MayaVectorUtils.to_mvector(vector)
        transformed = mv * matrix
        return MayaVectorUtils.from_mvector(transformed)

    @staticmethod
    def get_axis_vector(transform: str, axis: Literal['x', 'y', 'z']) -> np.ndarray:
        """Get transformed axis vector from Maya transform node"""
        try:
            # Get world matrix
            matrix = om.MMatrix(cmds.xform(transform, q=True, matrix=True, ws=True))
            # Get axis index
            axis_idx = {'x': 0, 'y': 1, 'z': 2}[axis.lower()]
            # Extract axis vector
            return np.array([matrix(i, axis_idx) for i in range(3)])
        except Exception as e:
            logger.error(f"Error getting axis vector: {e}")
            return np.array([1, 0, 0])  # Default to X axis


if __name__ == '__main__':
    # Test vector operations
    def run_vector_tests():
        """Run tests for vector operations"""
        try:
            # Test normalization
            v1 = (3, 4, 0)
            norm_v1 = VectorUtils.normalize(v1)
            assert np.allclose(np.linalg.norm(norm_v1), 1.0)
            logger.info("Normalization test passed")

            # Test direction vectors
            for direction in VectorDirection:
                vec = VectorUtils.get_direction_vector(direction.value)
                assert np.allclose(np.linalg.norm(vec), 1.0)
            logger.info("Direction vectors test passed")

            # Test vector products
            v2 = (0, 1, 0)
            dot = VectorUtils.dot_product(norm_v1, v2)
            cross = VectorUtils.cross_product(norm_v1, v2)
            logger.info("Vector products test passed")

            # Test angle calculation
            angle = VectorUtils.angle_between(v1, v2)
            assert 0 <= angle <= np.pi
            logger.info("Angle calculation test passed")

            # Test vector projection
            proj = VectorUtils.project_vector(v1, v2)
            logger.info("Vector projection test passed")

            # Test distance calculation
            point = (1, 1, 1)
            dist = VectorUtils.distance_along_vector(point, v1)
            logger.info("Distance calculation test passed")

            return True

        except Exception as e:
            logger.error(f"Vector tests failed: {e}")
            return False


    def run_maya_vector_tests():
        """Run tests for Maya vector operations"""
        try:
            from maya import cmds

            # Create test object
            cube = cmds.polyCube(name='vectorTest_cube')[0]
            cmds.move(1, 2, 3, cube)
            cmds.rotate(45, 0, 0, cube)

            # Test axis vector extraction
            x_axis = MayaVectorUtils.get_axis_vector(cube, 'x')
            y_axis = MayaVectorUtils.get_axis_vector(cube, 'y')
            z_axis = MayaVectorUtils.get_axis_vector(cube, 'z')

            # Test transformation
            point = (1, 0, 0)
            matrix = om.MMatrix(cmds.xform(cube, q=True, matrix=True, ws=True))
            transformed = MayaVectorUtils.transform_vector(point, matrix)

            # Cleanup
            cmds.delete(cube)

            logger.info("Maya vector tests passed")
            return True

        except Exception as e:
            logger.error(f"Maya vector tests failed: {e}")
            if cmds.objExists('vectorTest_cube'):
                cmds.delete('vectorTest_cube')
            return False


    # Run all tests
    logger.info("Starting vector system tests...")

    if run_vector_tests():
        logger.info("Basic vector tests completed successfully")
    else:
        logger.error("Basic vector tests failed")

    if run_maya_vector_tests():
        logger.info("Maya vector tests completed successfully")
    else:
        logger.error("Maya vector tests failed")