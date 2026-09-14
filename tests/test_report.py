"""Calculation package output validation."""

import re

import pytest

from burh.api import Project
from burh.report import calc_package_html, calc_sheet_text


@pytest.fixture
def project():
    p = Project("Reporting job", units="US")
    p.add_layer("Sandy fill", thickness=5, gamma=115, phi=30, spt_n=14)
    p.add_layer("Dense sand", thickness=35, gamma=128, gamma_sat=134, phi=38, spt_n=40)
    p.set_water_table(16)
    p.add_column("F-1", dead=120, live=60)
    p.add_column("F-2", dead=200, live=100, horizontal=15, moment_b=40)
    return p


def test_text_sheet_shows_every_factor(project):
    r = project.run()[0]
    text = calc_sheet_text(r, project)
    for token in ("FOOTING F-1", "BEARING CAPACITY", "SETTLEMENT",
                  "cohesion", "surcharge", "self wt", "q_ult",
                  "q_allow", "UTILISATION", "C1", "C2", "Izp", "GOVERNED BY"):
        assert token in text, f"missing {token!r}"


def test_text_sheet_reports_in_user_units(project):
    text = calc_sheet_text(project.run()[0], project)
    assert "ksf" in text and "ft" in text and "(in)" in text
    assert "kPa" not in text and "kN/m3" not in text


def test_text_sheet_handles_a_failed_footing():
    p = Project("Fail", units="US")
    p.add_layer("Soft", thickness=40, gamma=100, phi=26, spt_n=3)
    p.set_criteria(max_width=3.0)
    p.add_column("BIG", dead=4000)
    r = p.run()[0]
    assert not r.design.ok
    text = calc_sheet_text(r, p)
    assert "NO VALID DESIGN" in text


def test_html_package_is_well_formed(project):
    html = calc_package_html(project.run(), project)
    assert html.startswith("<!doctype html>")
    assert html.rstrip().endswith("</html>")
    for tag in ("html", "head", "body", "style", "title"):
        assert html.count(f"<{tag}") == 1, f"{tag} not unique"
        assert html.count(f"</{tag}>") == 1
    # Balanced structural tags.
    for tag in ("section", "table", "tbody", "thead", "dl"):
        assert html.count(f"<{tag}") == html.count(f"</{tag}>"), f"{tag} unbalanced"


def test_html_has_one_sheet_per_footing_plus_the_schedule(project):
    html = calc_package_html(project.run(), project)
    assert html.count('class="sheet"') == 3          # schedule + 2 footings
    assert 'id="f-F-1"' in html and 'id="f-F-2"' in html
    assert 'href="#f-F-1"' in html                    # table of contents links


def test_html_escapes_user_supplied_text():
    p = Project("<script>alert(1)</script>", units="US")
    p.add_layer('Sand "quoted" & <odd>', thickness=40, gamma=120, phi=33, spt_n=22)
    p.add_column("<img src=x>", dead=100)
    html = calc_package_html(p.run(), p)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert "<img src=x>" not in html


def test_html_carries_the_scope_disclaimer(project):
    html = calc_package_html(project.run(), project)
    assert "SERVICE (unfactored) load" in html
    assert "one-way and two-way shear" in html
    assert "licensed" in html


def test_html_is_responsive_and_printable(project):
    html = calc_package_html(project.run(), project)
    assert "@media print" in html
    assert "@media(max-width:640px)" in html
    assert 'name=\'viewport\'' in html or 'name="viewport"' in html


def test_schedule_sheet_summarises_the_job(project):
    html = calc_package_html(project.run(), project)
    assert "Footing schedule" in html
    assert "Concrete volume" in html
    assert "Governing criteria" in html
    assert "Design criteria" in html
    assert "Soil profile" in html


def test_inferred_parameters_appear_in_the_package():
    p = Project("Inferred", units="US")
    p.add_layer("Sand", thickness=40, gamma=120, spt_n=18)
    p.infer_phi_from_spt()
    p.add_column("F-1", dead=120)
    html = calc_package_html(p.run(), p)
    assert "Inferred parameters" in html
    assert "ESTIMATED" in html


def test_sliding_reported_when_horizontal_load_present(project):
    results = project.run()
    f2 = [r for r in results if r.design.mark == "F-2"][0]
    assert f2.design.sliding_fs is not None
    assert "Sliding" in calc_package_html(results, project)


@pytest.mark.parametrize("water_table,expected_case", [
    (2.0, "Case I"),      # at/above the base
    (6.0, "Case II"),     # within B below the base
    (60.0, "Case III"),   # below the failure zone
])
def test_no_raw_si_leaks_into_us_output(water_table, expected_case):
    """Internal SI must never surface on a US-units sheet.

    Parametrised over all three groundwater cases on purpose: Cases I and II
    are the ones that carry numbers, and an earlier version of this test used a
    single fixture that happened to land on Case III - which carries none - so
    it passed while the leak was live.
    """
    p = Project("Leak check", units="US")
    p.add_layer("Sandy fill", thickness=8, gamma=115, gamma_sat=125, phi=30, spt_n=14)
    p.add_layer("Dense sand", thickness=40, gamma=128, gamma_sat=134, phi=38, spt_n=40)
    p.set_water_table(water_table)
    p.add_column("F-1", dead=120, live=60)
    results = p.run()
    assert results[0].design.bearing.gw_note.startswith(expected_case)

    html = calc_package_html(results, p)
    body = re.sub(r"<style>.*?</style>", "", html, flags=re.S)
    for token in ("kN/m3", "kN/m³", " kPa", "kN-m", " m below", " m.<"):
        assert token not in body, f"internal SI unit {token!r} leaked into output"
    assert calc_sheet_text(results[0], p).count("kN") == 0


def test_groundwater_note_reports_distance_in_user_units():
    p = Project("GW", units="US")
    p.add_layer("Sandy fill", thickness=8, gamma=115, gamma_sat=125, phi=30, spt_n=14)
    p.add_layer("Dense sand", thickness=40, gamma=128, gamma_sat=134, phi=38, spt_n=40)
    p.set_water_table(6.0)
    p.add_column("F-1", dead=120, live=60)
    r = p.run()[0]
    text = calc_sheet_text(r, p)
    assert "Case II" in text
    assert "ft below the base" in text
    assert "pcf" in text
