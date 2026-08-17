"""
Procedural wind for a nucleus solver, baked to keyframes.

Summary:
    Builds a wind animation in plain python - gusting speed, a direction
    that rotates and sways, a varying windNoise - then writes it as
    keyframes on the nucleus. The math is deliberately kept out of a Maya
    expression: an expression re-evaluates on every solver step, cannot be
    plotted before committing, and confines the model to what MEL can say.
    Keyframes are inspectable in the graph editor, hand-editable after the
    fact, and cache identically on every machine.

Features:
    - Seeded fractal value noise, no numpy, no `random` state: the same
      seed gives the same wind on any machine and in any session.
    - Speed gusts, direction rotation + sway, windNoise variance, each on
      its own noise channel so they do not move in lockstep.
    - `evaluate` never touches the scene: the curves can be inspected or
      plotted before a single key is written, and the model can be tested
      outside Maya against a stubbed `cmds` (only `upAxis` is called, and
      only when `up_axis` was left unset).
    - ASCII plot for the script editor, so the noise can be judged in time
      without leaving Maya.

Classes:
    ValueNoise: Seeded fractal value noise over one dimension.
    WindSettings: The wind model parameters.

Functions:
    evaluate: Sample the model over a frame range (no Maya).
    bake_wind: Write the sampled curves as keyframes on a nucleus.
    ascii_plot: Draw sampled curves as text.

Example:
    >>> import dw_maya.dw_nucleus_utils.dw_wind as dw_wind
    >>> settings = dw_wind.WindSettings(speed=12.0,
    ...                                 speed_variance=6.0,
    ...                                 gust_period=18.0,
    ...                                 azimuth=45.0,
    ...                                 rotate_period=0.0,
    ...                                 direction_variance=25.0,
    ...                                 seed=7)
    >>> data = dw_wind.evaluate(settings, 1, 120)
    >>> print(dw_wind.ascii_plot(data))
    >>> dw_wind.bake_wind('nucleus1', settings, 1, 120)

TODO:
    Qt panel: live plot + sliders over the same `evaluate`, bake on accept.
    Presets (breeze / gusty / storm) once the parameter ranges settle.

Author:
    DrWeeny
"""

import math
from typing import List

from maya import cmds


#: Attributes written by `bake_wind`, in the order they are keyed.
WIND_ATTRS = ['windSpeed',
              'windDirectionX',
              'windDirectionY',
              'windDirectionZ',
              'windNoise']


class ValueNoise(object):
    """
    Seeded fractal value noise over one dimension.

    Lattice values come from an integer hash rather than a stored table,
    so sampling is stateless: the same (x, channel, seed) always gives the
    same value, whatever order the caller samples in.

    Args:
        seed (int): Master seed.
        octaves (int): Number of summed layers. 1 gives a smooth wave,
            4 gives a rough, detailed signal.
        persistence (float): Amplitude factor between octaves.
        lacunarity (float): Frequency factor between octaves.
    """

    def __init__(self,
                 seed: int = 0,
                 octaves: int = 3,
                 persistence: float = 0.5,
                 lacunarity: float = 2.0):
        self.seed = int(seed)
        self.octaves = max(1, int(octaves))
        self.persistence = persistence
        self.lacunarity = lacunarity

    def _lattice(self, i: int, channel: int) -> float:
        """Hash a lattice index to a deterministic value in [-1, 1]."""
        h = (i * 374761393 + channel * 668265263 + self.seed * 2246822519)
        h = h & 0xFFFFFFFF
        h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
        h = h ^ (h >> 16)
        return (h / float(0xFFFFFFFF)) * 2.0 - 1.0

    def _layer(self, x: float, channel: int) -> float:
        """One octave: smoothstep between two lattice values."""
        i = int(math.floor(x))
        t = x - i
        t = t * t * (3.0 - 2.0 * t)
        a = self._lattice(i, channel)
        b = self._lattice(i + 1, channel)
        return a + (b - a) * t

    def sample(self, x: float, channel: int = 0) -> float:
        """
        Sample the fractal noise.

        Args:
            x (float): Position along the noise, in lattice units.
            channel (int): Independent noise stream. Speed, direction and
                windNoise each use their own so they do not correlate.

        Returns:
            float: Value in [-1, 1].
        """
        total = 0.0
        norm = 0.0
        amp = 1.0
        freq = 1.0
        for octave in range(self.octaves):
            total += amp * self._layer(x * freq, channel * 32 + octave)
            norm += amp
            amp *= self.persistence
            freq *= self.lacunarity
        if not norm:
            return 0.0
        return total / norm


class WindSettings(object):
    """
    Parameters of the wind model.

    Every `*_period` is expressed in frames - the time it takes the
    matching signal to go through one cycle - because that is what an
    artist can read off a playblast. Every `*_variance` is the peak
    deviation from the base value, in the unit of that base value.

    Args:
        speed (float): Base wind speed.
        speed_variance (float): Peak gust deviation, same unit as speed.
            The result is clamped at 0, wind never blows backwards.
        gust_period (float): Frames per gust cycle.
        azimuth (float): Base direction around the up axis, in degrees.
        elevation (float): Base tilt above the ground plane, in degrees.
        rotate_period (float): Frames for the direction to turn a full
            360 degrees. 0 disables the rotation (sway only).
        direction_variance (float): Peak azimuth sway, in degrees.
        elevation_variance (float): Peak elevation sway, in degrees.
        direction_period (float): Frames per sway cycle.
        noise (float): Base nucleus windNoise.
        noise_variance (float): Peak windNoise deviation. Clamped at 0.
        noise_period (float): Frames per windNoise cycle.
        octaves (int): Roughness of every signal, see `ValueNoise`.
        seed (int): Master seed.
        up_axis (str): 'y' or 'z'. Defaults to the scene up axis.
    """

    def __init__(self,
                 speed: float = 10.0,
                 speed_variance: float = 4.0,
                 gust_period: float = 24.0,
                 azimuth: float = 0.0,
                 elevation: float = 0.0,
                 rotate_period: float = 0.0,
                 direction_variance: float = 20.0,
                 elevation_variance: float = 5.0,
                 direction_period: float = 48.0,
                 noise: float = 0.0,
                 noise_variance: float = 0.0,
                 noise_period: float = 36.0,
                 octaves: int = 3,
                 seed: int = 0,
                 up_axis: str = None):
        self.speed = speed
        self.speed_variance = speed_variance
        self.gust_period = gust_period
        self.azimuth = azimuth
        self.elevation = elevation
        self.rotate_period = rotate_period
        self.direction_variance = direction_variance
        self.elevation_variance = elevation_variance
        self.direction_period = direction_period
        self.noise = noise
        self.noise_variance = noise_variance
        self.noise_period = noise_period
        self.octaves = octaves
        self.seed = seed
        self.up_axis = up_axis

    def resolved_up_axis(self) -> str:
        """Return the up axis, asking Maya only when it was left unset."""
        if self.up_axis:
            return self.up_axis.lower()
        try:
            return cmds.upAxis(query=True, axis=True).lower()
        except Exception:
            return 'y'


def direction_vector(azimuth: float,
                     elevation: float,
                     up_axis: str = 'y') -> List[float]:
    """
    Convert an azimuth/elevation pair to a unit direction vector.

    Args:
        azimuth (float): Degrees around the up axis.
        elevation (float): Degrees above the ground plane.
        up_axis (str): 'y' or 'z'.

    Returns:
        list: [x, y, z] unit vector.
    """
    az = math.radians(azimuth)
    el = math.radians(elevation)
    ground_a = math.cos(el) * math.sin(az)
    ground_b = math.cos(el) * math.cos(az)
    up = math.sin(el)
    if up_axis == 'z':
        return [ground_a, ground_b, up]
    return [ground_a, up, ground_b]


def frame_range(start: float,
                end: float,
                step: float = 1.0) -> List[float]:
    """
    Build an inclusive frame list.

    Args:
        start (float): First frame.
        end (float): Last frame, always included even when `step` does
            not divide the range evenly.
        step (float): Frames between samples.

    Returns:
        list: Frames.
    """
    if step <= 0:
        cmds.error(f'Frame step must be positive, got {step}')
    frames = []
    current = float(start)
    while current < end:
        frames.append(current)
        current += step
    frames.append(float(end))
    return frames


def evaluate(settings: WindSettings,
             start: float,
             end: float,
             step: float = 1.0) -> dict:
    """
    Sample the wind model over a frame range. No Maya scene is touched.

    Args:
        settings (WindSettings): The model.
        start (float): First frame.
        end (float): Last frame.
        step (float): Frames between samples. Above 1 the baked curve is
            interpolated by Maya, which is usually what you want for a
            slow gust and never for a jittery one.

    Returns:
        dict: {'frames': [...], 'windSpeed': [...], 'windDirectionX': [...],
            'windDirectionY': [...], 'windDirectionZ': [...],
            'windNoise': [...], 'azimuth': [...], 'elevation': [...]}.
            `azimuth` and `elevation` are there to be plotted and read;
            they are not baked.
    """
    noise = ValueNoise(seed=settings.seed, octaves=settings.octaves)
    up_axis = settings.resolved_up_axis()
    frames = frame_range(start, end, step)

    data = {'frames': frames,
            'azimuth': [],
            'elevation': [],
            'windSpeed': [],
            'windDirectionX': [],
            'windDirectionY': [],
            'windDirectionZ': [],
            'windNoise': []}

    for frame in frames:
        # Speed: base plus gust, never negative
        gust = 0.0
        if settings.gust_period > 0 and settings.speed_variance:
            gust = noise.sample(frame / settings.gust_period, channel=0)
        speed = max(0.0, settings.speed + settings.speed_variance * gust)

        # Direction: a steady turn plus an independent sway
        azimuth = settings.azimuth
        if settings.rotate_period:
            azimuth += 360.0 * (frame - frames[0]) / settings.rotate_period
        sway = 0.0
        if settings.direction_period > 0 and settings.direction_variance:
            sway = noise.sample(frame / settings.direction_period, channel=1)
        azimuth += settings.direction_variance * sway

        elevation = settings.elevation
        if settings.direction_period > 0 and settings.elevation_variance:
            tilt = noise.sample(frame / settings.direction_period, channel=2)
            elevation += settings.elevation_variance * tilt

        vector = direction_vector(azimuth, elevation, up_axis)

        # windNoise on its own channel
        wind_noise = settings.noise
        if settings.noise_period > 0 and settings.noise_variance:
            jitter = noise.sample(frame / settings.noise_period, channel=3)
            wind_noise += settings.noise_variance * jitter
        wind_noise = max(0.0, wind_noise)

        data['azimuth'].append(azimuth)
        data['elevation'].append(elevation)
        data['windSpeed'].append(speed)
        data['windDirectionX'].append(vector[0])
        data['windDirectionY'].append(vector[1])
        data['windDirectionZ'].append(vector[2])
        data['windNoise'].append(wind_noise)

    return data


def bake_wind(nucleus: str,
              settings: WindSettings,
              start: float,
              end: float,
              step: float = 1.0,
              clear: bool = True,
              tangent: str = 'spline') -> dict:
    """
    Bake the wind model onto a nucleus as keyframes.

    Args:
        nucleus (str): The nucleus node.
        settings (WindSettings): The model.
        start (float): First frame.
        end (float): Last frame.
        step (float): Frames between keys.
        clear (bool): Remove existing keys on the wind attributes first.
            With `clear=False` the new keys merge into what is there,
            which is how a retake over a hand-edited curve goes wrong.
        tangent (str): Tangent type applied to the baked keys.

    Returns:
        dict: The sampled data, as returned by `evaluate`.

    Raises:
        RuntimeError: If the node does not exist or is not a nucleus.
    """
    if not cmds.objExists(nucleus):
        cmds.error(f'No such node: {nucleus}')

    node_type = cmds.nodeType(nucleus)
    if node_type != 'nucleus':
        cmds.error(f'{nucleus} is a {node_type}, expected a nucleus')

    data = evaluate(settings, start, end, step)
    frames = data['frames']

    for attr in WIND_ATTRS:
        plug = f'{nucleus}.{attr}'
        if cmds.getAttr(plug, lock=True):
            cmds.error(f'{plug} is locked')

        # A connection that is not an anim curve (an expression, a
        # constraint) would silently lose against the keys we write
        connections = cmds.listConnections(plug,
                                           source=True,
                                           destination=False) or []
        foreign = [c for c in connections
                   if not cmds.nodeType(c).startswith('animCurve')]
        if foreign:
            cmds.error(f'{plug} is driven by {foreign[0]}, disconnect it '
                       f'before baking')

        if clear:
            cmds.cutKey(nucleus, attribute=attr, clear=True)

        for frame, value in zip(frames, data[attr]):
            cmds.setKeyframe(nucleus,
                             attribute=attr,
                             time=frame,
                             value=value)

        cmds.keyTangent(nucleus,
                        attribute=attr,
                        inTangentType=tangent,
                        outTangentType=tangent)

    return data


def ascii_plot(data: dict,
               keys: List[str] = None,
               width: int = 78,
               height: int = 11) -> str:
    """
    Draw sampled curves as text, one block per key.

    Args:
        data (dict): Output of `evaluate`.
        keys (list): Which curves to draw. Defaults to speed, azimuth and
            windNoise - the three an artist actually judges.
        width (int): Columns per block.
        height (int): Rows per block.

    Returns:
        str: The plot, ready to print.

    Example:
        >>> print(ascii_plot(evaluate(WindSettings(), 1, 120)))
    """
    keys = keys or ['windSpeed', 'azimuth', 'windNoise']
    frames = data['frames']
    lines = []

    for key in keys:
        values = data.get(key)
        if not values:
            continue

        low = min(values)
        high = max(values)
        span = high - low
        lines.append(f'{key}  [{low:.3f} .. {high:.3f}]  '
                     f'frames {frames[0]:g}-{frames[-1]:g}')

        # Resample the curve onto the plot columns
        columns = []
        for col in range(width):
            index = int(round(col * (len(values) - 1) / float(width - 1)))
            columns.append(values[index])

        grid = [[' '] * width for _ in range(height)]
        for col, value in enumerate(columns):
            if span:
                row = int(round((value - low) / span * (height - 1)))
            else:
                row = (height - 1) // 2
            grid[height - 1 - row][col] = '*'

        for row in grid:
            lines.append(f'|{"".join(row)}')
        lines.append(f'+{"-" * width}')
        lines.append('')

    return '\n'.join(lines)