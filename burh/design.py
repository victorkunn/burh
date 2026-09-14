"""Footing sizing solver.

Sizes the smallest footing on a practical dimension increment that satisfies
every serviceability and stability limit state, and reports WHICH limit state
governs. That last part is the point: an engineer who knows settlement governs
will specify ground improvement; an engineer who only sees a number will pour
more concrete.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .bearing import (
    BearingMethod,
    BearingResult,
    averaged_properties,
    sliding_resistance,
    ultimate_bearing_capacity,
)
from .settlement import SettlementResult, settlement
from .soil import SoilProfile
from .units import Units

GAMMA_CONCRETE = 23.6  # kN/m3 (150 pcf)


@dataclass
class DesignCriteria:
    """Limit states the footing must satisfy. All internal SI."""

    factor_of_safety_bearing: float = 3.0
    factor_of_safety_sliding: float = 1.5
    factor_of_safety_overturning: float = 2.0
    settlement_limit: float = 0.025          # 25 mm ~ 1 in
    differential_ratio_limit: float = 1 / 500  # angular distortion
    min_width: float = 0.60
    max_width: float = 6.00
    size_increment: float = 0.05
    aspect_ratio: float = 1.0                # L/B; 1.0 = square
    min_embedment: float = 0.45              # frost / disturbance
    bearing_method: BearingMethod = BearingMethod.VESIC
    influence_depth_ratio: float = 1.5
    time_years: float = 50.0

    def __post_init__(self) -> None:
        if self.min_width <= 0 or self.max_width <= self.min_width:
            raise ValueError("Require 0 < min_width < max_width.")
        if self.size_increment <= 0:
            raise ValueError("size_increment must be > 0.")
        if self.aspect_ratio < 1.0:
            raise ValueError(
                "aspect_ratio is L/B and must be >= 1.0 (B is the short side)."
            )
        if self.settlement_limit <= 0:
            raise ValueError("settlement_limit must be > 0.")


@dataclass
class ColumnLoad:
    """Unfactored SERVICE loads at the top of the footing.

    Bearing capacity and settlement are both service-level (ASD) checks.
    Passing factored (LRFD) loads here will oversize every footing on the job
    by roughly 1.5x, so the name is deliberately explicit.
    """

    mark: str
    dead: float
    live: float = 0.0
    horizontal: float = 0.0
    moment_b: float = 0.0
    moment_l: float = 0.0
    column_b: float = 0.40
    column_l: float = 0.40
    embedment: float | None = None

    @property
    def service_vertical(self) -> float:
        return self.dead + self.live

    def __post_init__(self) -> None:
        if self.dead < 0 or self.live < 0:
            raise ValueError(f"{self.mark}: loads must be >= 0.")
        if self.service_vertical <= 0:
            raise ValueError(f"{self.mark}: total service vertical load must be > 0.")


@dataclass
class FootingDesign:
    """Result of sizing one footing."""

    mark: str
    ok: bool
    b: float = 0.0
    l: float = 0.0
    df: float = 0.0
    thickness: float = 0.0
    governing: str = ""
    q_applied_gross: float = 0.0
    q_allow_gross: float = 0.0
    bearing_utilisation: float = 0.0
    total_settlement: float = 0.0
    settlement_utilisation: float = 0.0
    sliding_fs: float | None = None
    concrete_volume: float = 0.0
    bearing: BearingResult | None = None
    settlement_result: SettlementResult | None = None
    warnings: list[str] = field(default_factory=list)
    message: str = ""


def estimate_thickness(b: float, column_b: float) -> float:
    """Placeholder footing thickness [m] used ONLY for self-weight.

    This is NOT a structural design. Final thickness comes from ACI 318
    one-way and two-way shear, which is outside this engine's scope. The
    estimate is deliberately generous so self-weight is not understated.
    """
    return max(0.30, math.ceil(((b - column_b) / 2.0 * 0.5) / 0.05) * 0.05)


def gross_pressure(v_service: float, b: float, l: float, df: float,
                   thickness: float, gamma_soil: float) -> float:
    """Gross bearing pressure at founding level [kPa], including the weight of
    the footing itself and the soil backfill sitting on top of it."""
    area = b * l
    w_footing = thickness * GAMMA_CONCRETE
    w_soil = max(0.0, df - thickness) * gamma_soil
    return v_service / area + w_footing + w_soil


@dataclass
class ProbeResult:
    """Outcome of searching beyond ``max_width`` after the main scan failed."""

    solution_b: float | None = None       # smallest passing width found, if any
    best_b: float = 0.0                   # width giving the least settlement
    best_settlement: float = 0.0
    max_probed: float = 0.0


def design_footing(
    profile: SoilProfile,
    load: ColumnLoad,
    criteria: DesignCriteria | None = None,
    units: Units | None = None,
) -> FootingDesign:
    """Size a single footing.

    All arguments and returned values are internal SI. ``units`` is used only
    to render diagnostic messages in the engineer's own units; it never
    affects the computation.
    """
    c = criteria or DesignCriteria()
    df = load.embedment if load.embedment is not None else c.min_embedment
    if df < c.min_embedment:
        raise ValueError(
            f"{load.mark}: embedment {df:.2f} m is less than the required minimum "
            f"{c.min_embedment:.2f} m (frost depth / disturbed zone)."
        )

    v = load.service_vertical
    props = averaged_properties(profile, df, c.min_width, c.influence_depth_ratio)
    gamma_soil = props.gamma_moist

    def evaluate(b: float) -> tuple[FootingDesign | None, str]:
        """Check one trial width against every limit state.

        Returns ``(design, "")`` or ``(None, reason)`` when the geometry is
        rejected outright (for example the footing slides before it bears).
        """
        l = b * c.aspect_ratio
        t = estimate_thickness(b, load.column_b)
        q_gross = gross_pressure(v, b, l, df, t, gamma_soil)
        # Total load delivered to the soil: eccentricity, sliding and
        # overturning all resist with the full weight, not just the column load.
        v_total = q_gross * b * l

        try:
            br = ultimate_bearing_capacity(
                profile, b=b, l=l, df=df, v=v_total, h=load.horizontal,
                m_b=load.moment_b, m_l=load.moment_l,
                factor_of_safety=c.factor_of_safety_bearing,
                method=c.bearing_method,
                influence_depth_ratio=c.influence_depth_ratio,
            )
        except ValueError as exc:
            return None, str(exc)

        bearing_util = q_gross / br.q_allow if br.q_allow > 0 else math.inf
        bearing_ok = q_gross <= br.q_allow

        st = settlement(profile, b=b, l=l, df=df, q_gross=q_gross,
                        time_years=c.time_years)
        settle_util = st.total / c.settlement_limit
        settle_ok = st.total <= c.settlement_limit

        sliding_fs = None
        sliding_ok = True
        if load.horizontal > 0:
            resistance = sliding_resistance(
                v_total, br.b_eff, br.l_eff, br.phi, br.cohesion
            )
            sliding_fs = resistance / load.horizontal
            sliding_ok = sliding_fs >= c.factor_of_safety_sliding

        overturning_ok = True
        if load.moment_b or load.moment_l:
            m_resisting = v_total * b / 2.0
            m_overturning = abs(load.moment_b) + load.horizontal * df
            if m_overturning > 0:
                overturning_ok = (
                    m_resisting / m_overturning >= c.factor_of_safety_overturning
                )

        governing = ("Bearing capacity" if bearing_util >= settle_util
                     else "Settlement")
        if not sliding_ok:
            governing = "Sliding"
        elif not overturning_ok:
            governing = "Overturning"

        return FootingDesign(
            mark=load.mark,
            ok=bearing_ok and settle_ok and sliding_ok and overturning_ok,
            b=b, l=l, df=df, thickness=t,
            governing=governing,
            q_applied_gross=q_gross,
            q_allow_gross=br.q_allow,
            bearing_utilisation=bearing_util,
            total_settlement=st.total,
            settlement_utilisation=settle_util,
            sliding_fs=sliding_fs,
            concrete_volume=b * l * t,
            bearing=br,
            settlement_result=st,
            warnings=list(br.warnings) + list(st.warnings),
        ), ""

    # -- main scan: smallest size on the increment grid that satisfies all ---
    n_steps = int(math.floor((c.max_width - c.min_width) / c.size_increment)) + 1
    trials: list[tuple[float, FootingDesign]] = []
    first_ok: FootingDesign | None = None
    last_fail = ""

    for i in range(n_steps):
        b = c.min_width + i * c.size_increment
        if b > c.max_width + 1e-9:
            break
        d, reason = evaluate(b)
        if d is None:
            last_fail = reason
            continue
        trials.append((b, d))
        if d.ok:
            first_ok = d
            break

    if first_ok is None:
        probe = _probe_beyond(evaluate, c, trials)
        return FootingDesign(
            mark=load.mark, ok=False, df=df, governing="NO SOLUTION",
            message=_diagnose_failure(load, c, trials, last_fail, units, probe),
        )

    _check_monotonic(evaluate, c, first_ok)
    return first_ok


def _probe_beyond(evaluate, c: DesignCriteria,
                  trials: list[tuple[float, FootingDesign]]) -> ProbeResult:
    """Search past ``max_width`` so the failure message can state a fact
    rather than an extrapolation.

    Settlement is not monotonic in width on a layered profile, so projecting a
    local power law past the end of the search range is unreliable - it was,
    in testing, wrong by 20%. Probing costs a handful of evaluations and
    answers the engineer's actual question: does ANY spread footing work here?
    """
    result = ProbeResult(best_settlement=math.inf)
    # Seed from the sizes already tried, so "the least settlement found" is the
    # minimum over EVERYTHING evaluated. Settlement is not monotonic in width on
    # a layered profile, so the probed sizes are not necessarily the best ones.
    for b, d in trials:
        if d.total_settlement < result.best_settlement:
            result.best_settlement = d.total_settlement
            result.best_b = b
    result.max_probed = c.max_width
    for factor in (1.25, 1.5, 2.0, 3.0):
        b = c.max_width * factor
        result.max_probed = b
        d, _ = evaluate(b)
        if d is None:
            continue
        if d.total_settlement < result.best_settlement:
            result.best_settlement = d.total_settlement
            result.best_b = b
        if d.ok and result.solution_b is None:
            result.solution_b = b
            break
    if math.isinf(result.best_settlement):
        result.best_settlement = 0.0
    return result


def _check_monotonic(evaluate, c: DesignCriteria, result: FootingDesign) -> None:
    """Verify that making the footing larger does not make it worse.

    On layered profiles settlement is not guaranteed to decrease with width:
    a wider footing sheds less contact pressure but stresses a deeper, softer
    stratum. If that happens the engineer must be told, because the 'smallest
    passing size' is then not a safe design envelope.
    """
    for step in (1, 2, 4, 8):
        b = result.b + step * c.size_increment
        if b > c.max_width:
            break
        d, _ = evaluate(b)
        if d is None:
            continue
        if d.total_settlement > c.settlement_limit:
            result.warnings.append(
                f"Non-monotonic settlement: enlarging the footing to B = {b:.2f} m "
                f"INCREASES settlement to {d.total_settlement * 1000:.1f} mm, exceeding "
                f"the {c.settlement_limit * 1000:.0f} mm limit. A deeper compressible "
                "stratum is being stressed. Do not size this footing by inspection."
            )
            break


def _diagnose_failure(load: ColumnLoad, c: DesignCriteria,
                      trials: list[tuple[float, FootingDesign]],
                      last_fail: str, units: Units | None = None,
                      probe: "ProbeResult | None" = None) -> str:
    """Explain WHY no footing works, and whether widening could ever fix it.

    'Consider a mat foundation' is not advice. The useful question is whether
    the controlling quantity is still improving with width or has gone
    asymptotic - because if consolidation in a deep compressible stratum is
    governing, a wider footing reaches deeper and buys almost nothing. That
    distinction decides between 'increase max_width' and 'stop designing
    spread footings'.

    The comparison is made over the LAST QUARTILE of the search. Comparing
    against the smallest size tried would average in the steep early region
    and hide a plateau.
    """
    u = units or Units("SI")
    L, SL = u.label("length"), u.label("small_length")

    def ln(v: float) -> str:
        return f"{u.from_si_length(v):.2f} {L}"

    def st_(v: float) -> str:
        return f"{u.from_si_settlement(v):.3f} {SL}"

    head = (
        f"No footing between {ln(c.min_width)} and {ln(c.max_width)} satisfies "
        f"the criteria for {load.mark}."
    )
    if not trials:
        return f"{head} Solver could not evaluate any trial size. {last_fail}".strip()

    worst = trials[-1][1]
    parts = [
        head,
        f"At the largest size tried (B = {ln(worst.b)}) bearing utilisation is "
        f"{worst.bearing_utilisation:.2f} and settlement utilisation is "
        f"{worst.settlement_utilisation:.2f}.",
    ]

    if worst.settlement_utilisation > 1.0:
        # Physically grounded test: the log-log slope d(ln S)/d(ln B).
        # Schmertmann on a uniform granular profile gives S ~ q*B ~ P/B, so
        # the slope sits near -1. When consolidation in a deep compressible
        # stratum dominates, widening pushes the stress bulb deeper and the
        # slope flattens toward 0. Measured values: uniform sand -1.7,
        # stiff clay lens -1.3, deep normally-consolidated clay -0.09.
        # A threshold of -0.4 separates these cleanly and, being a log slope,
        # it is independent of units and of the absolute footing size.
        ref = min(trials, key=lambda t: abs(t[0] - 0.6 * worst.b))[1]
        span = math.log(worst.b / ref.b) if ref.b > 0 and worst.b > ref.b else 0.0
        slope = None
        if span >= 0.15 and ref.total_settlement > 0 and worst.total_settlement > 0:
            slope = math.log(worst.total_settlement / ref.total_settlement) / span

        sr = worst.settlement_result
        share = sr.consolidation / sr.total if sr and sr.total > 0 else 0.0
        if share > 0.5 and sr is not None:
            by_layer: dict[str, float] = {}
            for sub in sr.sublayers:
                if sub.method == "Consolidation":
                    by_layer[sub.layer_name] = by_layer.get(sub.layer_name, 0.0) + sub.settlement
            culprit = max(by_layer, key=by_layer.get) if by_layer else "a cohesive stratum"
            parts.append(
                f"Settlement governs: {st_(worst.total_settlement)} against a limit of "
                f"{st_(c.settlement_limit)}, and {share * 100:.0f}% of it is "
                f"consolidation in {culprit!r}."
            )
        else:
            parts.append(
                f"Settlement governs: {st_(worst.total_settlement)} against a limit of "
                f"{st_(c.settlement_limit)}."
            )

        if probe is not None and probe.solution_b is not None:
            parts.append(
                f"Probing past the search range: a footing DOES work at "
                f"B = {ln(probe.solution_b)}. Raise max_width to at least that and "
                "re-run, then weigh the extra excavation and concrete against ground "
                "improvement."
            )
        elif probe is not None and probe.best_settlement > 0:
            parts.append(
                f"Probing out to {ln(probe.max_probed)} found no working size. The "
                f"least settlement at ANY width tried is {st_(probe.best_settlement)} "
                f"at B = {ln(probe.best_b)}, still above the "
                f"{st_(c.settlement_limit)} limit. Widening cannot solve this: a wider "
                "footing pushes its stress bulb deeper into the compressible stratum, "
                "cancelling the lower contact pressure. The real options are ground "
                "improvement, a mat, or deep foundations - or confirming with the "
                f"structural engineer whether {st_(probe.best_settlement)} is tolerable."
            )
        elif slope is not None and slope > -0.4:
            parts.append(
                f"Settlement falls only as B^{slope:.2f} at the top of the search "
                "range, so widening is close to useless here."
            )
        else:
            parts.append(
                f"Raising max_width above {ln(c.max_width)} may find a solution."
            )
    else:
        parts.append(
            "Bearing capacity governs. Founding deeper reaches stronger material and "
            "raises capacity faster than widening does."
        )

    if last_fail:
        parts.append(f"Solver note: {last_fail}")
    return " ".join(parts)
