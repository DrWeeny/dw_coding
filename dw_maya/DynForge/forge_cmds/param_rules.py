"""
param_rules.py - per-bone parameter rules: a few key values spread over a chain.

Summary:
    A preset stores node-level values, which do not depend on how many bones a
    chain has. Per-bone values do: a 5-bone and a 12-bone chain cannot share a
    list. A rule stores the SHAPE instead - a few keys along the chain - and
    is evaluated for whatever bone count it is applied to, so one preset fits
    every chain.

    Keys are written ``"0:1, 1:.5, 2:.1"`` (position : value). Positions are
    spread evenly from the first bone to the last: with as many bones as keys
    each bone takes its key exactly, with more bones the values in between are
    interpolated, with fewer the keys are sampled. A key may add its handle,
    ``"1:.5:smooth"`` - the interpolation of the segment that STARTS at it
    (linear by default), the same convention and the same smoothstep as the
    RampCurveWidget, so a rule edited as a curve evaluates the way it is drawn.

    Pure python, no Maya: the host applies the values to its own attributes.

Functions:
    parse_keys - "0:1, 1:.5:smooth" -> [(0.0, 1.0, 'linear'), (1.0, 0.5, 'smooth')]
    format_keys - the reverse, for display
    evaluate - the value of every bone, for a bone count
    keys_from_values - one key per bone, from values read off a chain
    to_curve / from_curve - keys <-> RampCurveWidget control points + value range

Example:
    >>> evaluate(parse_keys("0:1, 1:.5, 2:.1"), 3)
    [1.0, 0.5, 0.1]
    >>> evaluate(parse_keys("0:1, 1:.5, 2:.1"), 5)
    [1.0, 0.75, 0.5, 0.3, 0.1]

Author:
    DrWeeny
"""

from __future__ import annotations

from typing import List, Sequence, Tuple

Key = Tuple[float, float, str]   # (position, value, interp of the segment starting here)

INTERPS = ("linear", "smooth")
_INTERP_ALIASES = {"l": "linear", "linear": "linear", "s": "smooth", "smooth": "smooth"}


def _ease(t: float) -> float:
    """Smoothstep (3t^2 - 2t^3), the RampCurveWidget's 'smooth' handle."""
    return t * t * (3 - 2 * t)


def _as_key(key) -> Key:
    """Accept (position, value) or (position, value, interp)."""
    interp = key[2] if len(key) > 2 else "linear"
    return float(key[0]), float(key[1]), interp


def parse_keys(text: str) -> List[Key]:
    """
    Parse ``"0:1, 1:.5:smooth, 2:.1"`` into ``[(position, value, interp), ...]``
    sorted by position. Raises ValueError on a malformed pair, an unknown
    handle or a repeated position - a rule that half-parses would silently
    drive the wrong bones.
    """
    keys = []
    for chunk in text.replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        fields = [f.strip() for f in chunk.split(":")]
        if len(fields) not in (2, 3):
            raise ValueError(f"{chunk!r}: expected 'position:value' or 'position:value:smooth'")
        try:
            position, value = float(fields[0]), float(fields[1])
        except ValueError:
            raise ValueError(f"{chunk!r}: position and value must be numbers")
        interp = "linear"
        if len(fields) == 3:
            interp = _INTERP_ALIASES.get(fields[2].lower())
            if interp is None:
                raise ValueError(f"{chunk!r}: handle must be one of {', '.join(INTERPS)}")
        keys.append((position, value, interp))
    if not keys:
        raise ValueError("no keys")
    keys.sort()
    positions = [k[0] for k in keys]
    if len(set(positions)) != len(positions):
        raise ValueError("a position is given twice")
    return keys


def _short(number: float) -> str:
    """Whole numbers without a decimal, the rest at most 4 significant digits."""
    number = round(float(number), 4)
    return f"{int(number)}" if number.is_integer() else f"{number:g}"


def format_keys(keys: Sequence) -> str:
    """``[(0, 1), (1, .5, 'smooth')]`` -> ``"0:1, 1:0.5:smooth"`` (a linear handle is not written)."""
    out = []
    for key in keys:
        position, value, interp = _as_key(key)
        text = f"{_short(position)}:{_short(value)}"
        if interp != "linear":
            text += f":{interp}"
        out.append(text)
    return ", ".join(out)


def evaluate(keys:  Sequence,
             count: int,) -> List[float]:
    """
    The value of each of `count` bones, root first.

    The keys' positions are stretched over the chain: the first key on the
    first bone, the last key on the last bone, each segment interpolated by
    its starting key's handle. A single key, or a single bone, gives the first
    key's value everywhere.
    """
    if count < 1:
        return []
    keys = sorted(_as_key(k) for k in keys)
    if len(keys) == 1:
        return [keys[0][1]] * count
    first, last = keys[0][0], keys[-1][0]
    values = []
    for index in range(count):
        u = index / (count - 1) if count > 1 else 0.0
        values.append(_interpolate(keys, first + u * (last - first)))
    return values


def _interpolate(keys:     Sequence[Key],
                 position: float,) -> float:
    """Value at `position` between the surrounding keys (clamped at the ends)."""
    if position <= keys[0][0]:
        return keys[0][1]
    for (p0, v0, interp), (p1, v1, _next) in zip(keys, keys[1:]):
        if position <= p1:
            t = (position - p0) / (p1 - p0)
            if interp == "smooth":
                t = _ease(t)
            return v0 + t * (v1 - v0)
    return keys[-1][1]


def keys_from_values(values: Sequence[float]) -> List[Key]:
    """One linear key per bone (positions 0..n-1): a chain's current values as a rule."""
    return [(float(i), float(v), "linear") for i, v in enumerate(values)]


def value_range(keys: Sequence) -> Tuple[float, float]:
    """(low, high) of the key values, widened to 0..high (or low..low+1) when they are all equal."""
    values = [_as_key(k)[1] for k in keys]
    low, high = min(values), max(values)
    if high - low < 1e-9:
        low, high = (0.0, high) if high > 0 else (low, low + 1.0)
    return low, high


def to_curve(keys:  Sequence,
             low:   float,
             high:  float,) -> List[Key]:
    """
    Keys as RampCurveWidget control points: positions normalised to 0..1
    (first key 0, last key 1), values mapped from low..high to 0..1 (clamped -
    the widget's grid is 0..1).
    """
    keys = sorted(_as_key(k) for k in keys)
    first, last = keys[0][0], keys[-1][0]
    span = (last - first) or 1.0
    scale = (high - low) or 1.0
    return [((p - first) / span, min(max((v - low) / scale, 0.0), 1.0), i) for p, v, i in keys]


def from_curve(points:    Sequence,
               low:       float,
               high:      float,
               bones:     int = 0,) -> List[Key]:
    """
    RampCurveWidget control points back to keys: values from 0..1 to low..high,
    positions written in bone units when `bones` > 1 (so "1:..." reads as the
    second bone of the chain the curve was edited on), else left 0..1.
    """
    scale = (bones - 1) if bones > 1 else 1.0
    return [(round(float(p[0]) * scale, 3), low + float(p[1]) * (high - low), _as_key(p)[2])
            for p in sorted(points, key=lambda p: p[0])]
