# Commercial case

Cold version. Every number below that I could not verify from primary sources
is labelled as an assumption, and the ones that need your contacts to confirm
are listed at the end.

## What is being sold, and to whom

A **batch footing design and calculation-package tool** sold seat-wise to
structural engineering firms that design buildings on spread footings —
warehouses, light industrial, retail, low-rise commercial, schools.

Beachhead is **structural**, not geotechnical. The geotechnical engineer
writes one bearing recommendation per site; the structural engineer sizes
sixty footings and re-sizes them twice when the loads change. The repetitive
volume work — and therefore the pain — sits on the structural side.

## The wedge

Three things, in order of how hard they are to copy:

1. **Batch.** ENERCALC, RISAFoundation and GEO5 are GUI tools that size
   footings one at a time. A load revision means re-entering the job.
2. **Both limit states in one pass.** In the shipped example, settlement
   governs all ten viable footings while bearing utilisation runs as low as
   0.44. Bearing-only sizing undersizes every one of them. Many in-house
   spreadsheets check bearing and hand-wave settlement.
3. **An auditable calculation package.** Every factor and intermediate is on
   the sheet. This is also the liability mitigation (below) — it converts a
   black box into something a reviewer can check.

The real competitor is **Excel**, not the commercial packages. Every firm has
a spreadsheet that one person wrote, nobody has verified, and everyone is
slightly afraid of.

## ROI arithmetic

Assumptions, all to be validated against your contacts:

| | | |
|---|---|---|
| A1 | Billing rate, structural EIT/PE | $165/hr |
| A2 | Time per footing in a GUI tool, incl. data entry, check, transcription | 0.25 hr |
| A3 | Footings per job | 60 |
| A4 | Full re-runs per job from load revisions | 2 (3 passes total) |
| A5 | Qualifying jobs per firm per year | 15 |

```
Manual:  60 footings x 0.25 hr x 3 passes                        = 45.0 hr
Burh:    first pass 2 hr setup + 2 hr review                     =  4.0 hr
         2 re-runs x (0.25 hr re-run + 1 hr review)              =  2.5 hr
                                                                   -------
                                                                    6.5 hr
Saved per job        38.5 hr  x  $165                            = $6,350
Saved per firm-year  15 jobs                                     = $95,000
```

At **$1,500/seat/year x 6 seats = $9,000/year**, that is roughly 10x. The
number that matters is not 10x, it is that **the ratio survives being wrong
by a factor of three.** Halve the time saving and quarter the job count and
it is still ~2.5x. That robustness is what makes it sellable; the headline
figure is not.

## Pricing

- **$1,500/seat/year**, floor of 3 seats. Sits below the commercial packages,
  above the "is this serious?" line.
- **$250/project** for firms under ~8 engineers, who will not commit to
  seats.
- Perpetual licences: no. Recurring revenue is the whole point.

Do not discount early. In AEC, price is read as a quality signal, and the
first ten customers set the reference price for everyone they talk to.

## Go to market: free tool first

Lead with the **free single-footing checker**, not with seat sales. It generates
the warm introductions this plan depends on, it validates demand before any
sales motion exists, and because it runs entirely client-side you can say
*"your soil data never leaves your browser"* — which removes the objection that
kills most online engineering tools. Hosting cost is zero; there is no backend.

The upgrade path is honest and obvious from using it: the free tool does one
footing, the paid product does the whole job — batch CSV in, footing schedule
and sealed-ready calculation package out.

Sequence:

1. **Free tool, US and Canadian codes.** Shipped.
2. **Put it in front of the contacts.** The ask is not "buy this", it is "run a
   job you already sealed through this and tell me where it disagrees." That
   either validates the engine against real practice or finds the gap that
   matters, and it costs them twenty minutes.
3. **Instrument nothing at first.** Resist adding analytics or an email gate to
   a tool whose entire trust argument is that it sends nothing anywhere. Count
   conversations, not sessions.
4. **Only then** build the paid batch tier, priced per the section above.

Adding Canada roughly doubles the addressable market for the same engine, and
the limit-states framework is the same work Eurocode 7 will need later — the
partial-factor machinery is now in place, so item 3 of the roadmap is cheaper
than it was.

## Revenue path

| Firms | Seats @ 6 | ARR |
|---|---|---|
| 5 | 30 | $45,000 |
| 10 | 60 | $90,000 |
| 30 | 180 | $270,000 |
| 60 | 360 | $540,000 |

With warm introductions, 3–5 firms in year one is a realistic target; cold
outbound into AEC is close to useless. **Be honest about the ceiling: this is
a niche with a few thousand plausible buyers worldwide.** It is not a
venture-scale business. It is a plausible $250k–$1M/year business with very
low cost of goods, which is a better outcome than most software.

## Risks, ranked

1. **Professional liability. This is the big one.** Selling software that
   produces engineering results creates exposure that a normal SaaS does not
   have. Mitigations: liability capped at fees paid in the EULA; explicit
   "engineer of record is responsible" language on every output (already
   implemented); errors-and-omissions cover; and the calculation transparency,
   which makes output checkable rather than authoritative. **Talk to an
   attorney and an insurance broker before the first sale.** Do not treat
   this section as legal advice — it is a flag, not a plan.
2. **Validation burden.** Firms will benchmark against their existing tools
   before adopting, and rightly so. Budget weeks, not days. The 173-test suite
   validated against published tables, closed-form integrals and first
   principles is the asset that shortens this — lead with it.
3. **Excel incumbency.** Sunk cost and familiarity. Counter with the batch
   workflow and the settlement check, not with feature lists.
4. **Scope gaps as objections.** See the roadmap; the concrete design gap is
   the one that will come up in every demo.
5. **Buyer ambiguity.** If a firm's geotechnical consultant already supplies
   an allowable bearing pressure, part of the value evaporates. Qualify for
   this on the first call.

## Roadmap, ordered by sales objection

1. **ACI 318 flexure and two-way shear.** Biggest gap. Today footing
   thickness is a self-weight estimate, not a design, so the schedule is
   incomplete and the engineer still opens another tool. Needs factored
   (LRFD) loads alongside the service loads — deliberately not bolted on,
   because mixing ASD and LRFD load cases is exactly the error class this
   engine is built to prevent.
2. **Meyerhof & Hanna punching shear** for strong-over-weak profiles. The
   engine currently flags this case as unconservative and declines to compute
   it. Closing it removes a caveat from a common profile.
3. **Eurocode 7 partial factors** (Design Approaches 1/2/3). Required for any
   European sale. This is a limit-state framework fork, not a coefficient
   change — scope it properly before promising it.
4. **Mats and combined footings.** The natural escalation when spread
   footings fail, which the tool already diagnoses.
5. **Revit / Dynamo schedule export.** Closes the loop to the drawing set and
   is the feature that makes it sticky.

## What I need from you before going further

These change the product, not just the pitch:

1. **Code basis your contacts work to.** IBC/ACI with ASD bearing, AASHTO
   LRFD, or Eurocode 7? Eurocode is a significant fork (item 3 above), not a
   setting.
2. **Structural or geotechnical firms?** Determines the beachhead and whether
   the bearing-capacity engine is the product or merely a check.
3. **Typical footings per job** at those firms. The whole ROI case rests on
   A3; if their jobs are 12 footings rather than 60, the economics change and
   per-project pricing becomes the only viable model.
4. **What they use today** — ENERCALC, RISA, GEO5, or a spreadsheet — and, if
   a commercial package, **what they actually pay.** I did not have verified
   current pricing when setting the $1,500 figure above; treat it as a
   placeholder anchored to my understanding of the category, not a
   researched number.
5. **Whether any of them will run a benchmark** against a job they have
   already designed and sealed. That is the single highest-value next step:
   it either validates the engine against real practice or finds the gap that
   matters, and it costs nothing but a few hours.
