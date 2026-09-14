"""Design code framework validation.

The error this file exists to prevent: comparing a factored load against an
allowable capacity, or a service load against a factored resistance. Either
way it is roughly a 40% error, in whichever direction is worse.
"""

import pytest

from burh.api import Project
from burh.codes import CANADA_LSD, CODES, US_ASD, Approach, LoadCombination, get_code
from burh.design import ColumnLoad, DesignCriteria, design_footing
from burh.soil import SoilLayer, SoilProfile


def sand():
    return SoilProfile([
        SoilLayer("Medium dense sand", 30.0, 19.0, gamma_sat=20.5,
                  phi=33.0, spt_n=22),
    ], water_table_depth=15.0)


def criteria(code, **kw):
    base = dict(min_width=0.6, max_width=9.0, size_increment=0.05,
                settlement_limit=0.025, code=code)
    if code.factor_of_safety is not None:
        base["factor_of_safety_bearing"] = code.factor_of_safety
    base.update(kw)
    return DesignCriteria(**base)


# -- registry ---------------------------------------------------------------


def test_both_codes_registered():
    assert set(CODES) == {"us_asd", "canada_lsd"}
    assert get_code("us_asd") is US_ASD
    assert get_code("canada_lsd") is CANADA_LSD


def test_unknown_code_rejected():
    with pytest.raises(ValueError, match="Unknown design code"):
        get_code("eurocode")


def test_frameworks_declare_the_right_factors():
    assert US_ASD.approach is Approach.ASD
    assert US_ASD.factor_of_safety == 3.0
    assert US_ASD.resistance_factor is None
    assert US_ASD.combinations == ()          # ASD checks at service load

    assert CANADA_LSD.approach is Approach.LSD
    assert CANADA_LSD.resistance_factor == 0.5
    assert CANADA_LSD.factor_of_safety is None
    assert len(CANADA_LSD.combinations) == 2


def test_every_code_carries_its_citation_and_caveats():
    for code in CODES.values():
        assert code.citation
        assert code.notes, f"{code.key} has no caveats"


# -- load combinations ------------------------------------------------------


def test_nbcc_combination_crossover():
    """1.4D governs below L/D = 0.1, 1.25D + 1.5L above.
    1.4D = 1.25D + 1.5L  =>  0.15D = 1.5L  =>  L = 0.1D"""
    c = CANADA_LSD
    assert c.governing_combination(100.0, 5.0)[0].name == "1.4D"
    assert c.governing_combination(100.0, 20.0)[0].name == "1.25D + 1.5L"
    at_crossover = c.governing_combination(100.0, 10.0)[1]
    assert at_crossover == pytest.approx(140.0)


def test_governing_combination_returns_the_larger_value():
    for d, l in ((100, 0), (100, 50), (0.1, 900), (500, 500)):
        combo, value = CANADA_LSD.governing_combination(d, l)
        assert value == pytest.approx(combo.factored(d, l))
        assert value == max(c.factored(d, l) for c in CANADA_LSD.combinations)


def test_asd_has_no_combinations_and_says_so():
    with pytest.raises(ValueError, match="no ULS load combinations"):
        US_ASD.governing_combination(100.0, 50.0)


def test_load_combination_arithmetic():
    assert LoadCombination("t", dead=1.25, live=1.5).factored(100.0, 50.0) == 200.0


# -- the check itself -------------------------------------------------------


def test_asd_compares_service_load_against_q_ult_over_fs():
    d = design_footing(sand(), ColumnLoad("F", dead=600.0, live=300.0),
                       criteria(US_ASD))
    u = d.uls
    assert u.approach is Approach.ASD
    assert u.combination == "service (D + L)"
    assert u.demand == pytest.approx(d.q_service_gross)     # unfactored
    assert u.load_factor_ratio == pytest.approx(1.0)
    assert u.capacity == pytest.approx(u.q_ult / 3.0)
    assert u.equivalent_global_fs == pytest.approx(3.0)


def test_lsd_compares_factored_load_against_phi_q_ult():
    d = design_footing(sand(), ColumnLoad("F", dead=600.0, live=300.0),
                       criteria(CANADA_LSD))
    u = d.uls
    assert u.approach is Approach.LSD
    assert u.combination == "1.25D + 1.5L"
    assert u.capacity == pytest.approx(0.5 * u.q_ult)
    assert u.demand > u.q_service, "LSD demand must exceed the service pressure"
    assert 1.25 <= u.load_factor_ratio <= 1.5


def test_footing_self_weight_takes_the_same_dead_factor_as_the_combination():
    """The footing and its backfill are dead load. Factoring the column load
    but not the self-weight understates the demand."""
    load = ColumnLoad("F", dead=600.0, live=300.0)
    d = design_footing(sand(), load, criteria(CANADA_LSD))
    u = d.uls
    area = d.b * d.l
    v_factored = 1.25 * load.dead + 1.5 * load.live
    self_weight_service = d.q_service_gross - load.service_vertical / area
    expected = v_factored / area + 1.25 * self_weight_service
    assert u.demand == pytest.approx(expected, rel=1e-9)


def test_settlement_uses_service_load_under_both_frameworks():
    """Serviceability is a service-load question in every code. If LSD ever
    starts feeding factored pressure into the settlement calculation, every
    Canadian footing is oversized by ~30%."""
    load = ColumnLoad("F", dead=600.0, live=300.0)
    asd = design_footing(sand(), load, criteria(US_ASD, max_width=2.0))
    lsd = design_footing(sand(), load, criteria(CANADA_LSD, max_width=2.0))
    assert asd.q_service_gross == pytest.approx(lsd.q_service_gross)
    assert asd.total_settlement == pytest.approx(lsd.total_settlement, rel=1e-12)


def test_equivalent_global_fs_is_lambda_over_phi():
    d = design_footing(sand(), ColumnLoad("F", dead=600.0, live=300.0),
                       criteria(CANADA_LSD))
    u = d.uls
    assert u.equivalent_global_fs == pytest.approx(u.load_factor_ratio / 0.5, rel=1e-9)
    # Canadian LSD is less conservative than customary US practice on bearing.
    assert 2.3 < u.equivalent_global_fs < 3.0


def test_resistance_factor_can_be_overridden():
    load = ColumnLoad("F", dead=600.0, live=300.0)
    default = design_footing(sand(), load, criteria(CANADA_LSD))
    strict = design_footing(sand(), load,
                            criteria(CANADA_LSD, resistance_factor_bearing=0.4))
    assert strict.uls.capacity < default.uls.capacity
    assert strict.b >= default.b


def test_invalid_resistance_factor_rejected():
    for bad in (0.0, -0.5, 1.5):
        with pytest.raises(ValueError, match="resistance factor"):
            criteria(CANADA_LSD, resistance_factor_bearing=bad).phi_bearing


def test_lower_phi_is_more_conservative_than_higher():
    load = ColumnLoad("F", dead=900.0, live=100.0)
    sizes = []
    for phi in (0.35, 0.5, 0.7):
        d = design_footing(sand(), load,
                           criteria(CANADA_LSD, resistance_factor_bearing=phi,
                                    settlement_limit=1e9))
        sizes.append(d.b)
    assert sizes[0] >= sizes[1] >= sizes[2]


# -- through the public API -------------------------------------------------


def test_project_accepts_a_code_and_applies_its_defaults():
    p = Project("Canadian job", units="SI", code="canada_lsd")
    assert p.code is CANADA_LSD
    assert p.criteria.code is CANADA_LSD
    assert p.criteria.phi_bearing == 0.5


def test_switching_code_mid_project():
    p = Project("job", units="SI", code="us_asd")
    assert p.criteria.code.approach is Approach.ASD
    p.set_criteria(code="canada_lsd")
    assert p.criteria.code.approach is Approach.LSD


def test_same_soil_same_settlement_different_uls_across_codes():
    def run(code):
        p = Project("cmp", units="SI", code=code)
        p.add_layer("Sand", thickness=30, gamma=19.0, gamma_sat=20.5, phi=33, spt_n=22)
        p.set_water_table(15)
        p.set_criteria(settlement_limit=25.0, min_width=0.6, max_width=9.0,
                       size_increment=0.05)
        p.add_column("F-1", dead=600, live=300)
        return p.run()[0]

    us, ca = run("us_asd"), run("canada_lsd")
    assert us.design.ok and ca.design.ok
    assert us.design.uls.combination == "service (D + L)"
    assert ca.design.uls.combination == "1.25D + 1.5L"
    # Same service settlement, different ULS bookkeeping.
    assert us.settlement == pytest.approx(ca.settlement, rel=1e-9)
    assert ca.design.uls.demand > us.design.uls.demand


def test_us_project_in_us_units_defaults_correctly():
    p = Project("job", units="US")
    assert p.code is US_ASD
    assert p.criteria.factor_of_safety_bearing == 3.0
