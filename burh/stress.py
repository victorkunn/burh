"""Vertical stress increase beneath a loaded area.

Two methods are provided because engineers legitimately disagree:

* :func:`boussinesq_rectangle_center` - elastic half space, Newmark's
  integration of the Boussinesq point solution over a rectangle. Correct
  theory, used for settlement.
* :func:`two_to_one` - the 2V:1H approximation. Cruder, but it is what many
  office standards mandate, so it is available and clearly labelled.
"""

from __future__ import annotations

import math


def newmark_corner_influence(m: float, n: float) -> float:
    """Influence factor for the CORNER of a uniformly loaded rectangle.

    m = B/z, n = L/z (interchangeable). Newmark (1935):

        I = 1/(4 pi) * [ 2mn*sqrt(m^2+n^2+1)/(m^2+n^2+1+m^2 n^2)
                          * (m^2+n^2+2)/(m^2+n^2+1)
                        + arctan( 2mn*sqrt(m^2+n^2+1)/(m^2+n^2+1-m^2 n^2) ) ]

    The arctan branch is the trap: when m^2 n^2 > m^2+n^2+1 the argument goes
    negative and pi must be added, otherwise the factor collapses for wide
    areas at shallow depth.
    """
    if m < 0 or n < 0:
        raise ValueError("m and n must be non-negative.")
    if m == 0.0 or n == 0.0:
        return 0.0

    m2, n2 = m * m, n * n
    s = m2 + n2 + 1.0
    root = math.sqrt(s)
    num = 2.0 * m * n * root

    first = (num / (s + m2 * n2)) * ((m2 + n2 + 2.0) / s)

    denom = s - m2 * n2
    angle = math.atan2(num, denom)
    if denom < 0.0:
        # atan2 already returns the correct branch in (pi/2, pi]; using
        # atan() here instead would silently lose the +pi.
        pass
    return (first + angle) / (4.0 * math.pi)


def boussinesq_rectangle_center(q: float, b: float, l: float, z: float) -> float:
    """Vertical stress increase [kPa] under the CENTER of a uniformly loaded
    rectangle, by superposition of four quarter-rectangles."""
    if z <= 0.0:
        return q
    if b <= 0 or l <= 0:
        raise ValueError("Loaded area dimensions must be positive.")
    m = (b / 2.0) / z
    n = (l / 2.0) / z
    return 4.0 * q * newmark_corner_influence(m, n)


def boussinesq_rectangle_corner(q: float, b: float, l: float, z: float) -> float:
    """Vertical stress increase [kPa] under a CORNER of the loaded area."""
    if z <= 0.0:
        return q
    return q * newmark_corner_influence(b / z, l / z)


def two_to_one(q: float, b: float, l: float, z: float) -> float:
    """2V:1H load spread approximation [kPa]."""
    if z < 0:
        raise ValueError("Depth must be >= 0.")
    if b <= 0 or l <= 0:
        raise ValueError("Loaded area dimensions must be positive.")
    return q * (b * l) / ((b + z) * (l + z))


def influence_depth(b: float, l: float, q: float, threshold: float = 0.10,
                    z_max_ratio: float = 10.0) -> float:
    """Depth at which delta-sigma falls to ``threshold`` * q.

    Used to decide how deep the consolidation summation must run. Defaults to
    the conventional 10% criterion.
    """
    lo, hi = 0.0, z_max_ratio * max(b, l)
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if boussinesq_rectangle_center(q, b, l, mid) > threshold * q:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)
