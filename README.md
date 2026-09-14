# Burh

Batch shallow foundation design. Sizes spread footings against **bearing
capacity and settlement together**, reports which limit state governs, and
emits an auditable calculation package.

```
$ burh design examples/warehouse.json --html calcs.html --csv schedule.csv

Riverside Distribution Center - Phase 2  -  12 footing(s), units US
----------------------------------------------------------------------------------------
MARK             B       L       t     q_app     q_all    settl           GOVERNS
              (ft)    (ft)    (ft)     (ksf)     (ksf)     (in)
----------------------------------------------------------------------------------------
F-1           3.75    3.75    0.98      4.54      4.88    0.944        Settlement   OK
F-4           8.50    8.50    1.80      2.37      5.74    0.957        Settlement   OK
F-10         15.50   15.50    3.44      1.67      3.07    0.995        Settlement   OK
F-11                                   -- no valid design --                FAIL
```

**[Try it in your browser →](https://claude.ai/code/artifact/8890f5b7-1193-44a0-9c3d-25424befd7dd)**
— single-footing checker, US and Canadian codes, runs entirely client-side.
**[Sample calculation package →](https://claude.ai/code/artifact/edcbafbb-cd5a-4798-a406-ef83f4f6a1c2)**
— the batch output: a schedule sheet plus the full derivation for twelve footings.

## Why

On that job **settlement governs every single footing, and bearing
utilisation runs as low as 0.44.** A tool that checks bearing capacity alone
would have undersized all ten.

That is the normal situation on granular soil, and it is why the two checks
belong in one pass. The other half of the problem is throughput: GUI tools
size footings one at a time, so a 60-column job is a day of clicking and a
day of re-clicking when the loads change.

## Install

```bash
pip install -e .
```

Python 3.10+. **The engine has zero runtime dependencies** — pure standard
library. That is deliberate: it installs behind corporate IT policy without a
dependency review and runs inside constrained embedded Python environments.

## Use

```bash
burh design project.json --html calcs.html --csv schedule.csv
burh design project.json --sheet F-7          # full calculation for one footing
```

Exit status is `0` when every footing passes, `1` when any fails, `2` on bad
input — so it drops into a checking script.

Column loads come from a CSV exported from the analysis model. Header
spellings from different packages are accepted (`Mark`/`ID`/`Column`,
`Dead`/`DL`/`D`, …). An **unrecognised** column is a hard error rather than a
silent drop, because a silently ignored load is the worst failure this tool
could have.

```csv
Mark,Dead,Live,Shear,Mb
F-1,42,18,0,0
F-7,140,70,12,35
```

Or drive it from Python:

```python
from burh import Project

p = Project("Warehouse", units="US")          # or units="SI"
p.add_layer("Sandy fill",   thickness=4,  gamma=115, spt_n=15)
p.add_layer("Stiff clay",   thickness=11, gamma=126, drainage="undrained",
            cohesion=3.0, cc=0.18, cr=0.028, e0=0.70, ocr=4.0)
p.set_water_table(12)
p.infer_phi_from_spt()                        # records its own provenance
p.add_column("F-1", dead=120, live=60)

for r in p.run():
    print(r.design.mark, r.b, r.design.governing)
```

## What it computes

| | Method |
|---|---|
| Bearing capacity | Vesić general equation; Meyerhof and Hansen N-γ selectable |
| Shape / depth / inclination | Vesić, on Meyerhof effective area |
| Eccentricity | Effective area B′ = B − 2e; kern violation flagged |
| Groundwater | Three-case equivalent unit weight; effective vs total surcharge |
| Stress distribution | Newmark integration of the Boussinesq point solution |
| Settlement, granular | Schmertmann (1978) strain influence factor |
| Settlement, cohesive | Terzaghi 1-D consolidation with OCR / recompression |
| SPT | N60, (N1)60; φ′ and Es correlations with citations |
| Design frameworks | US allowable stress design, Canadian limit states design |

Units are handled at the API boundary only; **every internal calculation is
in one consistent SI base set**, so no mixed-unit arithmetic is reachable.

## US and Canadian codes

These are not the same calculation with a different coefficient — they compare
different quantities:

| | US | Canada |
|---|---|---|
| Framework | Allowable stress design | Limit states design |
| ULS check | q<sub>ult</sub> / FS ≥ **service** pressure | Φ · q<sub>ult</sub> ≥ **factored** pressure |
| Factor | FS = 3.0 (customary practice, *not* an IBC-prescribed number) | Φ = 0.5 (CFEM) |
| Load cases | D + L unfactored | max(1.4D, 1.25D + 1.5L), NBC 2020 Table 4.1.3.2 |
| Settlement | service load | service load — **same in both** |

Mixing the two — a factored load against an allowable capacity, or the reverse —
is roughly a 40% error in whichever direction is worse, so the framework is
carried explicitly on the criteria object and never inferred. The footing's own
self-weight and backfill take the dead-load factor of the same combination, not
a separate one.

Because both sit on one engine, they can be compared directly. The tool reports
the **equivalent global factor of safety** for an LSD check (λ/Φ, where λ is the
factored/service pressure ratio), which lands around **2.6** for a typical
dead-plus-live column — so Canadian LSD runs roughly 12–15% less conservative on
bearing than the customary US FS = 3.0.

Neither path verifies code compliance. Provincial amendments (OBC, BC, Alberta,
Quebec) and the project geotechnical report take precedence over every default.

## It tells you when it is wrong

The engine is opinionated about its own limits, because a number without its
caveats cannot be sealed:

- **Strong-over-weak layering** in the failure zone is flagged as
  unconservative, with a pointer to the punching-shear check it does *not*
  perform.
- **Borings that do not reach** the failure zone or the settlement summation
  depth are flagged as extrapolated.
- **Correlated parameters** carry their citation and the fact they are
  estimates, and appear in an "Inferred parameters" section of the package.
- **Non-monotonic settlement** — where a *wider* footing settles *more*
  because its stress bulb reaches a deeper soft stratum — is detected and
  called out, because "smallest passing size" is then not a safe envelope.
- **When no footing works**, it probes past the search range and states a
  fact instead of extrapolating:

  > Settlement governs: 467.6 mm against a limit of 25.0 mm, and 90% of it is
  > consolidation in 'Deep soft clay'. Probing out to 24.00 m found no working
  > size. The least settlement at ANY width tried is 316.2 mm at B = 1.00 m…
  > Widening cannot solve this: a wider footing pushes its stress bulb deeper
  > into the compressible stratum, cancelling the lower contact pressure.

## Validation

`python -m pytest` — 198 tests. Numeric expectations are published values or
hand calculations reproduced in the test body, **never snapshots of the
code's own output**:

- Vesić, Meyerhof and Hansen N-factors against published tables, φ = 0…45°.
- Newmark influence factors against **direct 2-D numerical integration of the
  Boussinesq point solution** — agreement to ~1e-9. (This caught that two
  values I had recalled from a table were the table's rounding, not the code.)
- The Schmertmann summation against its **closed-form analytic integral**
  (∫Iz dz = B(0.025 + Izp) for a square footing) — exact to machine precision.
- The lb/ft³ → kN/m³ constant derived independently through mass (pound → kg,
  × g) rather than through the force path the implementation uses.
- Degenerate cases: φ = 0 strip footing → q_ult → 5.14·su (Prandtl);
  Df = 0 → all depth factors unity; N-γ → 0 at φ = 0.

The browser engine is a separate implementation, so it is checked against the
Python one rather than trusted:

```
$ python web/gencases.py 500 && node web/crossvalidate.mjs
cases:            500
scalars compared: 7492
worst deviation:  4.024e-15 on "ngamma"
PASS - the browser engine matches the Python engine on every case.
```

Randomised layered profiles, both frameworks, all three N-γ methods, water
tables above and below the base, eccentric and inclined loads. Any divergence
beyond 1e-9 on a scalar, or *any* disagreement on a discrete outcome (solved /
governing criterion / load combination), fails the run.

## Scope — read this before using it

Bearing capacity and settlement are evaluated at **service (unfactored)**
load. That is correct for both checks and is enforced by the API naming.

**Not covered.** Reinforced concrete design — flexure, one-way and two-way
shear, development — is out of scope and must be done separately. Footing
thickness is a self-weight estimate only, *not* a structural design. Also
absent: mats and combined footings, deep foundations, Meyerhof & Hanna
punching shear through a strong-over-weak profile, seismic and liquefaction,
expansive and collapsible soils, rate of consolidation.

Correlated soil parameters are estimates with roughly a factor-of-two scatter
and do not replace laboratory or in-situ testing. **Output requires review
and sealing by a licensed engineer.** The engineer of record is responsible
for the design.

## Layout

```
burh/units.py       unit systems; conversion only at the API boundary
burh/soil.py        layers, effective stress, SPT corrections and correlations
burh/stress.py      Boussinesq / Newmark and the 2:1 approximation
burh/bearing.py     bearing capacity, all factors retained for the calc sheet
burh/settlement.py  Schmertmann and consolidation
burh/design.py      the sizing solver and failure diagnosis
burh/api.py         unit-aware public API
burh/report.py      text and HTML calculation packages
burh/batch.py       CSV / JSON in and out
burh/cli.py         command line
burh/codes.py       US ASD and Canadian LSD frameworks

web/engine.js       browser port of the engine (single source)
web/tool.html       the online tool; engine inlined at build time
web/build.py        inlines engine.js into tool.html
web/gencases.py     generates randomised cases from the Python engine
web/crossvalidate.mjs  replays them through the browser engine and compares
```

Build the page with `python web/build.py footing-check.html`. The page and the
cross-validator share one engine file, so the shipped page cannot drift from
the one that was validated.
