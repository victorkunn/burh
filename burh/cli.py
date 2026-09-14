"""Command line interface.

    burh design project.json --html calcs.html --csv schedule.csv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .api import Project
from .batch import load_project, write_schedule_csv
from .report import calc_package_html, calc_sheet_text


def _summarise(project: Project, results) -> str:
    u = project.units
    L, S = u.label("length"), u.label("stress")
    SL = u.label("small_length")
    lines = [
        "",
        f"{project.name}  -  {len(results)} footing(s), units {u.system.value}",
        "-" * 88,
        f"{'MARK':<10}{'B':>8}{'L':>8}{'t':>8}{'q_app':>10}{'q_all':>10}"
        f"{'settl':>9}{'GOVERNS':>18}{'':>5}",
        f"{'':<10}{'('+L+')':>8}{'('+L+')':>8}{'('+L+')':>8}{'('+S+')':>10}"
        f"{'('+S+')':>10}{'('+SL+')':>9}",
        "-" * 88,
    ]
    fails = 0
    for r in results:
        d = r.design
        if d.bearing is None:
            fails += 1
            lines.append(f"{d.mark:<10}{'-- no valid design --':>50}{'FAIL':>20}")
            continue
        if not d.ok:
            fails += 1
        lines.append(
            f"{d.mark:<10}{r.b:>8.2f}{r.l:>8.2f}{r.thickness:>8.2f}"
            f"{r.q_applied:>10.2f}{r.q_allow:>10.2f}{r.settlement:>9.3f}"
            f"{d.governing:>18}{'OK' if d.ok else 'FAIL':>5}"
        )
    lines.append("-" * 88)

    gov: dict[str, int] = {}
    for r in results:
        gov[r.design.governing] = gov.get(r.design.governing, 0) + 1
    lines.append("Governing: " + ", ".join(f"{k} ({v})" for k, v in sorted(gov.items())))

    vol = sum(r.concrete_volume for r in results if r.design.ok)
    unit = "ft3" if u.system.value == "US" else "m3"
    lines.append(f"Concrete:  {vol:,.1f} {unit}")

    n_warn = sum(1 for r in results if r.design.warnings)
    if n_warn:
        lines.append(f"Notes:     {n_warn} footing(s) carry engineering notes - "
                     "read the calculation package before sealing.")
    if fails:
        lines.append(f"FAILURES:  {fails} footing(s) do not satisfy the criteria.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="burh",
        description="Batch shallow foundation design and calculation packages.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("design", help="size every footing in a project")
    run.add_argument("project", type=Path, help="project JSON file")
    run.add_argument("--html", type=Path, help="write the calculation package here")
    run.add_argument("--csv", type=Path, help="write the footing schedule here")
    run.add_argument("--sheet", metavar="MARK",
                     help="print the full calculation sheet for one footing")
    run.add_argument("--quiet", action="store_true", help="suppress the summary table")

    args = parser.parse_args(argv)

    try:
        project = load_project(args.project)
        results = project.run()
    except (ValueError, OSError) as exc:
        print(f"burh: {exc}", file=sys.stderr)
        return 2

    if not args.quiet:
        print(_summarise(project, results))

    if args.sheet:
        match = [r for r in results if r.design.mark == args.sheet]
        if not match:
            print(f"burh: no footing marked {args.sheet!r}", file=sys.stderr)
            return 2
        print()
        print(calc_sheet_text(match[0], project))

    if args.html:
        args.html.write_text(calc_package_html(results, project), encoding="utf-8")
        print(f"\nCalculation package -> {args.html}")

    if args.csv:
        write_schedule_csv(results, args.csv)
        print(f"Footing schedule    -> {args.csv}")

    return 0 if all(r.design.ok for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
