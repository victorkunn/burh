"""Settlement validation.

The headline test integrates the Schmertmann summation analytically and
compares it with the code's numerical summation.
"""

import math

import pytest

from burh.settlement import schmertmann_geometry, settlement, strain_influence
from burh.soil import Drainage, SoilLayer, SoilProfile


def _closed_form_schmertmann(gamma, b, df, q, es, years=50.0):
    """Analytic Schmertmann settlement for a SQUARE footing on a uniform
    layer of constant Es.

    The area under the Iz profile, in units of B, is:
        int_0^0.5 [0.1 + (Izp-0.1)(z/0.5)] dz  = 0.025 + 0.25 Izp
      + int_0.5^2 [Izp (2-z)/1.5] dz           = 0.75 Izp
      = 0.025 + Izp
    so S = C1 C2 dq B (0.025 + Izp) / Es.
    """
    sigma0 = gamma * df
    dq = q - sigma0
    izp = 0.5 + 0.1 * math.sqrt(dq / (gamma * (df + 0.5 * b)))
    c1 = max(0.5, 1.0 - 0.5 * sigma0 / dq)
    c2 = 1.0 + 0.2 * math.log10(years / 0.1)
    return c1 * c2 * dq * b * (0.025 + izp) / es


def test_schmertmann_matches_closed_form_integration():
    gamma, b, df, q, es = 18.0, 2.0, 1.0, 250.0, 25000.0
    p = SoilProfile([SoilLayer("Sand", 40.0, gamma, phi=34.0, elastic_modulus=es)])
    r = settlement(p, b=b, l=b, df=df, q_gross=q, time_years=50.0)
    assert r.total == pytest.approx(
        _closed_form_schmertmann(gamma, b, df, q, es), rel=1e-6
    )


@pytest.mark.parametrize("b,df,q,es", [(1.5, 0.5, 180.0, 20000.0),
                                       (3.0, 1.5, 300.0, 40000.0),
                                       (2.5, 2.0, 400.0, 15000.0)])
def test_schmertmann_closed_form_across_geometries(b, df, q, es):
    gamma = 19.0
    p = SoilProfile([SoilLayer("Sand", 60.0, gamma, phi=35.0, elastic_modulus=es)])
    r = settlement(p, b=b, l=b, df=df, q_gross=q)
    assert r.total == pytest.approx(
        _closed_form_schmertmann(gamma, b, df, q, es), rel=1e-6
    )


def test_settlement_is_inversely_proportional_to_modulus():
    def run(es):
        p = SoilProfile([SoilLayer("Sand", 40.0, 18.0, phi=34.0, elastic_modulus=es)])
        return settlement(p, b=2.0, l=2.0, df=1.0, q_gross=250.0).total

    assert run(20000.0) == pytest.approx(2.0 * run(40000.0), rel=1e-9)


def test_correction_factors():
    p = SoilProfile([SoilLayer("Sand", 40.0, 18.0, phi=34.0, elastic_modulus=25000.0)])
    r = settlement(p, b=2.0, l=2.0, df=1.0, q_gross=250.0, time_years=50.0)
    assert r.c2 == pytest.approx(1.0 + 0.2 * math.log10(500.0))
    # C1 must never fall below 0.5 no matter how deep the footing.
    deep = settlement(p, b=2.0, l=2.0, df=10.0, q_gross=400.0)
    assert deep.c1 >= 0.5


def test_creep_can_be_disabled():
    p = SoilProfile([SoilLayer("Sand", 40.0, 18.0, phi=34.0, elastic_modulus=25000.0)])
    with_creep = settlement(p, b=2.0, l=2.0, df=1.0, q_gross=250.0, creep=True)
    without = settlement(p, b=2.0, l=2.0, df=1.0, q_gross=250.0, creep=False)
    assert without.c2 == 1.0
    assert without.total < with_creep.total


def test_fully_compensated_foundation_has_zero_settlement():
    p = SoilProfile([SoilLayer("Sand", 40.0, 18.0, phi=34.0, elastic_modulus=25000.0)])
    r = settlement(p, b=2.0, l=2.0, df=5.0, q_gross=18.0 * 5.0)
    assert r.total == 0.0
    assert any("compensation" in w for w in r.warnings)


# -- Iz geometry ------------------------------------------------------------


def test_schmertmann_geometry_endpoints():
    assert schmertmann_geometry(1.0) == (0.1, 0.5, 2.0)
    assert schmertmann_geometry(10.0) == pytest.approx((0.2, 1.0, 4.0))
    assert schmertmann_geometry(1000.0) == pytest.approx((0.2, 1.0, 4.0))


def test_strain_influence_shape():
    iz0, zp, zmax = schmertmann_geometry(1.0)
    izp = 0.6
    assert strain_influence(0.0, iz0, zp, zmax, izp) == pytest.approx(iz0)
    assert strain_influence(zp, iz0, zp, zmax, izp) == pytest.approx(izp)
    assert strain_influence(zmax, iz0, zp, zmax, izp) == 0.0
    assert strain_influence(zmax + 1.0, iz0, zp, zmax, izp) == 0.0


# -- Consolidation ----------------------------------------------------------


def _clay_profile(ocr=1.0, cc=0.30, cr=0.05):
    return SoilProfile([
        SoilLayer("Crust", 1.0, 18.0, phi=30.0, elastic_modulus=20000.0),
        SoilLayer("Soft clay", 12.0, 17.0, gamma_sat=17.5,
                  drainage=Drainage.UNDRAINED, cohesion=40.0,
                  cc=cc, cr=cr, e0=1.10, ocr=ocr),
    ], water_table_depth=1.0)


def test_overconsolidation_reduces_settlement():
    nc = settlement(_clay_profile(ocr=1.0), b=2.0, l=2.0, df=1.0, q_gross=150.0)
    oc = settlement(_clay_profile(ocr=3.0), b=2.0, l=2.0, df=1.0, q_gross=150.0)
    assert oc.consolidation < nc.consolidation
    assert nc.consolidation > 0.0


def test_consolidation_scales_with_compression_index():
    a = settlement(_clay_profile(cc=0.20), b=2.0, l=2.0, df=1.0, q_gross=150.0)
    b = settlement(_clay_profile(cc=0.40), b=2.0, l=2.0, df=1.0, q_gross=150.0)
    assert b.consolidation == pytest.approx(2.0 * a.consolidation, rel=1e-9)


def test_heavily_overconsolidated_clay_stays_on_the_recompression_line():
    """If sigma_f never exceeds sigma_p, only Cr is mobilised, so the result
    must be independent of Cc."""
    a = settlement(_clay_profile(ocr=50.0, cc=0.20), b=2.0, l=2.0, df=1.0, q_gross=120.0)
    b = settlement(_clay_profile(ocr=50.0, cc=0.90), b=2.0, l=2.0, df=1.0, q_gross=120.0)
    assert a.consolidation == pytest.approx(b.consolidation, rel=1e-12)
    assert a.consolidation > 0.0


def test_missing_consolidation_parameters_warns_loudly():
    p = SoilProfile([
        SoilLayer("Crust", 1.0, 18.0, phi=30.0, elastic_modulus=20000.0),
        SoilLayer("Soft clay", 12.0, 17.0, drainage=Drainage.UNDRAINED,
                  cohesion=40.0),   # no cc / e0
    ], water_table_depth=1.0)
    r = settlement(p, b=2.0, l=2.0, df=1.0, q_gross=150.0)
    assert r.consolidation == 0.0
    assert any("unconservative" in w for w in r.warnings)


def test_shallow_boring_warns():
    p = SoilProfile([SoilLayer("Sand", 3.0, 18.0, phi=34.0, elastic_modulus=25000.0)])
    r = settlement(p, b=3.0, l=3.0, df=1.0, q_gross=250.0)
    assert any("boring ends" in w for w in r.warnings)


def test_missing_modulus_and_spt_is_an_error_not_a_guess():
    p = SoilProfile([SoilLayer("Sand", 40.0, 18.0, phi=34.0)])
    with pytest.raises(ValueError, match="elastic_modulus or spt_n"):
        settlement(p, b=2.0, l=2.0, df=1.0, q_gross=250.0)


def test_invalid_inputs_rejected():
    p = SoilProfile([SoilLayer("Sand", 40.0, 18.0, phi=34.0, elastic_modulus=25000.0)])
    with pytest.raises(ValueError):
        settlement(p, b=0.0, l=2.0, df=1.0, q_gross=250.0)
    with pytest.raises(ValueError):
        settlement(p, b=2.0, l=2.0, df=1.0, q_gross=250.0, time_years=0.0)
