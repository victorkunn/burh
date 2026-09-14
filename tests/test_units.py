"""Unit conversion validation. Unit errors are the classic way foundation
software produces confidently wrong answers, so these are exhaustive."""

import pytest

from burh.units import (
    FT_TO_M,
    GAMMA_WATER_KNM3,
    KIP_TO_KN,
    KSF_TO_KPA,
    P_ATM_KPA,
    PCF_TO_KNM3,
    UnitSystem,
    Units,
)


def test_exact_conversion_constants():
    assert FT_TO_M == 0.3048                     # exact by definition
    assert KIP_TO_KN == pytest.approx(4.4482216152605, rel=1e-15)
    assert KSF_TO_KPA == pytest.approx(47.88025898, rel=1e-8)


def test_pcf_constant_via_an_independent_mass_derivation():
    """Derive lb/ft3 -> kN/m3 through MASS (pound -> kg, then x g) rather
    than through the force path the implementation uses. Agreement then means
    the constant is right, not merely self-consistent."""
    pound_kg = 0.45359237        # exact, international pound
    cubic_foot = 0.3048**3       # exact
    g = 9.80665                  # standard gravity, exact by definition
    assert PCF_TO_KNM3 == pytest.approx(pound_kg / cubic_foot * g / 1000.0, rel=1e-15)


def test_water_unit_weight():
    """The engine uses the standard SI value 9.81 kN/m3. US practice quotes
    62.4 pcf, which is 9.8023 kN/m3 - a 0.05% difference, far below the
    uncertainty in any soil parameter. 9.81 is used consistently so the two
    unit systems never disagree with each other."""
    u = Units("US")
    assert GAMMA_WATER_KNM3 == 9.81
    assert u.from_si_unit_weight(GAMMA_WATER_KNM3) == pytest.approx(62.449, abs=0.001)
    assert abs(62.449 - 62.4) / 62.4 < 0.001   # < 0.1%


def test_atmospheric_pressure_in_ksf():
    u = Units("US")
    assert u.from_si_stress(P_ATM_KPA) == pytest.approx(2.116, abs=0.001)


@pytest.mark.parametrize("system", ["SI", "US"])
@pytest.mark.parametrize("value", [0.0, 1.0, 37.5, 1234.5])
def test_round_trip_is_lossless(system, value):
    u = Units(system)
    for to, back in (
        (u.to_si_length, u.from_si_length),
        (u.to_si_force, u.from_si_force),
        (u.to_si_stress, u.from_si_stress),
        (u.to_si_unit_weight, u.from_si_unit_weight),
        (u.to_si_moment, u.from_si_moment),
        (u.to_si_settlement, u.from_si_settlement),
    ):
        assert back(to(value)) == pytest.approx(value, rel=1e-12, abs=1e-12)


def test_si_system_is_the_identity():
    u = Units("SI")
    for f in (u.to_si_length, u.to_si_force, u.to_si_stress,
              u.to_si_unit_weight, u.to_si_moment):
        assert f(42.0) == 42.0


def test_known_us_conversions():
    u = Units("US")
    assert u.to_si_length(10.0) == pytest.approx(3.048)
    assert u.to_si_force(1.0) == pytest.approx(4.4482216152605)
    assert u.to_si_stress(2.0) == pytest.approx(95.7605, rel=1e-5)
    assert u.to_si_unit_weight(120.0) == pytest.approx(18.85, abs=0.01)
    # 1 kip-ft = 1.3558 kN-m
    assert u.to_si_moment(1.0) == pytest.approx(1.35582, rel=1e-5)


def test_settlement_reports_in_mm_or_inches_not_base_length():
    assert Units("SI").from_si_settlement(0.025) == pytest.approx(25.0)
    assert Units("US").from_si_settlement(0.0254) == pytest.approx(1.0)


def test_moment_factor_is_force_times_length():
    for system in ("SI", "US"):
        u = Units(system)
        assert u.to_si_moment(1.0) == pytest.approx(u.to_si_force(1.0) * u.to_si_length(1.0))


def test_labels_are_distinct_per_system():
    assert Units("US").label("stress") == "ksf"
    assert Units("SI").label("stress") == "kPa"
    assert Units("US").label("small_length") == "in"
    assert Units("SI").label("small_length") == "mm"


def test_system_accepts_enum_or_case_insensitive_string():
    assert Units(UnitSystem.US).system is UnitSystem.US
    assert Units("us").system is UnitSystem.US
    assert Units("si").system is UnitSystem.SI


def test_unknown_system_rejected():
    with pytest.raises(ValueError, match="Unknown unit system"):
        Units("imperial")
