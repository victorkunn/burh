"""Batch I/O, project loading and CLI validation."""

import csv
import json
from pathlib import Path

import pytest

from burh.batch import load_project, read_loads_csv, write_schedule_csv
from burh.cli import main


@pytest.fixture
def loads_csv(tmp_path):
    p = tmp_path / "loads.csv"
    p.write_text("Mark,Dead,Live\nF-1,100,50\nF-2,150,75\n", encoding="utf-8")
    return p


@pytest.fixture
def project_json(tmp_path, loads_csv):
    p = tmp_path / "project.json"
    p.write_text(json.dumps({
        "name": "Test job",
        "units": "US",
        "water_table": 20.0,
        "criteria": {"fs_bearing": 3.0, "settlement_limit": 1.0},
        "layers": [{"name": "Sand", "thickness": 40, "gamma": 120,
                    "phi": 33, "spt_n": 22}],
        "loads_csv": "loads.csv",
    }), encoding="utf-8")
    return p


# -- loads CSV --------------------------------------------------------------


def test_read_loads_csv(loads_csv):
    rows = read_loads_csv(loads_csv)
    assert rows == [{"mark": "F-1", "dead": 100.0, "live": 50.0},
                    {"mark": "F-2", "dead": 150.0, "live": 75.0}]


@pytest.mark.parametrize("header", [
    "Mark,Dead,Live", "id,DL,LL", "name,dead_load,live_load",
    "Column,D,L", "  mark  ,  dead  ,  live  ",
])
def test_header_aliases_from_different_analysis_packages(tmp_path, header):
    p = tmp_path / "l.csv"
    p.write_text(f"{header}\nF-1,100,50\n", encoding="utf-8")
    rows = read_loads_csv(p)
    assert rows[0]["mark"] == "F-1" and rows[0]["dead"] == 100.0


def test_utf8_bom_is_tolerated(tmp_path):
    """Excel writes a BOM. Without utf-8-sig the first header becomes
    '\\ufeffMark' and the mark column is silently lost."""
    p = tmp_path / "l.csv"
    p.write_bytes("Mark,Dead\nF-1,100\n".encode("utf-8-sig"))
    assert read_loads_csv(p)[0]["mark"] == "F-1"


def test_blank_rows_are_skipped(tmp_path):
    p = tmp_path / "l.csv"
    p.write_text("Mark,Dead\nF-1,100\n\n,,\nF-2,150\n", encoding="utf-8")
    assert len(read_loads_csv(p)) == 2


def test_unknown_column_is_an_error_not_a_silent_drop(tmp_path):
    """A silently ignored load column is the worst failure mode in this tool."""
    p = tmp_path / "l.csv"
    p.write_text("Mark,Dead,Snow\nF-1,100,30\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unrecognised column"):
        read_loads_csv(p)


def test_missing_required_columns_rejected(tmp_path):
    p = tmp_path / "l.csv"
    p.write_text("Dead,Live\n100,50\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no column identifier"):
        read_loads_csv(p)
    p.write_text("Mark,Live\nF-1,50\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no dead load"):
        read_loads_csv(p)


def test_non_numeric_value_reports_line_and_column(tmp_path):
    p = tmp_path / "l.csv"
    p.write_text("Mark,Dead\nF-1,100\nF-2,heavy\n", encoding="utf-8")
    with pytest.raises(ValueError, match="line 3.*'dead'.*'heavy'"):
        read_loads_csv(p)


def test_blank_mark_rejected(tmp_path):
    p = tmp_path / "l.csv"
    p.write_text("Mark,Dead\n,100\n", encoding="utf-8")
    with pytest.raises(ValueError, match="blank column mark"):
        read_loads_csv(p)


def test_empty_file_rejected(tmp_path):
    p = tmp_path / "l.csv"
    p.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        read_loads_csv(p)
    p.write_text("Mark,Dead\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no data rows"):
        read_loads_csv(p)


# -- project JSON -----------------------------------------------------------


def test_load_project_resolves_csv_relative_to_the_json(project_json):
    p = load_project(project_json)
    assert p.name == "Test job"
    assert len(p.loads) == 2
    assert p.units.system.value == "US"


def test_load_project_runs_end_to_end(project_json):
    results = load_project(project_json).run()
    assert len(results) == 2
    assert all(r.design.ok for r in results)


def test_inline_loads_and_csv_loads_combine(tmp_path, loads_csv):
    p = tmp_path / "p.json"
    p.write_text(json.dumps({
        "units": "US",
        "layers": [{"name": "Sand", "thickness": 40, "gamma": 120, "phi": 33, "spt_n": 22}],
        "loads": [{"mark": "X-1", "dead": 80}],
        "loads_csv": "loads.csv",
    }), encoding="utf-8")
    assert len(load_project(p).loads) == 3


def test_duplicate_marks_rejected(tmp_path):
    p = tmp_path / "p.json"
    p.write_text(json.dumps({
        "units": "US",
        "layers": [{"name": "Sand", "thickness": 40, "gamma": 120, "phi": 33, "spt_n": 22}],
        "loads": [{"mark": "F-1", "dead": 80}, {"mark": "F-1", "dead": 90}],
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate column mark"):
        load_project(p)


def test_bad_json_reports_clearly(tmp_path):
    p = tmp_path / "p.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid JSON"):
        load_project(p)


def test_missing_layers_rejected(tmp_path):
    p = tmp_path / "p.json"
    p.write_text(json.dumps({"units": "US", "loads": [{"mark": "A", "dead": 10}]}),
                 encoding="utf-8")
    with pytest.raises(ValueError, match="'layers' is required"):
        load_project(p)


def test_missing_loads_rejected(tmp_path):
    p = tmp_path / "p.json"
    p.write_text(json.dumps({
        "units": "US",
        "layers": [{"name": "Sand", "thickness": 40, "gamma": 120, "phi": 33, "spt_n": 22}],
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="no column loads"):
        load_project(p)


def test_bad_layer_field_names_the_problem(tmp_path):
    p = tmp_path / "p.json"
    p.write_text(json.dumps({
        "units": "US",
        "layers": [{"name": "Sand", "thickness": 40, "gamma": 120, "wrong_field": 1}],
        "loads": [{"mark": "A", "dead": 10}],
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="bad field"):
        load_project(p)


def test_infer_phi_flag_is_honoured(tmp_path):
    p = tmp_path / "p.json"
    p.write_text(json.dumps({
        "units": "US",
        "layers": [{"name": "Sand", "thickness": 40, "gamma": 120, "spt_n": 22}],
        "loads": [{"mark": "A", "dead": 100}],
        "infer_phi_from_spt": True,
    }), encoding="utf-8")
    assert load_project(p).profile.layers[0].phi > 0


# -- schedule out -----------------------------------------------------------


def test_schedule_csv_round_trips(project_json, tmp_path):
    results = load_project(project_json).run()
    out = tmp_path / "schedule.csv"
    write_schedule_csv(results, out)
    with out.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    assert rows[0][0] == "mark"
    assert "(ft)" in rows[0][1] and "(ksf)" in rows[0][5]
    assert len(rows) == 3
    assert rows[1][0] == "F-1" and rows[1][11] == "OK"


def test_schedule_csv_records_failures(tmp_path):
    p = tmp_path / "p.json"
    p.write_text(json.dumps({
        "units": "US",
        "criteria": {"max_width": 4.0},
        "layers": [{"name": "Sand", "thickness": 40, "gamma": 120, "phi": 30, "spt_n": 10}],
        "loads": [{"mark": "BIG", "dead": 5000}],
    }), encoding="utf-8")
    results = load_project(p).run()
    out = tmp_path / "s.csv"
    write_schedule_csv(results, out)
    body = out.read_text(encoding="utf-8")
    assert "FAIL" in body and "BIG" in body


# -- CLI --------------------------------------------------------------------


def test_cli_success_returns_zero(project_json, tmp_path, capsys):
    rc = main(["design", str(project_json),
               "--csv", str(tmp_path / "s.csv"),
               "--html", str(tmp_path / "c.html")])
    assert rc == 0
    assert (tmp_path / "s.csv").exists()
    assert (tmp_path / "c.html").exists()
    out = capsys.readouterr().out
    assert "F-1" in out and "GOVERNS" in out


def test_cli_returns_one_when_a_footing_fails(tmp_path, capsys):
    p = tmp_path / "p.json"
    p.write_text(json.dumps({
        "units": "US",
        "criteria": {"max_width": 4.0},
        "layers": [{"name": "Sand", "thickness": 40, "gamma": 120, "phi": 30, "spt_n": 10}],
        "loads": [{"mark": "BIG", "dead": 5000}],
    }), encoding="utf-8")
    assert main(["design", str(p)]) == 1


def test_cli_returns_two_on_bad_input(tmp_path, capsys):
    bad = tmp_path / "nope.json"
    assert main(["design", str(bad)]) == 2
    assert "burh:" in capsys.readouterr().err


def test_cli_single_sheet(project_json, capsys):
    assert main(["design", str(project_json), "--sheet", "F-1", "--quiet"]) == 0
    out = capsys.readouterr().out
    assert "FOOTING F-1" in out and "BEARING CAPACITY" in out


def test_cli_unknown_mark_errors(project_json, capsys):
    assert main(["design", str(project_json), "--sheet", "NOPE"]) == 2
    assert "no footing marked" in capsys.readouterr().err


def test_shipped_example_project_runs(tmp_path):
    """The example in the repo must actually work - a broken example is worse
    than no example."""
    example = Path(__file__).resolve().parents[1] / "examples" / "warehouse.json"
    results = load_project(example).run()
    assert len(results) == 12
    ok = [r for r in results if r.design.ok]
    assert len(ok) >= 8
    # The whole point of the tool: on this profile settlement governs.
    assert all(r.design.governing == "Settlement" for r in ok)
    assert min(r.design.bearing_utilisation for r in ok) < 0.6
