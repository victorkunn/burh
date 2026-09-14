"""Soil profile, effective stress and SPT correction validation."""

import math

import pytest

from burh.soil import (
    ALPHA_E,
    Drainage,
    PhiCorrelation,
    SoilLayer,
    SoilProfile,
    es_from_spt,
    n1_60,
    n60,
    overburden_factor,
    phi_from_spt,
    rod_length_factor,
)
from burh.units import GAMMA_WATER_KNM3, P_ATM_KPA


def test_effective_stress_dry_profile():
    p = SoilProfile([SoilLayer("A", 5.0, 18.0, phi=32.0)])
    assert p.effective_stress(3.0) == pytest.approx(54.0)
    assert p.stress_at(3.0).pore_pressure == 0.0


def test_effective_stress_with_water_table_at_a_layer_boundary():
    p = SoilProfile(
        [SoilLayer("A", 2.0, 18.0, gamma_sat=20.0, phi=32.0),
         SoilLayer("B", 5.0, 19.0, gamma_sat=20.0, phi=34.0)],
        water_table_depth=2.0,
    )
    s = p.stress_at(5.0)
    assert s.total == pytest.approx(2 * 18.0 + 3 * 20.0)
    assert s.pore_pressure == pytest.approx(3 * GAMMA_WATER_KNM3)
    assert s.effective == pytest.approx(96.0 - 3 * GAMMA_WATER_KNM3)


def test_water_table_inside_a_layer_switches_unit_weight_mid_layer():
    p = SoilProfile([SoilLayer("A", 5.0, 18.0, gamma_sat=20.0, phi=32.0)],
                    water_table_depth=3.0)
    s = p.stress_at(5.0)
    assert s.total == pytest.approx(3 * 18.0 + 2 * 20.0)
    assert s.effective == pytest.approx(94.0 - 2 * GAMMA_WATER_KNM3)


def test_effective_stress_is_monotonic_and_starts_at_zero():
    p = SoilProfile([SoilLayer("A", 10.0, 18.0, gamma_sat=20.0, phi=32.0)],
                    water_table_depth=2.0)
    assert p.effective_stress(0.0) == 0.0
    vals = [p.effective_stress(z) for z in (0, 1, 2, 3, 5, 8, 10)]
    assert all(a < b for a, b in zip(vals, vals[1:]))


def test_profile_extrapolates_below_the_boring():
    p = SoilProfile([SoilLayer("A", 3.0, 18.0, phi=32.0)])
    assert not p.extends_below(5.0)
    # Must not raise; the bottom layer continues.
    assert p.effective_stress(5.0) == pytest.approx(90.0)
    assert p.layer_at(99.0).name == "A"


def test_layer_validation():
    with pytest.raises(ValueError, match="thickness"):
        SoilLayer("bad", 0.0, 18.0)
    with pytest.raises(ValueError, match="gamma"):
        SoilLayer("bad", 1.0, -1.0)
    with pytest.raises(ValueError, match="cannot be\\s+less"):
        SoilLayer("bad", 1.0, 20.0, gamma_sat=18.0)
    with pytest.raises(ValueError, match="unit weight of water"):
        SoilLayer("bad", 1.0, 9.0, gamma_sat=9.5)
    with pytest.raises(ValueError, match="phi"):
        SoilLayer("bad", 1.0, 18.0, phi=70.0)
    with pytest.raises(ValueError, match="OCR"):
        SoilLayer("bad", 1.0, 18.0, phi=30.0, ocr=0.5)


def test_undrained_layer_must_have_zero_phi_and_positive_su():
    with pytest.raises(ValueError, match="requires phi = 0"):
        SoilLayer("clay", 1.0, 18.0, drainage=Drainage.UNDRAINED, phi=25.0, cohesion=50.0)
    with pytest.raises(ValueError, match="requires su > 0"):
        SoilLayer("clay", 1.0, 18.0, drainage=Drainage.UNDRAINED, cohesion=0.0)


def test_buoyant_unit_weight():
    layer = SoilLayer("A", 1.0, 18.0, gamma_sat=20.0, phi=30.0)
    assert layer.gamma_buoyant == pytest.approx(20.0 - GAMMA_WATER_KNM3)


def test_negative_water_table_rejected():
    with pytest.raises(ValueError):
        SoilProfile([SoilLayer("A", 1.0, 18.0, phi=30.0)], water_table_depth=-1.0)


def test_empty_profile_rejected():
    with pytest.raises(ValueError):
        SoilProfile([])


# -- SPT --------------------------------------------------------------------


def test_n60_energy_correction():
    # A 70% efficient hammer reads high; N60 scales it up by 70/60.
    assert n60(20.0, energy_ratio=70.0) == pytest.approx(20.0 * 70.0 / 60.0)
    assert n60(20.0, energy_ratio=60.0) == pytest.approx(20.0)


def test_rod_length_factors_are_the_published_steps():
    assert rod_length_factor(2.0) == 0.75
    assert rod_length_factor(3.5) == 0.80
    assert rod_length_factor(5.0) == 0.85
    assert rod_length_factor(8.0) == 0.95
    assert rod_length_factor(15.0) == 1.00


def test_overburden_factor_is_capped_near_the_surface():
    assert overburden_factor(0.0) == 1.7
    assert overburden_factor(1e-6) == 1.7
    # C_N = 1 exactly at one atmosphere of effective overburden.
    assert overburden_factor(P_ATM_KPA) == pytest.approx(1.0)
    assert overburden_factor(400.0) < 1.0


def test_n1_60_combines_both_corrections():
    assert n1_60(20.0, P_ATM_KPA, energy_ratio=60.0) == pytest.approx(20.0)


def test_phi_correlations_are_ordered_and_bounded():
    for method in PhiCorrelation:
        low, _ = phi_from_spt(4.0, 100.0, method=method)
        high, _ = phi_from_spt(45.0, 100.0, method=method)
        assert low < high, f"{method} not monotonic in N"
        assert 25.0 <= low <= 45.0 and 25.0 <= high <= 45.0


def test_phi_correlation_returns_its_citation():
    _, cite = phi_from_spt(20.0, 100.0, method=PhiCorrelation.KULHAWY_MAYNE)
    assert "Kulhawy" in cite


def test_es_from_spt_matches_kulhawy_mayne_brackets():
    for key, alpha in ALPHA_E.items():
        assert es_from_spt(20.0, 60.0, key) == pytest.approx(alpha * 20.0 * P_ATM_KPA)
    assert es_from_spt(20.0, 60.0, "clean_sand_nc") > es_from_spt(20.0, 60.0, "sand_with_fines")


def test_unknown_soil_class_rejected():
    with pytest.raises(ValueError, match="soil_class"):
        es_from_spt(20.0, 60.0, "mud")
    with pytest.raises(ValueError, match="soil_class"):
        SoilLayer("bad", 1.0, 18.0, phi=30.0, soil_class="mud")


def test_negative_spt_rejected():
    with pytest.raises(ValueError):
        n60(-1.0)
