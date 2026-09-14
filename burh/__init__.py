"""Burh - batch shallow foundation design.

Sizes spread footings against bearing capacity AND settlement, reports which
one governs, and emits an auditable calculation package.

    from burh import Project

    p = Project("Warehouse", units="US")
    p.add_layer("Medium dense sand", thickness=30, gamma=120, phi=33, spt_n=20)
    p.set_water_table(18)
    p.add_column("F-1", dead=180, live=95)
    for r in p.run():
        print(r.design.mark, r.b, r.design.governing)
"""

from .api import Project, ProjectResult
from .batch import load_project, read_loads_csv, write_schedule_csv
from .bearing import BearingMethod, bearing_factors, ultimate_bearing_capacity
from .design import ColumnLoad, DesignCriteria, FootingDesign, design_footing
from .report import calc_package_html, calc_sheet_text
from .settlement import settlement
from .soil import Drainage, PhiCorrelation, SoilLayer, SoilProfile
from .stress import boussinesq_rectangle_center, newmark_corner_influence
from .units import UnitSystem, Units

__version__ = "0.1.0"

__all__ = [
    "Project", "ProjectResult",
    "SoilLayer", "SoilProfile", "Drainage", "PhiCorrelation",
    "ColumnLoad", "DesignCriteria", "FootingDesign", "design_footing",
    "BearingMethod", "bearing_factors", "ultimate_bearing_capacity",
    "settlement", "boussinesq_rectangle_center", "newmark_corner_influence",
    "calc_package_html", "calc_sheet_text",
    "load_project", "read_loads_csv", "write_schedule_csv",
    "Units", "UnitSystem", "__version__",
]
