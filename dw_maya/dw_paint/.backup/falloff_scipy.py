def create_custom_falloff(control_points: List[Tuple[float, float]]) -> FalloffCurve:
    """Create custom falloff curve from control points.

    Args:
        control_points: List of (x, y) points defining the curve

    Returns:
        CustomFalloff instance
    """
    from scipy.interpolate import interp1d

    # Sort points by x value
    points = sorted(control_points)
    x_vals = [p[0] for p in points]
    y_vals = [p[1] for p in points]

    # Create interpolation function
    interp_func = interp1d(x_vals, y_vals, kind='cubic', bounds_error=False, fill_value=(y_vals[0], y_vals[-1]))

    def custom_falloff(x: np.ndarray) -> np.ndarray:
        return interp_func(x)

    return CustomFalloff(custom_falloff)