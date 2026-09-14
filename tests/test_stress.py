"""Stress distribution validation against first principles."""

import math

import pytest

from burh.stress import (
    boussinesq_rectangle_center,
    boussinesq_rectangle_corner,
    influence_depth,
    newmark_corner_influence,
    two_to_one,
)


def _numeric_corner(b: float, l: float, z: float, n: int = 900) -> float:
    """Direct midpoint integration of the Boussinesq point solution over the
    rectangle, evaluated at the corner, for unit load.

    This is the ground truth: it depends on nothing but the Boussinesq point
    solution, so it validates the closed form independently of any table.
    """
    total = 0.0
    dx, dy = b / n, l / n
    z3 = z**3
    for i in range(n):
        x = (i + 0.5) * dx
        x2 = x * x
        s = 0.0
        for j in range(n):
            y = (j + 0.5) * dy
            s += z3 / (x2 + y * y + z * z) ** 2.5
        total += s
    return 3.0 / (2.0 * math.pi) * total * dx * dy


@pytest.mark.parametrize("b,l,z", [(1.0, 1.0, 1.0), (2.0, 2.0, 1.0),
                                   (0.5, 1.0, 1.0), (5.0, 5.0, 1.0)])
def test_newmark_matches_direct_integration(b, l, z):
    assert newmark_corner_influence(b / z, l / z) == pytest.approx(
        _numeric_corner(b, l, z), rel=2e-5
    )


def test_arctan_branch_does_not_collapse_for_large_areas():
    """When m^2 n^2 > m^2+n^2+1 the arctan argument goes negative and pi must
    be added. Getting this wrong makes wide, shallow areas collapse toward
    zero instead of approaching 0.25."""
    values = [newmark_corner_influence(m, m) for m in (2, 5, 10, 20, 50, 200)]
    assert all(a < b for a, b in zip(values, values[1:])), "must be monotonic"
    assert values[-1] == pytest.approx(0.25, abs=1e-4)
    assert all(v > 0.2 for v in values[1:]), "collapse detected"


def test_influence_factor_is_symmetric_in_m_and_n():
    for m, n in ((1.0, 3.0), (0.4, 2.7), (5.0, 0.1)):
        assert newmark_corner_influence(m, n) == pytest.approx(
            newmark_corner_influence(n, m), rel=1e-14
        )


def test_zero_dimension_gives_zero_influence():
    assert newmark_corner_influence(0.0, 5.0) == 0.0
    assert newmark_corner_influence(5.0, 0.0) == 0.0


def test_center_is_four_times_the_quarter_corner():
    q, b, l, z = 100.0, 2.0, 3.0, 1.5
    expected = 4.0 * q * newmark_corner_influence((b / 2) / z, (l / 2) / z)
    assert boussinesq_rectangle_center(q, b, l, z) == pytest.approx(expected, rel=1e-14)


def test_stress_at_surface_equals_applied_pressure():
    assert boussinesq_rectangle_center(100.0, 2.0, 2.0, 0.0) == 100.0
    assert boussinesq_rectangle_corner(100.0, 2.0, 2.0, 0.0) == 100.0


def test_center_stress_exceeds_corner_stress():
    for z in (0.5, 1.0, 3.0):
        c = boussinesq_rectangle_center(100.0, 2.0, 2.0, z)
        k = boussinesq_rectangle_corner(100.0, 2.0, 2.0, z)
        assert c > k


def test_stress_decays_monotonically_with_depth():
    vals = [boussinesq_rectangle_center(100.0, 2.0, 2.0, z)
            for z in (0.5, 1.0, 2.0, 4.0, 8.0, 16.0)]
    assert all(a > b for a, b in zip(vals, vals[1:]))


def test_two_to_one_conserves_total_load():
    q, b, l = 100.0, 2.0, 3.0
    for z in (0.0, 1.0, 5.0):
        spread = two_to_one(q, b, l, z) * (b + z) * (l + z)
        assert spread == pytest.approx(q * b * l, rel=1e-12)


def test_two_to_one_is_conservative_at_depth_and_unconservative_shallow():
    """The 2:1 rule underestimates stress just below the footing and
    overestimates it deep down. Engineers should know which side they are on."""
    q, b, l = 100.0, 2.0, 2.0
    assert two_to_one(q, b, l, 0.5) < boussinesq_rectangle_center(q, b, l, 0.5)
    assert two_to_one(q, b, l, 8.0) > boussinesq_rectangle_center(q, b, l, 8.0)


def test_influence_depth_hits_the_threshold():
    b = l = 2.0
    q = 100.0
    z = influence_depth(b, l, q, threshold=0.10)
    assert boussinesq_rectangle_center(q, b, l, z) == pytest.approx(0.10 * q, rel=1e-3)


def test_negative_inputs_rejected():
    with pytest.raises(ValueError):
        newmark_corner_influence(-1.0, 1.0)
    with pytest.raises(ValueError):
        two_to_one(100.0, 0.0, 1.0, 1.0)
