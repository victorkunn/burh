"""Batch input/output.

Column loads arrive as a CSV export from the analysis model (ETABS, RAM, RISA,
SAP) and leave as a footing schedule CSV that drops into the drawing set.
Everything is stdlib ``csv`` and ``json``.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .api import Project, ProjectResult

#: Accepted spellings for each load column, lower-cased and stripped.
_ALIASES: dict[str, tuple[str, ...]] = {
    "mark": ("mark", "id", "name", "column", "label", "footing"),
    "dead": ("dead", "d", "dl", "dead_load", "p_dead"),
    "live": ("live", "l", "ll", "live_load", "p_live"),
    "horizontal": ("horizontal", "h", "shear", "vx", "lateral"),
    "moment_b": ("moment_b", "mb", "m_b", "mxx", "moment"),
    "moment_l": ("moment_l", "ml", "m_l", "myy"),
    "column_b": ("column_b", "cb", "col_b", "cx"),
    "column_l": ("column_l", "cl", "col_l", "cy"),
    "embedment": ("embedment", "df", "depth", "founding_depth"),
}


def _normalise_header(field: str) -> str | None:
    key = field.strip().lower().replace(" ", "_").replace("-", "_")
    for canonical, spellings in _ALIASES.items():
        if key in spellings:
            return canonical
    return None


def read_loads_csv(path: str | Path) -> list[dict[str, Any]]:
    """Read a column-load CSV, tolerating the header spellings that different
    analysis packages emit.

    Raises with a clear message rather than silently dropping a column, since
    a silently ignored load is the worst possible failure mode here.
    """
    path = Path(path)
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.reader(fh)
        try:
            header = next(reader)
        except StopIteration:
            raise ValueError(f"{path}: file is empty.") from None

        mapping: dict[int, str] = {}
        unknown: list[str] = []
        for i, field in enumerate(header):
            if not field.strip():
                continue
            canonical = _normalise_header(field)
            if canonical is None:
                unknown.append(field)
            else:
                mapping[i] = canonical

        if "mark" not in mapping.values():
            raise ValueError(
                f"{path}: no column identifier found. Expected one of "
                f"{_ALIASES['mark']}; got {header}."
            )
        if "dead" not in mapping.values():
            raise ValueError(
                f"{path}: no dead load column found. Expected one of "
                f"{_ALIASES['dead']}; got {header}."
            )
        if unknown:
            raise ValueError(
                f"{path}: unrecognised column(s) {unknown}. Rename or remove them "
                "so no load is silently ignored. Recognised names: "
                + ", ".join(sorted(_ALIASES))
            )

        rows: list[dict[str, Any]] = []
        for lineno, raw in enumerate(reader, start=2):
            if not any(cell.strip() for cell in raw):
                continue
            row: dict[str, Any] = {}
            for i, cell in enumerate(raw):
                key = mapping.get(i)
                if key is None:
                    continue
                cell = cell.strip()
                if key == "mark":
                    row[key] = cell
                elif cell == "":
                    continue
                else:
                    try:
                        row[key] = float(cell)
                    except ValueError:
                        raise ValueError(
                            f"{path} line {lineno}: column {key!r} has "
                            f"non-numeric value {cell!r}."
                        ) from None
            if not row.get("mark"):
                raise ValueError(f"{path} line {lineno}: blank column mark.")
            rows.append(row)

    if not rows:
        raise ValueError(f"{path}: header found but no data rows.")
    return rows


def write_schedule_csv(results: list[ProjectResult], path: str | Path) -> None:
    """Write the footing schedule."""
    path = Path(path)
    u = results[0].units if results else None
    L = u.label("length") if u else "m"
    S = u.label("stress") if u else "kPa"
    SL = u.label("small_length") if u else "mm"

    with path.open("w", newline="", encoding="utf-8") as fh:
        wr = csv.writer(fh)
        wr.writerow([
            "mark", f"B ({L})", f"L ({L})", f"thickness ({L})", f"Df ({L})",
            f"q_applied ({S})", f"q_allow ({S})", "bearing_util",
            f"settlement ({SL})", "settlement_util", "governs", "status", "notes",
        ])
        for r in results:
            d = r.design
            if d.bearing is None:
                wr.writerow([d.mark, "", "", "", "", "", "", "", "", "",
                             d.governing, "FAIL", d.message])
                continue
            wr.writerow([
                d.mark, f"{r.b:.2f}", f"{r.l:.2f}", f"{r.thickness:.2f}",
                f"{r.df:.2f}", f"{r.q_applied:.3f}", f"{r.q_allow:.3f}",
                f"{d.bearing_utilisation:.3f}", f"{r.settlement:.3f}",
                f"{d.settlement_utilisation:.3f}", d.governing,
                "OK" if d.ok else "FAIL",
                " | ".join(d.warnings),
            ])


def load_project(path: str | Path) -> Project:
    """Build a :class:`Project` from a JSON definition.

    Schema::

        {
          "name": "...",
          "units": "US" | "SI",
          "water_table": 18.0,
          "criteria": { "fs_bearing": 3.0, "settlement_limit": 1.0, ... },
          "layers":  [ { "name": "...", "thickness": 6, "gamma": 115, ... } ],
          "loads":   [ { "mark": "F-1", "dead": 180, "live": 95 } ],
          "loads_csv": "loads.csv",
          "infer_phi_from_spt": true
        }
    """
    path = Path(path)
    with path.open(encoding="utf-8") as fh:
        try:
            data = json.load(fh)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}: invalid JSON - {exc}") from None

    if not isinstance(data, dict):
        raise ValueError(f"{path}: top level must be a JSON object.")

    project = Project(name=data.get("name", path.stem),
                      units=data.get("units", "US"))

    layers = data.get("layers")
    if not layers:
        raise ValueError(f"{path}: 'layers' is required and must be non-empty.")
    for i, layer in enumerate(layers):
        try:
            project.add_layer(**layer)
        except TypeError as exc:
            raise ValueError(f"{path}: layer {i} has a bad field - {exc}") from None

    if "water_table" in data and data["water_table"] is not None:
        project.set_water_table(float(data["water_table"]))

    if data.get("criteria"):
        try:
            project.set_criteria(**data["criteria"])
        except TypeError as exc:
            raise ValueError(f"{path}: bad 'criteria' field - {exc}") from None

    if data.get("infer_phi_from_spt"):
        project.infer_phi_from_spt(
            data.get("phi_correlation", "kulhawy_mayne_1990")
        )

    rows: list[dict[str, Any]] = list(data.get("loads") or [])
    if data.get("loads_csv"):
        csv_path = Path(data["loads_csv"])
        if not csv_path.is_absolute():
            csv_path = path.parent / csv_path
        rows.extend(read_loads_csv(csv_path))
    if not rows:
        raise ValueError(f"{path}: no column loads (use 'loads' or 'loads_csv').")

    seen: set[str] = set()
    for row in rows:
        mark = str(row["mark"])
        if mark in seen:
            raise ValueError(f"{path}: duplicate column mark {mark!r}.")
        seen.add(mark)
        try:
            project.add_column(**{**row, "mark": mark})
        except TypeError as exc:
            raise ValueError(f"{path}: load {mark!r} has a bad field - {exc}") from None

    return project
