# utils/falloff.py
from typing import Union, List, Literal, Optional, Callable, Tuple
import numpy as np
from functools import lru_cache
from dw_logger import get_logger

logger = get_logger()

# Type aliases
FalloffType = Literal['linear', 'quadratic', 'smooth', 'smooth2', 'gaussian', 'sine', 'exponential']
WeightList = Union[List[float], np.ndarray]


class FalloffFunction:
    """Class handling different falloff functions"""

    @staticmethod
    def linear(x: np.ndarray) -> np.ndarray:
        """Linear falloff"""
        return x

    @staticmethod
    def quadratic(x: np.ndarray) -> np.ndarray:
        """Quadratic (ease-in) falloff"""
        return x * x

    @staticmethod
    def smooth(x: np.ndarray) -> np.ndarray:
        """Smooth step falloff (3t² - 2t³)"""
        return x * x * (3 - 2 * x)

    @staticmethod
    def smooth2(x: np.ndarray) -> np.ndarray:
        """Smoother step falloff (6t⁵ - 15t⁴ + 10t³)"""
        return x * x * x * (x * (6 * x - 15) + 10)

    @staticmethod
    def gaussian(x: np.ndarray, sigma: float = 0.4) -> np.ndarray:
        """Gaussian falloff"""
        return np.exp(-(x - 1) ** 2 / (2 * sigma ** 2))

    @staticmethod
    def sine(x: np.ndarray) -> np.ndarray:
        """Sinusoidal falloff"""
        return 0.5 * (1 + np.cos(np.pi * (1 - x)))

    @staticmethod
    def exponential(x: np.ndarray, power: float = 2.0) -> np.ndarray:
        """Exponential falloff"""
        return 1 - np.exp(-power * x)


class FalloffCurve:
    """Class for creating and manipulating falloff curves"""

    def __init__(self, falloff_type: FalloffType = 'linear', **kwargs):
        self.falloff_type = falloff_type
        self.params = kwargs
        self._cached_curve: Optional[np.ndarray] = None

    def evaluate(self, values: WeightList) -> np.ndarray:
        """Evaluate falloff for given values"""
        x = np.array(values, dtype=np.float32)

        # Get falloff function
        func = getattr(FalloffFunction, self.falloff_type, None)
        if func is None:
            logger.warning(f"Unknown falloff type: {self.falloff_type}, using linear")
            return x

        try:
            # Apply falloff function with parameters
            result = func(x, **self.params)
            return np.clip(result, 0.0, 1.0)

        except Exception as e:
            logger.error(f"Falloff evaluation failed: {e}")
            return x

    @lru_cache(maxsize=128)
    def generate_curve(self, resolution: int = 100) -> np.ndarray:
        """Generate falloff curve at specified resolution"""
        x = np.linspace(0, 1, resolution)
        return self.evaluate(x)

    def blend(self, other: 'FalloffCurve', blend_factor: float = 0.5) -> 'FalloffCurve':
        """Blend this falloff curve with another"""

        def blended_falloff(x: np.ndarray) -> np.ndarray:
            result1 = self.evaluate(x)
            result2 = other.evaluate(x)
            return result1 * (1 - blend_factor) + result2 * blend_factor

        return CustomFalloff(blended_falloff)


class CustomFalloff(FalloffCurve):
    """Class for custom falloff functions"""

    def __init__(self, falloff_func: Callable[[np.ndarray], np.ndarray]):
        super().__init__()
        self._falloff_func = falloff_func

    def evaluate(self, values: WeightList) -> np.ndarray:
        """Evaluate custom falloff function"""
        try:
            x = np.array(values, dtype=np.float32)
            result = self._falloff_func(x)
            return np.clip(result, 0.0, 1.0)
        except Exception as e:
            logger.error(f"Custom falloff evaluation failed: {e}")
            return np.array(values)


def apply_falloff(weights: WeightList,
                  falloff_type: FalloffType = 'linear',
                  **kwargs) -> np.ndarray:
    """Apply falloff to weights.

    Args:
        weights: Input weight values
        falloff_type: Type of falloff curve
        **kwargs: Additional parameters for falloff function

    Returns:
        Modified weights
    """
    curve = FalloffCurve(falloff_type, **kwargs)
    return curve.evaluate(weights)

def apply_falloff(weights: np.ndarray, falloff: str) -> np.ndarray:
    """Vectorized falloff application"""
    if falloff == 'linear':
        return weights
    elif falloff == 'quadratic':
        return np.square(weights)
    elif falloff == 'smooth':
        return weights * weights * (3 - 2 * weights)
    elif falloff == 'smooth2':
        return weights * weights * weights * (weights * (6 * weights - 15) + 10)
    return weights


if __name__ == '__main__':
    def run_falloff_tests():
        """Test falloff functionality"""
        try:
            # Test basic falloff types
            test_values = np.linspace(0, 1, 10)
            falloff_types: List[FalloffType] = ['linear', 'quadratic', 'smooth', 'smooth2', 'gaussian', 'sine',
                                                'exponential']

            for f_type in falloff_types:
                result = apply_falloff(test_values, f_type)
                assert len(result) == len(test_values)
                assert np.all((result >= 0) & (result <= 1))
                logger.info(f"{f_type} falloff test passed")

            # Test custom falloff
            control_points = [(0, 0), (0.5, 0.8), (1, 1)]
            custom = create_custom_falloff(control_points)
            result = custom.evaluate(test_values)
            assert len(result) == len(test_values)
            logger.info("Custom falloff test passed")

            # Test falloff blending
            curve1 = FalloffCurve('linear')
            curve2 = FalloffCurve('quadratic')
            blended = curve1.blend(curve2, 0.5)
            result = blended.evaluate(test_values)
            assert len(result) == len(test_values)
            logger.info("Falloff blending test passed")

            # Test curve generation
            curve = FalloffCurve('smooth')
            generated = curve.generate_curve(100)
            assert len(generated) == 100
            logger.info("Curve generation test passed")

            return True

        except Exception as e:
            logger.error(f"Falloff tests failed: {e}")
            return False


    # Run tests
    logger.info("Starting falloff tests...")
    if run_falloff_tests():
        logger.info("Falloff tests completed successfully")
    else:
        logger.error("Falloff tests failed")