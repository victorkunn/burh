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


#: Proper names for the N-gamma formulations, for display only.
_METHOD_LABEL = {"vesic": "Vesic", "meyerhof": "Meyerhof", "hansen": "Hansen"}


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
:root{
  --paper:#ffffff;
  --ground:#e4e9ed;          /* cool grey, biased toward the drafting blue */
  --ink:#1a2530;
  --ink-soft:#5a6b7a;
  --rule:#ccd5dd;
  --rule-hard:#1a2530;
  --blue:#1c4f82;            /* drafting ink */
  --blue-wash:#eef3f9;
  --ochre:#8a5a00;           /* redline note */
  --ochre-wash:#fdf4e0;
  --red:#9c2620;
  --red-wash:#faeae8;
  --green:#16603a;
  --green-wash:#e6f1eb;
  --display:"Barlow Condensed","Arial Narrow",Haettenschweiler,sans-serif;
  --body:"Source Sans 3","Segoe UI",Helvetica,Arial,sans-serif;
  --mono:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);
  font:15px/1.55 var(--body);-webkit-text-size-adjust:100%}
.sheet{background:var(--paper);max-width:8.5in;margin:18px auto;
  padding-block:0.5in;padding-inline:0.6in;border:1px solid var(--rule);
  box-shadow:0 1px 3px rgba(26,37,48,.10)}

/* --- title block ------------------------------------------------------- */
.tb{display:grid;grid-template-columns:1fr auto;gap:6px 22px;align-items:end;
  border-bottom:2.5px solid var(--rule-hard);padding-bottom:8px}
.tb h1{font:600 26px/1.05 var(--display);margin:0;letter-spacing:.005em;
  text-wrap:balance}
.tb .sub{font:500 15px/1.2 var(--display);color:var(--blue);
  text-transform:uppercase;letter-spacing:.10em;margin-top:3px}
.tb .stamp{font:500 12px/1.5 var(--display);color:var(--ink-soft);
  text-transform:uppercase;letter-spacing:.09em;text-align:right;
  white-space:nowrap;font-variant-numeric:tabular-nums}
.tb .stamp b{color:var(--ink);font-weight:600}

h2{font:600 15px/1.2 var(--display);text-transform:uppercase;letter-spacing:.11em;
  margin:26px 0 8px;padding-bottom:5px;border-bottom:1.5px solid var(--rule-hard)}
h3{font:600 13px/1.2 var(--display);text-transform:uppercase;letter-spacing:.09em;
  color:var(--ink-soft);margin:16px 0 6px}

/* --- tables ------------------------------------------------------------ */
.tw{overflow-x:auto}
table{border-collapse:collapse;width:100%;margin:8px 0;
  font-variant-numeric:tabular-nums;font-size:14px}
th,td{padding:5px 8px;border-bottom:1px solid var(--rule);text-align:right}
th:first-child,td:first-child{text-align:left}
thead th{font:600 11.5px/1.3 var(--display);text-transform:uppercase;
  letter-spacing:.07em;color:var(--ink-soft);background:var(--blue-wash);
  border-bottom:1.5px solid var(--rule-hard);white-space:nowrap}
tbody td{font-family:var(--mono);font-size:13px}
/* Text cells opt out of the monospace/right-aligned numeric treatment. */
tbody td:first-child,td.t{font-family:var(--body);text-align:left}
/* Greek symbols are quantity names: gamma is not Gamma, phi is not Phi, so
   they must escape the uppercase transform on headings and labels. */
.g{text-transform:none}
thead th .u{display:block;font-weight:500;opacity:.8;text-transform:none;
  letter-spacing:.02em}
tfoot td{font-weight:700;border-top:1.5px solid var(--rule-hard);border-bottom:none;
  font-family:var(--mono)}

/* --- key/value ---------------------------------------------------------- */
.kv{display:grid;grid-template-columns:minmax(160px,auto) 1fr;gap:3px 18px;margin:8px 0}
.kv dt{font:500 13px/1.5 var(--display);text-transform:uppercase;
  letter-spacing:.06em;color:var(--ink-soft)}
.kv dd{margin:0;font-variant-numeric:tabular-nums}

/* --- computation blocks ------------------------------------------------- */
.eq{background:var(--blue-wash);border-left:3px solid var(--blue);
  padding:10px 13px;margin:10px 0;font-family:var(--mono);font-size:13px;
  line-height:1.65;white-space:pre-wrap;overflow-x:auto}

.util{display:inline-block;padding:1px 10px;border-radius:2px;font-weight:700;
  font-size:13px;font-family:var(--mono)}
.ok{background:var(--green-wash);color:var(--green)}
.bad{background:var(--red-wash);color:var(--red)}

.gov{background:var(--blue-wash);border-left:3px solid var(--blue);
  padding:10px 13px;margin:12px 0}
.gov b{color:var(--blue)}

.notes{background:var(--ochre-wash);border-left:3px solid var(--ochre);
  padding:10px 15px;margin:14px 0}
.notes li{margin:6px 0}
.notes h3{color:var(--ochre)}

.fail{background:var(--red-wash);border-left:3px solid var(--red);
  padding:12px 15px}

.toc a{color:var(--blue);text-decoration:none}
.toc a:hover{text-decoration:underline}
.toc td{border-bottom:1px dotted var(--rule)}

.disc{font-size:12px;line-height:1.5;color:var(--ink-soft);
  border-top:1px solid var(--rule);margin-top:26px;padding-top:10px}

a:focus-visible,:focus-visible{outline:2px solid var(--blue);outline-offset:2px}

@media print{
  body{background:#fff}
  .sheet{box-shadow:none;border:none;margin:0;max-width:none;page-break-after:always}
  .sheet:last-child{page-break-after:auto}
}
@media(max-width:640px){
  .sheet{padding-inline:16px;padding-block:22px;margin:8px}
  .tb{grid-template-columns:1fr}
  .tb .stamp{text-align:left}
  .kv{grid-template-columns:1fr}
  .kv dt{margin-top:8px}
}
@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
"""


def _esc(s: str) -> str:
    return html.escape(str(s))


def _util_badge(v: float) -> str:
    cls = "ok" if v <= 1.0 else "bad"
    return f'<span class="util {cls}">{v:.3f}</span>'


def _header(project: Project, subtitle: str,
            sheet: int | None = None, total: int | None = None) -> str:
    """Drawing title block: project and sheet on the left, the stamp fields a
    reviewer looks for on the right."""
    num = (f"Sheet <b>{sheet}</b> of <b>{total}</b><br>"
           if sheet is not None and total is not None else "")
    return (
        f'<div class="tb"><div><h1>{_esc(project.name)}</h1>'
        f'<div class="sub">{_esc(subtitle)}</div></div>'
        f'<div class="stamp">{num}'
        f'Shallow foundation design<br>'
        f'Units <b>{project.units.system.value}</b><br>'
        f'{date.today().isoformat()}</div></div>'
    )


def _footing_sheet(result: ProjectResult, project: Project,
                   sheet: int | None = None, total: int | None = None) -> str:
    d = result.design
    u: Units = result.units
    L, S = u.label("length"), u.label("stress")
    SL = u.label("small_length")
    p: list[str] = [f'<section class="sheet" id="f-{_esc(d.mark)}">']
    p.append(_header(project, f"Footing {d.mark}", sheet, total))

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
        ("Method", _METHOD_LABEL.get(b.factors.method.value, b.factors.method.value)),
        ('<span class="g">&phi;&prime;</span> (zone average)', f"{_f(b.phi,1)}&deg;"),
        ("c (zone average)", f"{_f(u.from_si_stress(b.cohesion))} {S}"),
        ("Surcharge q", f"{_f(u.from_si_stress(b.surcharge_q))} {S} "
                        f"({'total' if b.drainage is Drainage.UNDRAINED else 'effective'} stress)"),
        ('<span class="g">&gamma;</span>e (self-weight term)', f"{_f(u.from_si_unit_weight(b.gamma_e))} "
                                        f"{u.label('unit_weight')}"),
        ("Groundwater", _esc(b.gw_note)),
        ("Effective dimensions", f"B&prime; = {_f(u.from_si_length(b.b_eff))} {L}, "
                                 f"L&prime; = {_f(u.from_si_length(b.l_eff))} {L}"),
    ]:
        p.append(f"<dt>{k}</dt><dd>{v}</dd>")
    p.append("</dl>")

    p.append(f'<div class="tw"><table><thead><tr><th>Term</th><th>N</th><th>shape s</th>'
             f'<th>depth d</th><th>incl. i</th><th>Contribution ({S})</th></tr></thead><tbody>')
    for nm, n, s_, dd, i_, t in [
        ("Cohesion", b.factors.nc, b.sc, b.dc, b.ic, b.term_cohesion),
        ("Surcharge", b.factors.nq, b.sq, b.dq, b.iq, b.term_surcharge),
        ("Self weight", b.factors.ngamma, b.sg, b.dg, b.ig, b.term_self_weight),
    ]:
        p.append(f'<tr><td class="t">{nm}</td><td>{n:.3f}</td>'
                 f"<td>{s_:.3f}</td>"
                 f"<td>{dd:.3f}</td><td>{i_:.3f}</td><td>{u.from_si_stress(t):,.2f}</td></tr>")
    p.append(f'</tbody><tfoot><tr><td colspan="5">q_ult (gross ultimate)</td>'
             f'<td>{u.from_si_stress(b.q_ult):,.2f}</td></tr></tfoot></table></div>')

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
            ('Net pressure <span class="g">&Delta;q</span>', f"{_f(u.from_si_stress(st.net_pressure))} {S}"),
            ('<span class="g">&sigma;&prime;v0</span> at founding level', f"{_f(u.from_si_stress(st.sigma_v0_base))} {S}"),
            ("C1 (embedment)", f"{st.c1:.4f}"),
            (f"C2 (creep, {project.criteria.time_years:g} yr)", f"{st.c2:.4f}"),
            ("Izp (peak strain influence)", f"{st.izp:.4f}"),
            ("Influence depth", f"{st.zmax_over_b:g}B"),
        ]:
            p.append(f"<dt>{k}</dt><dd>{v}</dd>")
        p.append("</dl>")

        rows = [s for s in st.sublayers if abs(s.settlement) > 1e-9]
        if rows:
            p.append(f'<div class="tw"><table><thead><tr><th>From ({L})</th><th>To ({L})</th>'
                     f'<th>Layer</th><th>Method</th><th>Settlement ({SL})</th>'
                     f'</tr></thead><tbody>')
            for s in rows:
                p.append(f"<tr><td>{u.from_si_length(s.z_top):.2f}</td>"
                         f"<td>{u.from_si_length(s.z_bot):.2f}</td>"
                         f'<td class="t">{_esc(s.layer_name)}</td><td class="t">{_esc(s.method)}</td>'
                         f"<td>{u.from_si_settlement(s.settlement):.4f}</td></tr>")
            p.append(f'</tbody><tfoot><tr><td colspan="4">Total</td>'
                     f'<td>{u.from_si_settlement(st.total):.4f}</td></tr></tfoot></table></div>')

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


def _schedule_sheet(results: list[ProjectResult], project: Project,
                    sheet: int | None = None, total: int | None = None) -> str:
    u = project.units
    L, S = u.label("length"), u.label("stress")
    SL = u.label("small_length")
    vol = "ft&sup3;" if u.system.value == "US" else "m&sup3;"
    p = ['<section class="sheet">', _header(project, "Footing schedule", sheet, total)]

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

    def th(label: str, unit: str | None = None) -> str:
        return (f'<th>{label}<span class="u">({unit})</span></th>' if unit
                else f'<th>{label}</th>')

    p.append('<div class="tw"><table><thead><tr>'
             + th("Mark") + th("B", L) + th("L", L) + th("t", L) + th("Df", L)
             + th("q applied", S) + th("q allow", S) + th("Settl.", SL)
             + th("Governs") + th("Status")
             + '</tr></thead><tbody>')
    for sheet_no, r in enumerate(results, start=2):
        d = r.design
        if d.bearing is None:
            p.append(f'<tr><td>{_esc(d.mark)}</td>'
                     f'<td colspan="8" class="t">No spread footing satisfies the '
                     f'criteria &mdash; see sheet {sheet_no}</td>'
                     f'<td class="t"><span class="util bad">FAIL</span></td></tr>')
            continue
        status = ('<span class="util ok">OK</span>' if d.ok
                  else '<span class="util bad">FAIL</span>')
        p.append(f"<tr><td>{_esc(d.mark)}</td><td>{_f(r.b)}</td><td>{_f(r.l)}</td>"
                 f"<td>{_f(r.thickness)}</td><td>{_f(r.df)}</td>"
                 f"<td>{_f(r.q_applied)}</td><td>{_f(r.q_allow)}</td>"
                 f"<td>{r.settlement:.3f}</td>"
                 f'<td class="t">{_esc(d.governing)}</td>'
                 f'<td class="t">{status}</td></tr>')
    p.append("</tbody></table></div>")

    p.append("<h2>Soil profile</h2>")
    p.append(f'<div class="tw"><table><thead><tr><th>Depth ({L})</th><th>Layer</th><th>Analysis</th>'
             f'<th><span class="g">&gamma;</span><span class="u">({u.label("unit_weight")})</span></th>'
             f'<th><span class="g">&phi;&prime;</span><span class="u">(&deg;)</span></th>'
             f'<th>c / su<span class="u">({S})</span></th></tr></thead><tbody>')
    prof = project.profile
    for i, layer in enumerate(prof.layers):
        p.append(f"<tr><td>{u.from_si_length(prof.layer_top(i)):.2f} &ndash; "
                 f"{u.from_si_length(prof.layer_bottom(i)):.2f}</td>"
                 f'<td class="t">{_esc(layer.name)}</td><td class="t">{layer.drainage.value}</td>'
                 f"<td>{u.from_si_unit_weight(layer.gamma):.1f}</td>"
                 f"<td>{layer.phi:.1f}</td>"
                 f"<td>{u.from_si_stress(layer.cohesion):.2f}</td></tr>")
    p.append("</tbody></table></div>")
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
        ('N<span class="g">&gamma;</span> method', _METHOD_LABEL.get(c.bearing_method.value, c.bearing_method.value)),
        ("Design life (creep)", f"{c.time_years:g} yr"),
    ]:
        p.append(f"<dt>{k}</dt><dd>{v}</dd>")
    p.append("</dl>")

    p.append('<h2>Contents</h2><div class="tw"><table class="toc"><tbody>')
    for r in results:
        p.append(f'<tr><td><a href="#f-{_esc(r.design.mark)}">Footing '
                 f'{_esc(r.design.mark)}</a></td>'
                 f'<td>{_esc(r.design.governing)}</td></tr>')
    p.append("</tbody></table></div></section>")
    return "".join(p)


def calc_package_html(results: list[ProjectResult], project: Project) -> str:
    """Full calculation package: schedule sheet followed by one sheet per
    footing. Print to PDF from any browser."""
    total = len(results) + 1
    body = [_schedule_sheet(results, project, 1, total)]
    body += [_footing_sheet(r, project, i, total)
             for i, r in enumerate(results, start=2)]
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{_esc(project.name)} - Footing calculations</title>"
        "<link rel='preconnect' href='https://fonts.googleapis.com'>"
        "<link rel='preconnect' href='https://fonts.gstatic.com' crossorigin>"
        "<link rel='stylesheet' href='https://fonts.googleapis.com/css2?"
        "family=Barlow+Condensed:wght@500;600&family=IBM+Plex+Mono:wght@400;600"
        "&family=Source+Sans+3:wght@400;600&display=swap'>"
        f"<style>{_CSS}</style></head><body>{''.join(body)}</body></html>"
    )
