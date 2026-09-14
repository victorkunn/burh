"""Generate randomised design cases and their Python-engine results.

The JS port is only trustworthy if it agrees with the validated Python engine
across the whole input space, not on a couple of spot checks. This writes
cases.json; web/crossvalidate.mjs replays it through the browser engine.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from burh.codes import CANADA_LSD, US_ASD
from burh.design import ColumnLoad, DesignCriteria, design_footing
from burh.soil import Drainage, SoilLayer, SoilProfile

rng = random.Random(20260914)


def random_case(i: int) -> dict:
    n_layers = rng.choice([1, 1, 2, 2, 3])
    layers, depth = [], 0.0
    for k in range(n_layers):
        cohesive = rng.random() < 0.35 and k > 0
        thickness = round(rng.uniform(1.5, 12.0), 2)
        gamma = round(rng.uniform(16.0, 21.0), 2)
        if cohesive:
            layers.append(dict(
                name=f"Clay {k}", thickness=thickness, gamma=gamma,
                gamma_sat=round(gamma + rng.uniform(0.3, 1.5), 2),
                drainage="undrained", phi=0.0,
                cohesion=round(rng.uniform(25.0, 160.0), 2),
                elastic_modulus=round(rng.uniform(5000.0, 40000.0), 1),
                cc=round(rng.uniform(0.12, 0.45), 3),
                cr=round(rng.uniform(0.02, 0.07), 3),
                e0=round(rng.uniform(0.6, 1.3), 3),
                ocr=round(rng.choice([1.0, 1.0, 2.0, 4.0]), 2),
            ))
        else:
            layers.append(dict(
                name=f"Sand {k}", thickness=thickness, gamma=gamma,
                gamma_sat=round(gamma + rng.uniform(0.3, 1.5), 2),
                drainage="drained", phi=round(rng.uniform(28.0, 40.0), 2),
                cohesion=0.0,
                elastic_modulus=round(rng.uniform(8000.0, 60000.0), 1),
                soil_class=rng.choice(list(("sand_with_fines", "clean_sand_nc", "clean_sand_oc"))),
            ))
        depth += thickness
    # Ensure the profile is deep enough often, but not always.
    wt = rng.choice([float("inf"), round(rng.uniform(0.0, depth), 2)])

    load = dict(
        mark=f"C-{i}",
        dead=round(rng.uniform(80.0, 2500.0), 1),
        live=round(rng.uniform(0.0, 1200.0), 1),
        horizontal=round(rng.choice([0.0, 0.0, rng.uniform(5.0, 120.0)]), 1),
        moment_b=round(rng.choice([0.0, 0.0, rng.uniform(10.0, 300.0)]), 1),
        column_b=round(rng.uniform(0.3, 0.8), 2),
        column_l=round(rng.uniform(0.3, 0.8), 2),
    )
    crit = dict(
        code=rng.choice(["us_asd", "canada_lsd"]),
        factor_of_safety_bearing=round(rng.uniform(2.0, 3.5), 2),
        resistance_factor_bearing=round(rng.uniform(0.35, 0.65), 2),
        settlement_limit=round(rng.uniform(0.012, 0.060), 4),
        min_width=0.6,
        max_width=round(rng.uniform(3.0, 9.0), 2),
        size_increment=rng.choice([0.05, 0.1, 0.25 * 0.3048]),
        min_embedment=round(rng.uniform(0.45, 2.0), 2),
        aspect_ratio=rng.choice([1.0, 1.0, 1.5, 2.0]),
        bearing_method=rng.choice(["vesic", "hansen", "meyerhof"]),
        time_years=rng.choice([1.0, 10.0, 50.0]),
        influence_depth_ratio=1.5,
    )
    return dict(layers=layers, water_table=wt, load=load, criteria=crit)


def run(case: dict) -> dict:
    layers = [SoilLayer(
        name=l["name"], thickness=l["thickness"], gamma=l["gamma"],
        gamma_sat=l["gamma_sat"],
        drainage=Drainage(l["drainage"]), phi=l["phi"], cohesion=l["cohesion"],
        elastic_modulus=l["elastic_modulus"], cc=l.get("cc"), cr=l.get("cr"),
        e0=l.get("e0"), ocr=l.get("ocr", 1.0),
        soil_class=l.get("soil_class", "clean_sand_nc"),
    ) for l in case["layers"]]
    wt = case["water_table"]
    profile = SoilProfile(layers, float("inf") if wt == "inf" or wt == float("inf") else wt)

    c = case["criteria"]
    code = US_ASD if c["code"] == "us_asd" else CANADA_LSD
    from burh.bearing import BearingMethod
    crit = DesignCriteria(
        code=code,
        factor_of_safety_bearing=c["factor_of_safety_bearing"],
        resistance_factor_bearing=c["resistance_factor_bearing"],
        settlement_limit=c["settlement_limit"], min_width=c["min_width"],
        max_width=c["max_width"], size_increment=c["size_increment"],
        min_embedment=c["min_embedment"], aspect_ratio=c["aspect_ratio"],
        bearing_method=BearingMethod(c["bearing_method"]),
        time_years=c["time_years"], influence_depth_ratio=c["influence_depth_ratio"],
    )
    ld = case["load"]
    load = ColumnLoad(mark=ld["mark"], dead=ld["dead"], live=ld["live"],
                      horizontal=ld["horizontal"], moment_b=ld["moment_b"],
                      column_b=ld["column_b"], column_l=ld["column_l"])
    try:
        d = design_footing(profile, load, crit)
    except ValueError as exc:
        return {"error": str(exc)}
    out = {"ok": d.ok, "governing": d.governing, "b": d.b}
    if d.bearing is not None:
        out.update({
            "q_ult": d.bearing.q_ult, "q_demand": d.q_applied_gross,
            "q_capacity": d.q_allow_gross, "q_service": d.q_service_gross,
            "settlement": d.total_settlement,
            "bearing_util": d.bearing_utilisation,
            "settle_util": d.settlement_utilisation,
            "phi": d.bearing.phi, "nq": d.bearing.factors.nq,
            "ngamma": d.bearing.factors.ngamma,
            "surcharge": d.bearing.surcharge_q, "gamma_e": d.bearing.gamma_e,
            "b_eff": d.bearing.b_eff, "sliding_fs": d.sliding_fs,
            "equiv_fs": d.uls.equivalent_global_fs if d.uls else None,
            "combination": d.uls.combination if d.uls else None,
            "immediate": d.settlement_result.immediate,
            "consolidation": d.settlement_result.consolidation,
            "n_warnings": len(d.warnings),
        })
    return out


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 400
    cases = []
    for i in range(n):
        case = random_case(i)
        case["expected"] = run(case)
        if case["water_table"] == float("inf"):
            case["water_table"] = None
        cases.append(case)
    out = Path(__file__).with_name("cases.json")
    out.write_text(json.dumps(cases))
    solved = sum(1 for c in cases if c["expected"].get("ok"))
    errs = sum(1 for c in cases if "error" in c["expected"])
    print(f"{n} cases -> {out.name}  ({solved} solved, "
          f"{n - solved - errs} no-solution, {errs} rejected)")


if __name__ == "__main__":
    main()
