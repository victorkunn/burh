"""Calculation sheet generation.

The output is deliberately verbose. A number without its derivation cannot be
checked, and an unchecked number cannot be sealed. Every factor, every term
and every assumption appears on the sheet.

HTML is the output format because every machine can print it to PDF and it
needs no third-party library.
"""

from __future__ import annotations

import html
from datetime import date

from .api import Project, ProjectResult
from .soil import Drainage
from .units import Units


def _f(x: float, n: int = 2) -> str:
    return f"{x:,.{n}f}"


# --------------------------------------------------------------------------
# Plain text
# --------------------------------------------------------------------------


def calc_sheet_text(result: ProjectResult, project: Project) -> str:
    d = result.design
    u = result.units
    L, F, S = u.label("length"), u.label("force"), u.label("stress")
    SL = u.label("small_length")
    out: list[str] = []
    w = out.append

    w("=" * 78)
    w(f"FOOTING {d.mark}".center(78))
    w("=" * 78)

    if not d.ok and d.bearing is None:
        w("")
        w("*** NO VALID DESIGN ***")
        w(d.message)
        return "\n".join(out)

    w("")
    w(f"  Size            {_f(result.b)} x {_f(result.l)} {L}  "
      f"x {_f(result.thickness)} {L} thick")
    w(f"  Founding depth  {_f(result.df)} {L} below grade")
    w(f"  GOVERNED BY     {d.governing}")
    w("")
    w("-" * 78)
    w("BEARING CAPACITY  (Vesic general equation, service loads)")
    w("-" * 78)

    b = d.bearing
    assert b is not None
    w(f"  Analysis            {b.drainage.value}")
    w(f"  phi' (averaged)     {_f(b.phi, 1)} deg")
    w(f"  c   (averaged)      {_f(u.from_si_stress(b.cohesion))} {S}")
    w(f"  Surcharge q         {_f(u.from_si_stress(b.surcharge_q))} {S}"
      f"   ({'total' if b.drainage is Drainage.UNDRAINED else 'effective'} stress at Df)")
    w(f"  gamma_e (B term)    {_f(u.from_si_unit_weight(b.gamma_e))} {u.label('unit_weight')}")
    w(f"  {b.gw_note}")
    w("")
    w(f"  Effective area      B' = {_f(u.from_si_length(b.b_eff))} {L}, "
      f"L' = {_f(u.from_si_length(b.l_eff))} {L}")
    w("")
    w(f"  {'':<10}{'N':>10}{'s':>10}{'d':>10}{'i':>10}{'term ('+S+')':>16}")
    w(f"  {'cohesion':<10}{b.factors.nc:>10.3f}{b.sc:>10.3f}{b.dc:>10.3f}{b.ic:>10.3f}"
      f"{u.from_si_stress(b.term_cohesion):>16,.2f}")
    w(f"  {'surcharge':<10}{b.factors.nq:>10.3f}{b.sq:>10.3f}{b.dq:>10.3f}{b.iq:>10.3f}"
      f"{u.from_si_stress(b.term_surcharge):>16,.2f}")
    w(f"  {'self wt':<10}{b.factors.ngamma:>10.3f}{b.sg:>10.3f}{b.dg:>10.3f}{b.ig:>10.3f}"
      f"{u.from_si_stress(b.term_self_weight):>16,.2f}")
    w(f"  {'':<50}{'-'*16}")
    w(f"  {'q_ult':<50}{u.from_si_stress(b.q_ult):>16,.2f}")
    w("")
    w(f"  q_allow = q_ult / FS = {_f(u.from_si_stress(b.q_ult))} / {b.factor_of_safety:g}"
      f" = {_f(result.q_allow)} {S}")
    w(f"  q_applied (gross, incl. footing + backfill) = {_f(result.q_applied)} {S}")
    w(f"  UTILISATION = {d.bearing_utilisation:.3f}   "
      f"{'OK' if d.bearing_utilisation <= 1.0 else '*** OVERSTRESSED ***'}")

    st = d.settlement_result
    if st is not None:
        w("")
        w("-" * 78)
        w("SETTLEMENT")
        w("-" * 78)
        w(f"  Net pressure dq     {_f(u.from_si_stress(st.net_pressure))} {S}")
        w(f"  sigma'_v0 at Df     {_f(u.from_si_stress(st.sigma_v0_base))} {S}")
        w(f"  C1 (embedment)      {st.c1:.4f}")
        w(f"  C2 (creep, {project.criteria.time_years:g} yr) {st.c2:.4f}")
        w(f"  Izp (peak)          {st.izp:.4f}   influence depth "
          f"{st.zmax_over_b:g}B")
        w("")
        if st.sublayers:
            w(f"  {'from':>8}{'to':>8}  {'layer':<22}{'method':<15}"
              f"{'settlement ('+SL+')':>20}")
            for s in st.sublayers:
                if abs(s.settlement) < 1e-9:
                    continue
                w(f"  {u.from_si_length(s.z_top):>8.2f}{u.from_si_length(s.z_bot):>8.2f}  "
                  f"{s.layer_name[:21]:<22}{s.method:<15}"
                  f"{u.from_si_settlement(s.settlement):>20.4f}")
            w(f"  {'':>53}{'-'*20}")
        w(f"  {'Immediate / Schmertmann':<53}"
          f"{u.from_si_settlement(st.immediate):>20.4f}")
        w(f"  {'Consolidation':<53}{u.from_si_settlement(st.consolidation):>20.4f}")
        w(f"  {'TOTAL':<53}{u.from_si_settlement(st.total):>20.4f}")
        w("")
        w(f"  Limit = {u.from_si_settlement(project.criteria.settlement_limit):.3f} {SL}"
          f"   UTILISATION = {d.settlement_utilisation:.3f}   "
          f"{'OK' if d.settlement_utilisation <= 1.0 else '*** EXCEEDED ***'}")

    if d.sliding_fs is not None:
        w("")
        w(f"  Sliding FS = {d.sliding_fs:.2f} "
          f"(required {project.criteria.factor_of_safety_sliding:g})")

    if d.warnings:
        w("")
        w("-" * 78)
        w("ENGINEERING NOTES  -  read before sealing")
        w("-" * 78)
        for i, note in enumerate(d.warnings, 1):
            w(f"  {i}. {note}")
    w("")
    return "\n".join(out)


# --------------------------------------------------------------------------
# HTML package
# --------------------------------------------------------------------------

_CSS = """
:root{--ink:#16202b;--mut:#5b6b7c;--line:#d6dee6;--bg:#fff;--accent:#0b5cad;
--warn-bg:#fff6e0;--warn-line:#e0a52a;--bad:#b3261e;--good:#1a6b3c;}
*{box-sizing:border-box}
body{margin:0;background:#eef2f6;color:var(--ink);
font:13px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.sheet{background:var(--bg);max-width:8.5in;margin:16px auto;padding:0.55in 0.6in;
box-shadow:0 1px 4px rgba(20,30,45,.14)}
h1{font-size:19px;margin:0 0 2px}
h2{font-size:13px;text-transform:uppercase;letter-spacing:.07em;margin:22px 0 7px;
padding-bottom:4px;border-bottom:1.5px solid var(--ink)}
h3{font-size:12px;margin:15px 0 5px;color:var(--mut);text-transform:uppercase;letter-spacing:.05em}
.hdr{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;
border-bottom:2.5px solid var(--ink);padding-bottom:9px;margin-bottom:6px;flex-wrap:wrap}
.meta{font-size:11px;color:var(--mut);text-align:right;white-space:nowrap}
table{border-collapse:collapse;width:100%;margin:7px 0;font-variant-numeric:tabular-nums}
th,td{padding:4px 7px;border-bottom:1px solid var(--line);text-align:right}
th:first-child,td:first-child{text-align:left}
thead th{background:#f3f6f9;border-bottom:1.5px solid var(--ink);font-size:11px;
text-transform:uppercase;letter-spacing:.04em;color:var(--mut)}
tfoot td{font-weight:700;border-top:1.5px solid var(--ink);border-bottom:none}
.kv{display:grid;grid-template-columns:minmax(150px,auto) 1fr;gap:2px 14px;margin:7px 0}
.kv dt{color:var(--mut)}
.kv dd{margin:0;font-variant-numeric:tabular-nums}
.eq{background:#f5f8fa;border-left:3px solid var(--accent);padding:8px 11px;margin:9px 0;
font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px;
white-space:pre-wrap;overflow-x:auto}
.util{display:inline-block;padding:1px 9px;border-radius:9px;font-weight:700;font-size:12px}
.ok{background:#e4f3ea;color:var(--good)} .bad{background:#fbe6e4;color:var(--bad)}
.gov{background:#eaf1fa;border:1px solid #b9d0ec;border-radius:5px;padding:9px 12px;margin:10px 0}
.gov b{color:var(--accent)}
.notes{background:var(--warn-bg);border:1px solid var(--warn-line);border-radius:5px;
padding:9px 13px;margin:12px 0}
.notes li{margin:5px 0}
.toc a{color:var(--accent);text-decoration:none}
.toc td{border-bottom:1px dotted var(--line)}
.fail{background:#fbe6e4;border:1px solid var(--bad);border-radius:5px;padding:11px 13px}
.disc{font-size:10.5px;color:var(--mut);border-top:1px solid var(--line);
margin-top:22px;padding-top:9px}
@media print{body{background:#fff}.sheet{box-shadow:none;margin:0;max-width:none;
page-break-after:always}.sheet:last-child{page-break-after:auto}}
@media(max-width:640px){.sheet{padding:18px 14px;margin:8px}
.kv{grid-template-columns:1fr}.kv dt{margin-top:6px}}
"""


def _esc(s: str) -> str:
    return html.escape(str(s))


def _util_badge(v: float) -> str:
    cls = "ok" if v <= 1.0 else "bad"
    return f'<span class="util {cls}">{v:.3f}</span>'


def _header(project: Project, subtitle: str) -> str:
    return (
        f'<div class="hdr"><div><h1>{_esc(project.name)}</h1>'
        f'<div style="color:var(--mut)">{_esc(subtitle)}</div></div>'
        f'<div class="meta">Shallow foundation design<br>'
        f'Units: {project.units.system.value}<br>{date.today().isoformat()}</div></div>'
    )


def _footing_sheet(result: ProjectResult, project: Project) -> str:
    d = result.design
    u: Units = result.units
    L, S = u.label("length"), u.label("stress")
    SL = u.label("small_length")
    p: list[str] = [f'<section class="sheet" id="f-{_esc(d.mark)}">']
    p.append(_header(project, f"Footing {d.mark}"))

    if not d.ok and d.bearing is None:
        p.append(f'<div class="fail"><b>No valid design.</b><br>{_esc(d.message)}</div>')
        p.append("</section>")
        return "".join(p)

    b = d.bearing
    st = d.settlement_result
    assert b is not None

    p.append(f'<div class="gov">Governed by <b>{_esc(d.governing)}</b> &mdash; '
             f'{_esc(d.mark)}: <b>{_f(result.b)} &times; {_f(result.l)} {L}</b>, '
             f'{_f(result.thickness)} {L} thick, founded {_f(result.df)} {L} below grade.'
             f'{"" if d.ok else " <b style=color:var(--bad)>DOES NOT SATISFY CRITERIA</b>"}</div>')

    p.append("<h2>Bearing capacity</h2>")
    p.append('<div class="eq">q_ult = c&middot;Nc&middot;sc&middot;dc&middot;ic '
             '+ q&middot;Nq&middot;sq&middot;dq&middot;iq '
             '+ &frac12;&middot;&gamma;e&middot;B\'&middot;N&gamma;&middot;s&gamma;&middot;d&gamma;&middot;i&gamma;</div>')
    p.append('<dl class="kv">')
    for k, v in [
        ("Analysis", b.drainage.value),
        ("Method", b.factors.method.value),
        ("&phi;&prime; (zone average)", f"{_f(b.phi,1)}&deg;"),
        ("c (zone average)", f"{_f(u.from_si_stress(b.cohesion))} {S}"),
        ("Surcharge q", f"{_f(u.from_si_stress(b.surcharge_q))} {S} "
                        f"({'total' if b.drainage is Drainage.UNDRAINED else 'effective'} stress)"),
        ("&gamma;e (self-weight term)", f"{_f(u.from_si_unit_weight(b.gamma_e))} "
                                        f"{u.label('unit_weight')}"),
        ("Groundwater", _esc(b.gw_note)),
        ("Effective dimensions", f"B&prime; = {_f(u.from_si_length(b.b_eff))} {L}, "
                                 f"L&prime; = {_f(u.from_si_length(b.l_eff))} {L}"),
    ]:
        p.append(f"<dt>{k}</dt><dd>{v}</dd>")
    p.append("</dl>")

    p.append(f'<table><thead><tr><th>Term</th><th>N</th><th>shape s</th>'
             f'<th>depth d</th><th>incl. i</th><th>Contribution ({S})</th></tr></thead><tbody>')
    for nm, n, s_, dd, i_, t in [
        ("Cohesion", b.factors.nc, b.sc, b.dc, b.ic, b.term_cohesion),
        ("Surcharge", b.factors.nq, b.sq, b.dq, b.iq, b.term_surcharge),
        ("Self weight", b.factors.ngamma, b.sg, b.dg, b.ig, b.term_self_weight),
    ]:
        p.append(f"<tr><td>{nm}</td><td>{n:.3f}</td><td>{s_:.3f}</td>"
                 f"<td>{dd:.3f}</td><td>{i_:.3f}</td><td>{u.from_si_stress(t):,.2f}</td></tr>")
    p.append(f'</tbody><tfoot><tr><td colspan="5">q_ult (gross ultimate)</td>'
             f'<td>{u.from_si_stress(b.q_ult):,.2f}</td></tr></tfoot></table>')

    p.append(f'<div class="eq">q_allow = q_ult / FS = '
             f'{_f(u.from_si_stress(b.q_ult))} / {b.factor_of_safety:g} '
             f'= {_f(result.q_allow)} {S}\n'
             f'q_applied (gross, incl. footing self-weight and backfill) '
             f'= {_f(result.q_applied)} {S}</div>')
    p.append(f"<p>Bearing utilisation {_util_badge(d.bearing_utilisation)}</p>")

    if st is not None:
        p.append("<h2>Settlement</h2>")
        p.append('<dl class="kv">')
        for k, v in [
            ("Net pressure &Delta;q", f"{_f(u.from_si_stress(st.net_pressure))} {S}"),
            ("&sigma;&prime;v0 at founding level", f"{_f(u.from_si_stress(st.sigma_v0_base))} {S}"),
            ("C1 (embedment)", f"{st.c1:.4f}"),
            (f"C2 (creep, {project.criteria.time_years:g} yr)", f"{st.c2:.4f}"),
            ("Izp (peak strain influence)", f"{st.izp:.4f}"),
            ("Influence depth", f"{st.zmax_over_b:g}B"),
        ]:
            p.append(f"<dt>{k}</dt><dd>{v}</dd>")
        p.append("</dl>")

        rows = [s for s in st.sublayers if abs(s.settlement) > 1e-9]
        if rows:
            p.append(f'<table><thead><tr><th>From ({L})</th><th>To ({L})</th>'
                     f'<th>Layer</th><th>Method</th><th>Settlement ({SL})</th>'
                     f'</tr></thead><tbody>')
            for s in rows:
                p.append(f"<tr><td>{u.from_si_length(s.z_top):.2f}</td>"
                         f"<td>{u.from_si_length(s.z_bot):.2f}</td>"
                         f"<td>{_esc(s.layer_name)}</td><td>{_esc(s.method)}</td>"
                         f"<td>{u.from_si_settlement(s.settlement):.4f}</td></tr>")
            p.append(f'</tbody><tfoot><tr><td colspan="4">Total</td>'
                     f'<td>{u.from_si_settlement(st.total):.4f}</td></tr></tfoot></table>')

        p.append(f'<div class="eq">Immediate / Schmertmann '
                 f'{u.from_si_settlement(st.immediate):.4f} {SL}\n'
                 f'Consolidation              {u.from_si_settlement(st.consolidation):.4f} {SL}\n'
                 f'TOTAL                      {u.from_si_settlement(st.total):.4f} {SL}\n'
                 f'Limit                      '
                 f'{u.from_si_settlement(project.criteria.settlement_limit):.4f} {SL}</div>')
        p.append(f"<p>Settlement utilisation {_util_badge(d.settlement_utilisation)}</p>")

    if d.sliding_fs is not None:
        req = project.criteria.factor_of_safety_sliding
        cls = "ok" if d.sliding_fs >= req else "bad"
        p.append(f'<h2>Sliding</h2><p>FS = <span class="util {cls}">'
                 f'{d.sliding_fs:.2f}</span> (required {req:g})</p>')

    if d.warnings:
        p.append('<div class="notes"><h3 style="margin-top:0">Engineering notes '
                 '&mdash; read before sealing</h3><ol>')
        for note in d.warnings:
            p.append(f"<li>{_esc(note)}</li>")
        p.append("</ol></div>")

    p.append('<div class="disc">Bearing capacity and settlement are evaluated at '
             'SERVICE (unfactored) load. Reinforced concrete design &mdash; flexure, '
             'one-way and two-way shear, development &mdash; is NOT covered by this '
             'calculation and must be performed separately. Correlated soil '
             'parameters are estimates; they do not replace laboratory or in-situ '
             'testing. This output requires review and sealing by a licensed '
             'engineer.</div>')
    p.append("</section>")
    return "".join(p)


def _schedule_sheet(results: list[ProjectResult], project: Project) -> str:
    u = project.units
    L, S = u.label("length"), u.label("stress")
    SL = u.label("small_length")
    vol = "ft&sup3;" if u.system.value == "US" else "m&sup3;"
    p = ['<section class="sheet">', _header(project, "Footing schedule")]

    total_vol = sum(r.concrete_volume for r in results if r.design.ok)
    n_ok = sum(1 for r in results if r.design.ok)
    gov: dict[str, int] = {}
    for r in results:
        gov[r.design.governing] = gov.get(r.design.governing, 0) + 1

    p.append('<dl class="kv">')
    p.append(f"<dt>Footings</dt><dd>{len(results)} ({n_ok} satisfy all criteria)</dd>")
    p.append(f"<dt>Concrete volume</dt><dd>{_f(total_vol,1)} {vol}</dd>")
    p.append(f"<dt>Governing criteria</dt><dd>"
             + ", ".join(f"{k}: {v}" for k, v in sorted(gov.items())) + "</dd>")
    p.append("</dl>")

    p.append(f'<table><thead><tr><th>Mark</th><th>B ({L})</th><th>L ({L})</th>'
             f'<th>t ({L})</th><th>Df ({L})</th><th>q applied ({S})</th>'
             f'<th>q allow ({S})</th><th>Settl. ({SL})</th><th>Governs</th>'
             f'<th>Status</th></tr></thead><tbody>')
    for r in results:
        d = r.design
        if d.bearing is None:
            p.append(f'<tr><td>{_esc(d.mark)}</td><td colspan="8">{_esc(d.message[:90])}</td>'
                     f'<td><span class="util bad">FAIL</span></td></tr>')
            continue
        status = ('<span class="util ok">OK</span>' if d.ok
                  else '<span class="util bad">FAIL</span>')
        p.append(f"<tr><td>{_esc(d.mark)}</td><td>{_f(r.b)}</td><td>{_f(r.l)}</td>"
                 f"<td>{_f(r.thickness)}</td><td>{_f(r.df)}</td>"
                 f"<td>{_f(r.q_applied)}</td><td>{_f(r.q_allow)}</td>"
                 f"<td>{r.settlement:.3f}</td><td>{_esc(d.governing)}</td>"
                 f"<td>{status}</td></tr>")
    p.append("</tbody></table>")

    p.append("<h2>Soil profile</h2>")
    p.append(f'<table><thead><tr><th>Depth ({L})</th><th>Layer</th><th>Analysis</th>'
             f'<th>&gamma; ({u.label("unit_weight")})</th><th>&phi;&prime; (&deg;)</th>'
             f'<th>c / su ({S})</th></tr></thead><tbody>')
    prof = project.profile
    for i, layer in enumerate(prof.layers):
        p.append(f"<tr><td>{u.from_si_length(prof.layer_top(i)):.2f} &ndash; "
                 f"{u.from_si_length(prof.layer_bottom(i)):.2f}</td>"
                 f"<td>{_esc(layer.name)}</td><td>{layer.drainage.value}</td>"
                 f"<td>{u.from_si_unit_weight(layer.gamma):.1f}</td>"
                 f"<td>{layer.phi:.1f}</td>"
                 f"<td>{u.from_si_stress(layer.cohesion):.2f}</td></tr>")
    p.append("</tbody></table>")
    wt = prof.water_table_depth
    p.append(f'<p>Groundwater: '
             f'{"not encountered" if wt == float("inf") else f"{u.from_si_length(wt):.2f} {L} below grade"}</p>')

    notes = [n for layer in prof.layers for n in layer.notes]
    if notes:
        p.append('<div class="notes"><h3 style="margin-top:0">Inferred parameters</h3><ol>')
        for n in notes:
            p.append(f"<li>{_esc(n)}</li>")
        p.append("</ol></div>")

    p.append("<h2>Design criteria</h2>")
    c = project.criteria
    p.append('<dl class="kv">')
    for k, v in [
        ("FS, bearing", f"{c.factor_of_safety_bearing:g}"),
        ("FS, sliding", f"{c.factor_of_safety_sliding:g}"),
        ("Settlement limit", f"{u.from_si_settlement(c.settlement_limit):.3f} {SL}"),
        ("Minimum embedment", f"{u.from_si_length(c.min_embedment):.2f} {L}"),
        ("Size increment", f"{u.from_si_length(c.size_increment):.2f} {L}"),
        ("Width searched", f"{u.from_si_length(c.min_width):.2f} &ndash; "
                           f"{u.from_si_length(c.max_width):.2f} {L}"),
        ("N&gamma; method", c.bearing_method.value),
        ("Design life (creep)", f"{c.time_years:g} yr"),
    ]:
        p.append(f"<dt>{k}</dt><dd>{v}</dd>")
    p.append("</dl>")

    p.append('<h2>Contents</h2><table class="toc"><tbody>')
    for r in results:
        p.append(f'<tr><td><a href="#f-{_esc(r.design.mark)}">Footing '
                 f'{_esc(r.design.mark)}</a></td>'
                 f'<td>{_esc(r.design.governing)}</td></tr>')
    p.append("</tbody></table></section>")
    return "".join(p)


def calc_package_html(results: list[ProjectResult], project: Project) -> str:
    """Full calculation package: schedule sheet followed by one sheet per
    footing. Print to PDF from any browser."""
    body = [_schedule_sheet(results, project)]
    body += [_footing_sheet(r, project) for r in results]
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{_esc(project.name)} - Footing calculations</title>"
        f"<style>{_CSS}</style></head><body>{''.join(body)}</body></html>"
    )
