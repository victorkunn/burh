"""Bearing capacity validation.

Every numeric expectation here is either a published table value or a full
hand calculation reproduced in the test body. Nothing is a regression
snapshot of the code's own output.
"""

import math

import pytest

from burh.bearing import (
    BearingMethod,
    bearing_factors,
    depth_factors,
    inclination_factors,
    shape_factors,
    ultimate_bearing_capacity,
)
from burh.soil import Drainage, SoilLayer, SoilProfile

# Vesic factors, Das "Principles of Foundation Engineering" Table 3.3.
VESIC_TABLE = {
    0: (5.14, 1.00, 0.00),
    10: (8.35, 2.47, 1.22),
    20: (14.83, 6.40, 5.39),
    25: (20.72, 10.66, 10.88),
    30: (30.14, 18.40, 22.40),
    35: (46.12, 33.30, 48.03),
    40: (75.31, 64.20, 109.41),
    45: (133.88, 134.88, 271.76),
}


@pytest.mark.parametrize("phi,expected", sorted(VESIC_TABLE.items()))
def test_vesic_factors_match_published_table(phi, expected):
    nc, nq, ng = expected
    f = bearing_factors(phi, BearingMethod.VESIC)
    # The published table is rounded to 2 decimals, so the achievable
    # agreement is bounded by the table, not by the implementation. A wrong
    # N-factor formula is off by tens of percent, so this still has teeth.
    tol = dict(rel=2e-3, abs=0.01)
    assert f.nc == pytest.approx(nc, **tol)
    assert f.nq == pytest.approx(nq, **tol)
    if ng > 0:
        assert f.ngamma == pytest.approx(ng, **tol)
    else:
        assert f.ngamma == 0.0


@pytest.mark.parametrize("phi,ng", [(30, 15.67), (35, 37.15), (40, 93.69)])
def test_meyerhof_ngamma(phi, ng):
    assert bearing_factors(phi, BearingMethod.MEYERHOF).ngamma == pytest.approx(ng, rel=1e-3)


@pytest.mark.parametrize("phi,ng", [(30, 15.07), (35, 33.92), (40, 79.54)])
def test_hansen_ngamma(phi, ng):
    assert bearing_factors(phi, BearingMethod.HANSEN).ngamma == pytest.approx(ng, rel=1e-3)


def test_nc_phi_zero_is_prandtl():
    assert bearing_factors(0.0).nc == pytest.approx(math.pi + 2.0, rel=1e-12)


def test_vesic_ngamma_is_the_least_conservative():
    """Vesic gives the largest N-gamma across the practical range, so
    switching method can only ever reduce capacity.

    Note Meyerhof and Hansen CROSS near phi ~ 25 deg, because
    N_g,M / N_g,H = tan(1.4 phi) / (1.5 tan phi) passes through unity there.
    Neither is uniformly the more conservative of the two.
    """
    for phi in range(20, 46, 5):
        m = bearing_factors(phi, BearingMethod.MEYERHOF).ngamma
        h = bearing_factors(phi, BearingMethod.HANSEN).ngamma
        v = bearing_factors(phi, BearingMethod.VESIC).ngamma
        assert v > m and v > h, f"Vesic not the largest at phi={phi}"


def test_meyerhof_hansen_ngamma_crossover_near_25_deg():
    """Pin the crossover so the documented caveat stays true."""
    below = bearing_factors(15, BearingMethod.MEYERHOF).ngamma < bearing_factors(15, BearingMethod.HANSEN).ngamma
    above = bearing_factors(35, BearingMethod.MEYERHOF).ngamma > bearing_factors(35, BearingMethod.HANSEN).ngamma
    assert below and above


def test_factors_reject_invalid_phi():
    with pytest.raises(ValueError):
        bearing_factors(-1.0)
    with pytest.raises(ValueError):
        bearing_factors(60.0)


# --------------------------------------------------------------------------
# Full hand calculation
# --------------------------------------------------------------------------


def test_square_footing_full_hand_calculation():
    """B = L = 2 m, Df = 1 m, gamma = 18 kN/m3, phi = 30 deg, c = 0, dry.

    Hand calculation (Vesic):
      q      = 18 * 1.0                                  = 18.000 kPa
      Nq     = e^(pi tan30) tan^2(60)                    = 18.4011
      Nc     = (Nq-1)/tan30                              = 30.1396
      Ng     = 2(Nq+1)tan30                              = 22.4025
      sq     = 1 + (B/L) tan30                           =  1.5774
      sg     = 1 - 0.4(B/L)                              =  0.6000
      k      = Df/B = 0.5
      dq     = 1 + 2 tan30 (1-sin30)^2 (0.5)             =  1.14434
      dg     = 1.0
      term_q = 18 * 18.4011 * 1.5774 * 1.14434           = 597.89 kPa
      term_g = 0.5 * 18 * 2.0 * 22.4025 * 0.6 * 1.0      = 241.95 kPa
      q_ult                                              = 839.84 kPa
    """
    profile = SoilProfile([SoilLayer("Sand", 20.0, 18.0, phi=30.0, spt_n=25)])
    r = ultimate_bearing_capacity(profile, b=2.0, l=2.0, df=1.0, v=500.0)

    phi = math.radians(30.0)
    nq = math.exp(math.pi * math.tan(phi)) * math.tan(math.radians(60.0)) ** 2
    ng = 2.0 * (nq + 1.0) * math.tan(phi)
    sq = 1.0 + math.tan(phi)
    sg = 0.6
    dq = 1.0 + 2.0 * math.tan(phi) * (1.0 - math.sin(phi)) ** 2 * 0.5

    term_q = 18.0 * nq * sq * dq
    term_g = 0.5 * 18.0 * 2.0 * ng * sg * 1.0

    assert r.surcharge_q == pytest.approx(18.0, rel=1e-12)
    assert r.term_cohesion == pytest.approx(0.0, abs=1e-12)
    assert r.term_surcharge == pytest.approx(term_q, rel=1e-10)
    assert r.term_self_weight == pytest.approx(term_g, rel=1e-10)
    assert r.q_ult == pytest.approx(term_q + term_g, rel=1e-10)
    # Independent arithmetic, to 2 decimals.
    assert r.q_ult == pytest.approx(839.84, rel=1e-4)
    assert r.q_net_ult == pytest.approx(839.84 - 18.0, rel=1e-4)
    assert r.q_allow == pytest.approx(r.q_ult / 3.0, rel=1e-12)


def test_undrained_strip_reduces_to_514_su():
    """phi = 0, Df = 0, B/L -> 0 must give q_ult -> 5.14 su (Prandtl)."""
    su = 50.0
    profile = SoilProfile([
        SoilLayer("Clay", 20.0, 18.0, drainage=Drainage.UNDRAINED,
                  phi=0.0, cohesion=su, cc=0.2, e0=0.8),
    ])
    r = ultimate_bearing_capacity(profile, b=1.0, l=2000.0, df=0.0, v=100.0)
    assert r.q_ult == pytest.approx(5.14159 * su, rel=2e-3)
    assert r.factors.ngamma == 0.0
    assert r.term_self_weight == pytest.approx(0.0, abs=1e-12)


def test_undrained_uses_total_stress_surcharge():
    """With phi = 0 the surcharge must be TOTAL, not effective, overburden."""
    layers = [SoilLayer("Clay", 20.0, 18.0, gamma_sat=19.0,
                        drainage=Drainage.UNDRAINED, cohesion=60.0, cc=0.3, e0=0.9)]
    profile = SoilProfile(layers, water_table_depth=0.0)
    r = ultimate_bearing_capacity(profile, b=2.0, l=2.0, df=2.0, v=400.0)
    assert r.surcharge_q == pytest.approx(19.0 * 2.0, rel=1e-12)  # total
    assert r.surcharge_q != pytest.approx(profile.effective_stress(2.0))


# --------------------------------------------------------------------------
# Shape / depth / inclination behaviour
# --------------------------------------------------------------------------


def test_shape_factors_square_vs_strip():
    nq, nc = 18.4011, 30.1396
    sc_sq, sq_sq, sg_sq = shape_factors(2.0, 2.0, 30.0, nq, nc)
    sc_st, sq_st, sg_st = shape_factors(2.0, 200.0, 30.0, nq, nc)
    assert sc_sq > sc_st and sq_sq > sq_st
    assert sg_sq < sg_st           # self-weight term is penalised on a square
    assert sg_st == pytest.approx(1.0, abs=0.01)
    assert sq_st == pytest.approx(1.0, abs=0.01)


def test_depth_factor_switches_to_radians_beyond_df_over_b_of_one():
    """k = Df/B for Df/B <= 1, else arctan(Df/B). Forgetting the switch makes
    deep footings silently unconservative."""
    _, _, _, k_shallow = depth_factors(1.0, 2.0, 30.0)
    assert k_shallow == pytest.approx(0.5)
    _, _, _, k_deep = depth_factors(8.0, 2.0, 30.0)
    assert k_deep == pytest.approx(math.atan(4.0))
    assert k_deep < 4.0            # the whole point of the switch


def test_depth_factors_unity_at_zero_embedment():
    dc, dq, dg, k = depth_factors(0.0, 2.0, 30.0)
    assert (dc, dq, dg, k) == pytest.approx((1.0, 1.0, 1.0, 0.0))


def test_inclination_factors_reduce_capacity():
    ic, iq, ig, m = inclination_factors(1000.0, 200.0, 2.0, 2.0, 30.0, 0.0, 30.14, 18.40)
    assert 0.0 < ic < 1.0 and 0.0 < iq < 1.0 and 0.0 < ig < 1.0
    assert ig < iq, "i_gamma carries the higher exponent and must be smaller"
    assert m == pytest.approx(1.5)  # (2+1)/(1+1) for a square


def test_zero_horizontal_load_gives_unity_inclination():
    assert inclination_factors(1000.0, 0.0, 2.0, 2.0, 30.0, 0.0, 30.14, 18.40)[:3] == (1.0, 1.0, 1.0)


def test_horizontal_load_exceeding_shear_resistance_raises():
    with pytest.raises(ValueError, match="slides before it bears"):
        inclination_factors(100.0, 500.0, 2.0, 2.0, 30.0, 0.0, 30.14, 18.40)


# --------------------------------------------------------------------------
# Eccentricity
# --------------------------------------------------------------------------


def test_eccentricity_reduces_effective_area_and_capacity():
    profile = SoilProfile([SoilLayer("Sand", 20.0, 18.0, phi=32.0, spt_n=25)])
    concentric = ultimate_bearing_capacity(profile, b=2.0, l=2.0, df=1.0, v=500.0)
    eccentric = ultimate_bearing_capacity(profile, b=2.0, l=2.0, df=1.0, v=500.0, m_b=150.0)
    assert eccentric.b_eff < concentric.b_eff
    assert eccentric.q_ult < concentric.q_ult


def test_kern_violation_warns():
    profile = SoilProfile([SoilLayer("Sand", 20.0, 18.0, phi=32.0, spt_n=25)])
    # e_B = M/V = 250/500 = 0.5 m > B/6 = 0.333 m
    r = ultimate_bearing_capacity(profile, b=2.0, l=2.0, df=1.0, v=500.0, m_b=250.0)
    assert any("kern" in w for w in r.warnings)


def test_overturning_eccentricity_raises():
    profile = SoilProfile([SoilLayer("Sand", 20.0, 18.0, phi=32.0, spt_n=25)])
    with pytest.raises(ValueError, match="overturns"):
        ultimate_bearing_capacity(profile, b=2.0, l=2.0, df=1.0, v=500.0, m_b=600.0)


def test_b_effective_is_always_the_shorter_dimension():
    """A large eccentricity on the long side must not leave B' > L'."""
    profile = SoilProfile([SoilLayer("Sand", 20.0, 18.0, phi=32.0, spt_n=25)])
    r = ultimate_bearing_capacity(profile, b=2.0, l=6.0, df=1.0, v=1000.0, m_l=2500.0)
    assert r.b_eff <= r.l_eff


# --------------------------------------------------------------------------
# Groundwater
# --------------------------------------------------------------------------


def test_water_table_at_base_reduces_self_weight_term():
    layers = lambda: [SoilLayer("Sand", 20.0, 18.0, gamma_sat=20.0, phi=32.0, spt_n=25)]
    dry = SoilProfile(layers(), water_table_depth=float("inf"))
    wet = SoilProfile(layers(), water_table_depth=1.0)
    r_dry = ultimate_bearing_capacity(dry, b=2.0, l=2.0, df=1.0, v=500.0)
    r_wet = ultimate_bearing_capacity(wet, b=2.0, l=2.0, df=1.0, v=500.0)
    assert r_wet.gamma_e == pytest.approx(20.0 - 9.81, rel=1e-9)
    assert r_wet.q_ult < r_dry.q_ult
    assert "Case I" in r_wet.gw_note


def test_water_table_below_failure_zone_has_no_effect():
    layers = [SoilLayer("Sand", 40.0, 18.0, gamma_sat=20.0, phi=32.0, spt_n=25)]
    deep = SoilProfile(layers, water_table_depth=30.0)
    r = ultimate_bearing_capacity(deep, b=2.0, l=2.0, df=1.0, v=500.0)
    assert r.gamma_e == pytest.approx(18.0)
    assert "Case III" in r.gw_note


def test_water_table_within_b_interpolates():
    layers = [SoilLayer("Sand", 40.0, 18.0, gamma_sat=20.0, phi=32.0, spt_n=25)]
    p = SoilProfile(layers, water_table_depth=2.0)   # Df=1, B=2 -> dw is 1 m below base
    r = ultimate_bearing_capacity(p, b=2.0, l=2.0, df=1.0, v=500.0)
    gamma_sub = 20.0 - 9.81
    expected = gamma_sub + 0.5 * (18.0 - gamma_sub)
    assert r.gamma_e == pytest.approx(expected, rel=1e-9)
    assert "Case II" in r.gw_note


# --------------------------------------------------------------------------
# Layering
# --------------------------------------------------------------------------


def test_strong_over_weak_is_flagged():
    profile = SoilProfile([
        SoilLayer("Dense sand", 1.5, 20.0, phi=40.0, spt_n=45),
        SoilLayer("Soft clay", 10.0, 16.0, drainage=Drainage.UNDRAINED,
                  cohesion=20.0, cc=0.35, e0=1.0),
    ])
    r = ultimate_bearing_capacity(profile, b=2.0, l=2.0, df=0.5, v=300.0)
    assert any("punching" in w.lower() for w in r.warnings)


def test_shallow_boring_is_flagged():
    profile = SoilProfile([SoilLayer("Sand", 2.0, 18.0, phi=32.0, spt_n=20)])
    r = ultimate_bearing_capacity(profile, b=3.0, l=3.0, df=1.0, v=500.0)
    assert any("boring terminates" in w.lower() for w in r.warnings)


def test_invalid_inputs_rejected():
    profile = SoilProfile([SoilLayer("Sand", 20.0, 18.0, phi=32.0, spt_n=25)])
    with pytest.raises(ValueError):
        ultimate_bearing_capacity(profile, b=0.0, l=2.0, df=1.0, v=500.0)
    with pytest.raises(ValueError):
        ultimate_bearing_capacity(profile, b=2.0, l=2.0, df=1.0, v=0.0)
    with pytest.raises(ValueError):
        ultimate_bearing_capacity(profile, b=2.0, l=2.0, df=1.0, v=500.0, factor_of_safety=1.0)
