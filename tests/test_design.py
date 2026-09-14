"""Sizing solver validation, including the behaviour the product is sold on:
correctly identifying WHICH limit state governs."""

import pytest

from burh.api import Project
from burh.design import ColumnLoad, DesignCriteria, design_footing, estimate_thickness, gross_pressure
from burh.soil import Drainage, SoilLayer, SoilProfile


def sand_profile(n=20, es=None):
    return SoilProfile([
        SoilLayer("Medium dense sand", 30.0, 18.9, gamma_sat=20.1,
                  phi=33.0, spt_n=n, elastic_modulus=es),
    ], water_table_depth=15.0)


def soft_clay_profile():
    return SoilProfile([
        SoilLayer("Fill", 1.0, 18.0, phi=28.0, spt_n=8),
        SoilLayer("Soft clay", 20.0, 16.5, gamma_sat=17.0,
                  drainage=Drainage.UNDRAINED, cohesion=25.0,
                  cc=0.35, cr=0.06, e0=1.2, ocr=1.0, elastic_modulus=6000.0),
    ], water_table_depth=1.0)


# -- which limit state governs ---------------------------------------------


def test_settlement_governs_on_sand():
    """The core selling point: on granular soil the bearing check passes with
    a wide margin while settlement is what actually sizes the footing."""
    d = design_footing(sand_profile(), ColumnLoad("C-1", dead=670.0, live=330.0))
    assert d.ok
    assert d.governing == "Settlement"
    assert d.bearing_utilisation < 0.85, "bearing should not be close to governing"
    assert d.settlement_utilisation == pytest.approx(1.0, abs=0.12)


def test_bearing_governs_on_soft_clay():
    d = design_footing(soft_clay_profile(), ColumnLoad("C-2", dead=180.0, live=90.0))
    if d.ok:
        assert d.governing == "Bearing capacity"
        assert d.bearing_utilisation >= d.settlement_utilisation
    else:
        assert d.governing == "NO SOLUTION"


def test_governing_criterion_is_the_higher_utilisation():
    d = design_footing(sand_profile(), ColumnLoad("C-3", dead=400.0, live=200.0))
    assert d.ok
    expected = ("Bearing capacity" if d.bearing_utilisation >= d.settlement_utilisation
                else "Settlement")
    assert d.governing == expected


# -- solver mechanics -------------------------------------------------------


def test_result_lands_on_the_size_increment_grid():
    c = DesignCriteria(min_width=0.6, max_width=6.0, size_increment=0.05)
    d = design_footing(sand_profile(), ColumnLoad("C-1", dead=500.0, live=250.0), c)
    assert d.ok
    steps = (d.b - c.min_width) / c.size_increment
    assert steps == pytest.approx(round(steps), abs=1e-9)


def test_solver_returns_the_smallest_passing_size():
    c = DesignCriteria(min_width=0.6, max_width=6.0, size_increment=0.05)
    load = ColumnLoad("C-1", dead=500.0, live=250.0)
    d = design_footing(sand_profile(), load, c)
    assert d.ok
    smaller = DesignCriteria(min_width=0.6, max_width=d.b - c.size_increment,
                             size_increment=c.size_increment)
    assert not design_footing(sand_profile(), load, smaller).ok


def test_heavier_load_needs_a_bigger_footing():
    light = design_footing(sand_profile(), ColumnLoad("L", dead=200.0))
    heavy = design_footing(sand_profile(), ColumnLoad("H", dead=800.0))
    assert light.ok and heavy.ok
    assert heavy.b > light.b


def test_aspect_ratio_is_honoured():
    c = DesignCriteria(aspect_ratio=2.0)
    d = design_footing(sand_profile(), ColumnLoad("C-1", dead=500.0), c)
    assert d.ok
    assert d.l == pytest.approx(2.0 * d.b)


def test_unsolvable_case_returns_a_diagnosis_instead_of_raising():
    tiny = DesignCriteria(min_width=0.6, max_width=1.0, size_increment=0.05)
    d = design_footing(soft_clay_profile(), ColumnLoad("C-X", dead=5000.0), tiny)
    assert not d.ok
    assert d.governing == "NO SOLUTION"
    assert d.b == 0.0
    # The diagnosis must name the governing quantity and an actionable step.
    assert "Settlement governs" in d.message or "Bearing capacity governs" in d.message
    assert "max_width" in d.message or "deep foundations" in d.message


def test_artificially_truncated_search_says_to_raise_max_width():
    """When the search is cut short while settlement is still falling fast,
    the advice must be 'search wider', not 'go to deep foundations'."""
    tiny = DesignCriteria(min_width=0.6, max_width=1.2, size_increment=0.05)
    d = design_footing(sand_profile(), ColumnLoad("C-X", dead=900.0), tiny)
    assert not d.ok
    # The probe must state a fact, not extrapolate: a working size exists.
    assert "a footing DOES work at" in d.message
    assert "Raise max_width" in d.message
    assert "Widening cannot solve this" not in d.message


def test_reported_minimum_settlement_is_the_global_minimum():
    """The probe searches beyond max_width, but settlement is not monotonic in
    width on a layered profile. The quoted 'least settlement' must fold in the
    sizes already tried, or it can quote a worse number than one the solver
    already saw."""
    import re

    from burh.bearing import averaged_properties
    from burh.design import estimate_thickness, gross_pressure
    from burh.settlement import settlement as settle

    profile = SoilProfile([
        SoilLayer("Crust", 1.5, 18.0, phi=30.0, spt_n=12, elastic_modulus=20000.0),
        SoilLayer("Deep soft clay", 40.0, 16.0, gamma_sat=16.8,
                  drainage=Drainage.UNDRAINED, cohesion=45.0,
                  cc=0.45, cr=0.07, e0=1.30, ocr=1.0, elastic_modulus=7000.0),
    ], water_table_depth=1.5)
    c = DesignCriteria(min_width=0.6, max_width=8.0, size_increment=0.1,
                       settlement_limit=0.025)
    load = ColumnLoad("C-A", dead=900.0, live=400.0)
    d = design_footing(profile, load, c)

    match = re.search(r"least settlement at ANY width tried is ([\d.]+) mm", d.message)
    assert match, f"probe minimum not reported: {d.message}"
    quoted = float(match.group(1)) / 1000.0

    gamma = averaged_properties(profile, c.min_embedment, c.min_width,
                                c.influence_depth_ratio).gamma_moist
    steps = int((c.max_width - c.min_width) / c.size_increment) + 1
    for i in range(steps):
        b = c.min_width + i * c.size_increment
        t_ = estimate_thickness(b, load.column_b)
        q = gross_pressure(load.service_vertical, b, b, c.min_embedment, t_, gamma)
        s = settle(profile, b=b, l=b, df=c.min_embedment, q_gross=q,
                   time_years=c.time_years).total
        assert s >= quoted - 1e-9, (
            f"B={b:.2f} m settles {s * 1000:.1f} mm, better than the quoted "
            f"minimum {quoted * 1000:.1f} mm"
        )


def test_asymptotic_settlement_says_widening_will_not_help():
    """A deep normally-consolidated clay makes settlement asymptotic in width:
    a wider footing pushes its bulb deeper and gains almost nothing. The tool
    must say so rather than advising a bigger footing."""
    profile = SoilProfile([
        SoilLayer("Crust", 1.5, 18.0, phi=30.0, spt_n=12, elastic_modulus=20000.0),
        SoilLayer("Deep soft clay", 40.0, 16.0, gamma_sat=16.8,
                  drainage=Drainage.UNDRAINED, cohesion=45.0,
                  cc=0.45, cr=0.07, e0=1.30, ocr=1.0, elastic_modulus=7000.0),
    ], water_table_depth=1.5)
    c = DesignCriteria(min_width=0.6, max_width=8.0, size_increment=0.1,
                       settlement_limit=0.025)
    d = design_footing(profile, ColumnLoad("C-A", dead=900.0, live=400.0), c)
    assert not d.ok
    assert "Widening cannot solve this" in d.message
    assert "Deep soft clay" in d.message
    assert "ground improvement" in d.message or "deep foundations" in d.message
    assert "a footing DOES work at" not in d.message


def test_diagnosis_is_written_in_the_engineers_units():
    p = Project("US diag", units="US")
    p.add_layer("Soft", thickness=60, gamma=100, phi=26, spt_n=3)
    p.set_criteria(max_width=6.0)
    p.add_column("BIG", dead=3000)
    msg = p.run()[0].design.message
    assert "ft" in msg and " m." not in msg and "kPa" not in msg


def test_embedment_below_the_minimum_is_rejected():
    c = DesignCriteria(min_embedment=1.0)
    with pytest.raises(ValueError, match="less than the required minimum"):
        design_footing(sand_profile(), ColumnLoad("C-1", dead=300.0, embedment=0.5), c)


def test_stricter_settlement_limit_forces_a_bigger_footing():
    load = ColumnLoad("C-1", dead=600.0, live=300.0)
    loose = design_footing(sand_profile(), load, DesignCriteria(settlement_limit=0.050))
    tight = design_footing(sand_profile(), load, DesignCriteria(settlement_limit=0.012))
    assert loose.ok and tight.ok
    assert tight.b > loose.b


def test_higher_factor_of_safety_never_shrinks_the_footing():
    load = ColumnLoad("C-1", dead=600.0, live=300.0)
    a = design_footing(sand_profile(), load, DesignCriteria(factor_of_safety_bearing=2.5))
    b = design_footing(sand_profile(), load, DesignCriteria(factor_of_safety_bearing=4.0))
    assert b.b >= a.b


# -- load model -------------------------------------------------------------


def test_column_load_validation():
    with pytest.raises(ValueError):
        ColumnLoad("bad", dead=-1.0)
    with pytest.raises(ValueError):
        ColumnLoad("bad", dead=0.0, live=0.0)


def test_service_vertical_is_dead_plus_live_unfactored():
    """Bearing and settlement are both ASD checks. If this ever picks up a
    load factor, every footing on every job is oversized by ~1.5x."""
    assert ColumnLoad("C", dead=100.0, live=50.0).service_vertical == 150.0


def test_gross_pressure_includes_concrete_and_backfill():
    q = gross_pressure(v_service=1000.0, b=2.0, l=2.0, df=1.5,
                       thickness=0.5, gamma_soil=18.0)
    expected = 1000.0 / 4.0 + 0.5 * 23.6 + 1.0 * 18.0
    assert q == pytest.approx(expected)


def test_thickness_estimate_is_never_below_the_floor():
    assert estimate_thickness(0.6, 0.4) >= 0.30
    assert estimate_thickness(6.0, 0.4) > 0.30


# -- end to end through the unit-aware API ---------------------------------


def test_us_units_end_to_end_gives_sane_engineering_numbers():
    p = Project("Warehouse", units="US")
    p.add_layer("Medium dense sand", thickness=30, gamma=120, gamma_sat=128,
                phi=33, spt_n=20)
    p.set_water_table(50)
    p.add_column("C-1", dead=150, live=75)
    r = p.run()[0]
    assert r.design.ok
    # A 225 kip service load on medium dense sand: 7-9 ft square, q ~ 3-5 ksf,
    # settlement at or just under the 1 in limit.
    assert 6.0 < r.b < 10.0
    assert 2.5 < r.q_applied < 5.5
    assert r.settlement <= 1.0 + 1e-9
    assert r.q_allow > r.q_applied


def test_identical_problem_in_si_and_us_agrees():
    us = Project("us", units="US")
    us.add_layer("Sand", thickness=100, gamma=120, phi=33, elastic_modulus=500)
    us.add_column("C-1", dead=200)
    ru = us.run()[0]

    si = Project("si", units="SI")
    si.add_layer("Sand", thickness=100 * 0.3048, gamma=120 * 0.1570874785,
                 phi=33, elastic_modulus=500 * 47.88025898)
    si.set_criteria(settlement_limit=25.4, min_width=2 * 0.3048,
                    max_width=20 * 0.3048, size_increment=0.25 * 0.3048,
                    min_embedment=1.5 * 0.3048)
    si.add_column("C-1", dead=200 * 4.4482216152605)
    rs = si.run()[0]

    assert ru.design.ok and rs.design.ok
    assert rs.design.b == pytest.approx(ru.design.b, rel=1e-9)
    assert rs.design.total_settlement == pytest.approx(ru.design.total_settlement, rel=1e-6)
    assert rs.design.governing == ru.design.governing


def test_one_bad_column_does_not_kill_the_batch():
    p = Project("Mixed", units="US")
    p.add_layer("Sand", thickness=30, gamma=120, phi=33, spt_n=20)
    p.add_column("C-1", dead=100)
    p.add_column("C-HUGE", dead=100000)     # impossible on a spread footing
    p.add_column("C-3", dead=150)
    results = p.run()
    assert len(results) == 3
    assert results[0].design.ok and results[2].design.ok
    assert not results[1].design.ok


def test_phi_inference_records_its_provenance():
    p = Project("Inferred", units="US")
    p.add_layer("Sand", thickness=30, gamma=120, spt_n=18)   # no phi given
    notes = p.infer_phi_from_spt()
    assert len(notes) == 1
    assert "ESTIMATED" in notes[0] and "Kulhawy" in notes[0]
    assert p.profile.layers[0].phi > 0


def test_project_requires_layers_and_loads():
    p = Project("Empty", units="US")
    with pytest.raises(ValueError, match="No soil layers"):
        p.run()
    p.add_layer("Sand", thickness=10, gamma=120, phi=32, spt_n=20)
    with pytest.raises(ValueError, match="No column loads"):
        p.run()
