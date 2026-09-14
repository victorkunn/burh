"""Ultimate bearing capacity of shallow foundations.

General bearing capacity equation (Terzaghi form with Vesic factors):

    q_ult = c*Nc*sc*dc*ic + q*Nq*sq*dq*iq + 0.5*gamma_e*B'*Ng*sg*dg*ig

Sign / convention notes that matter and are routinely gotten wrong:

* ``q`` is the EFFECTIVE overburden at founding level for a drained
  analysis, and the TOTAL overburden for an undrained (phi = 0) analysis.
* Shape factors use the EFFECTIVE dimensions B'/L' (Meyerhof effective area).
* Depth factors use the ACTUAL B, because embedment resistance is mobilised
  by the real footing geometry, not the reduced bearing area.
* ``B'`` in the self-weight term is the SHORTER effective dimension.
* Groundwater reduces the self-weight term via an equivalent unit weight.

Every intermediate is retained on :class:`BearingResult` so the calculation
sheet can show the full derivation rather than a single black-box number.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum

from .soil import Drainage, SoilProfile

N_C_PHI_ZERO = math.pi + 2.0  # 5.14159..., Prandtl


class BearingMethod(Enum):
    """Which N-gamma expression to use. Nc and Nq are identical across all
    three (Prandtl / Reissner); only N-gamma is empirical and disputed."""

    VESIC = "vesic"
    """Ng = 2(Nq+1)tan(phi). AASHTO / US practice default. Least conservative."""

    HANSEN = "hansen"
    """Ng = 1.5(Nq-1)tan(phi). Eurocode-adjacent."""

    MEYERHOF = "meyerhof"
    """Ng = (Nq-1)tan(1.4 phi). Comparable to Hansen; the two cross near
    phi ~ 25 deg, so neither is uniformly the more conservative."""


@dataclass
class BearingFactors:
    nc: float
    nq: float
    ngamma: float
    method: BearingMethod


def bearing_factors(phi_deg: float, method: BearingMethod = BearingMethod.VESIC) -> BearingFactors:
    """Bearing capacity factors.

    Nq = e^(pi tan phi) * tan^2(45 + phi/2)      (Reissner 1924)
    Nc = (Nq - 1) cot(phi), -> pi + 2 at phi = 0  (Prandtl 1921)
    """
    if phi_deg < 0 or phi_deg >= 60:
        raise ValueError(f"phi = {phi_deg} deg outside valid range [0, 60).")
    phi = math.radians(phi_deg)

    if phi_deg == 0.0:
        return BearingFactors(nc=N_C_PHI_ZERO, nq=1.0, ngamma=0.0, method=method)

    nq = math.exp(math.pi * math.tan(phi)) * math.tan(math.radians(45.0 + phi_deg / 2.0)) ** 2
    nc = (nq - 1.0) / math.tan(phi)

    if method is BearingMethod.VESIC:
        ngamma = 2.0 * (nq + 1.0) * math.tan(phi)
    elif method is BearingMethod.HANSEN:
        ngamma = 1.5 * (nq - 1.0) * math.tan(phi)
    else:  # MEYERHOF
        ngamma = (nq - 1.0) * math.tan(1.4 * phi)

    return BearingFactors(nc=nc, nq=nq, ngamma=ngamma, method=method)


def shape_factors(b_eff: float, l_eff: float, phi_deg: float, nq: float, nc: float) -> tuple[float, float, float]:
    """Vesic / De Beer shape factors, using EFFECTIVE dimensions."""
    if b_eff <= 0 or l_eff <= 0:
        raise ValueError("Effective dimensions must be positive.")
    ratio = b_eff / l_eff
    phi = math.radians(phi_deg)
    sc = 1.0 + ratio * (nq / nc)
    sq = 1.0 + ratio * math.tan(phi)
    sg = max(0.6, 1.0 - 0.4 * ratio)
    return sc, sq, sg


def depth_factors(df: float, b: float, phi_deg: float) -> tuple[float, float, float, float]:
    """Vesic / Hansen depth factors. Returns ``(dc, dq, dg, k)``.

    k = Df/B for Df/B <= 1, else arctan(Df/B) in RADIANS. Forgetting the
    radian switch is a classic error that silently inflates deep footings.
    """
    if b <= 0:
        raise ValueError("Footing width must be positive.")
    ratio = df / b
    k = ratio if ratio <= 1.0 else math.atan(ratio)
    phi = math.radians(phi_deg)
    dq = 1.0 + 2.0 * math.tan(phi) * (1.0 - math.sin(phi)) ** 2 * k
    dc = 1.0 + 0.4 * k if phi_deg == 0.0 else dq - (1.0 - dq) / (bearing_factors(phi_deg).nc * math.tan(phi))
    dg = 1.0
    return dc, dq, dg, k


def inclination_factors(
    v: float,
    h: float,
    b_eff: float,
    l_eff: float,
    phi_deg: float,
    cohesion: float,
    nc: float,
    nq: float,
    theta_from_l: float = 90.0,
) -> tuple[float, float, float, float]:
    """Vesic load-inclination factors. Returns ``(ic, iq, ig, m)``.

    ``theta_from_l`` is the angle [deg] between the horizontal load vector and
    the L axis; 90 deg (default) means H acts parallel to the B dimension,
    which is the usual critical case for a rectangular footing.
    """
    if h <= 0.0:
        return 1.0, 1.0, 1.0, 0.0
    if v <= 0.0:
        raise ValueError("Vertical load must be > 0 to evaluate load inclination.")

    ratio = b_eff / l_eff
    m_b = (2.0 + ratio) / (1.0 + ratio)
    m_l = (2.0 + 1.0 / ratio) / (1.0 + 1.0 / ratio)
    th = math.radians(theta_from_l)
    m = m_l * math.cos(th) ** 2 + m_b * math.sin(th) ** 2

    area = b_eff * l_eff
    phi = math.radians(phi_deg)

    if phi_deg == 0.0:
        if cohesion <= 0:
            raise ValueError("phi = 0 analysis requires cohesion > 0.")
        ic = 1.0 - m * h / (area * cohesion * nc)
        iq = 1.0
        ig = 1.0
        return max(ic, 0.0), iq, ig, m

    denom = v + area * cohesion / math.tan(phi)
    base = 1.0 - h / denom
    if base <= 0.0:
        raise ValueError(
            f"Horizontal load H = {h:.1f} kN exceeds the available shear resistance; "
            "the footing slides before it bears. Increase size or add a key."
        )
    iq = base**m
    ig = base ** (m + 1.0)
    ic = iq - (1.0 - iq) / (nq - 1.0)
    return max(ic, 0.0), iq, ig, m


def effective_gamma(profile: SoilProfile, df: float, b: float, gamma_moist: float) -> tuple[float, str]:
    """Equivalent unit weight for the self-weight (B) term [kN/m3].

    Case I   : water table at or above founding level -> fully buoyant.
    Case II  : water table within B below the base    -> linear transition.
    Case III : water table deeper than Df + B         -> no reduction.
    """
    dw = profile.water_table_depth
    layer = profile.layer_at(df + b / 2.0)
    gamma_sub = layer.gamma_buoyant
    if not math.isfinite(dw) or dw >= df + b:
        return gamma_moist, "Case III - water table below the failure zone; no reduction."
    if dw <= df:
        return gamma_sub, f"Case I - water table at/above base; gamma' = {gamma_sub:.2f} kN/m3."
    gamma_e = gamma_sub + ((dw - df) / b) * (gamma_moist - gamma_sub)
    return gamma_e, (
        f"Case II - water table {dw - df:.2f} m below base; interpolated "
        f"gamma_e = {gamma_e:.2f} kN/m3."
    )


@dataclass
class BearingResult:
    """Full ultimate bearing capacity derivation."""

    q_ult: float           # gross ultimate bearing pressure [kPa]
    q_net_ult: float       # net ultimate (gross minus overburden) [kPa]
    q_allow: float         # gross allowable = q_ult / FS [kPa]
    q_net_allow: float     # net allowable = q_net_ult / FS [kPa]
    factor_of_safety: float

    # Inputs actually used
    b: float
    l: float
    b_eff: float
    l_eff: float
    df: float
    cohesion: float
    phi: float
    surcharge_q: float
    gamma_e: float
    drainage: Drainage

    # Factors
    factors: BearingFactors
    sc: float
    sq: float
    sg: float
    dc: float
    dq: float
    dg: float
    ic: float
    iq: float
    ig: float
    k_depth: float
    m_incl: float

    # Term-by-term contributions [kPa]
    term_cohesion: float
    term_surcharge: float
    term_self_weight: float

    gw_note: str = ""
    warnings: list[str] = field(default_factory=list)


def ultimate_bearing_capacity(
    profile: SoilProfile,
    b: float,
    l: float,
    df: float,
    v: float,
    h: float = 0.0,
    m_b: float = 0.0,
    m_l: float = 0.0,
    factor_of_safety: float = 3.0,
    method: BearingMethod = BearingMethod.VESIC,
    influence_depth_ratio: float = 1.5,
    theta_from_l: float = 90.0,
) -> BearingResult:
    """Gross and net ultimate bearing capacity of a rectangular footing.

    Parameters (all internal SI: m, kN, kPa, kN/m3)
    -----------------------------------------------
    b, l : plan dimensions; ``b`` is nominally the short side.
    df   : founding depth below grade.
    v    : unfactored vertical service load at the base of the footing.
    h    : horizontal service load.
    m_b  : moment producing eccentricity in the B direction [kN-m].
    m_l  : moment producing eccentricity in the L direction [kN-m].
    influence_depth_ratio : depth below the base, as a multiple of B, over
        which layer properties are averaged for the failure wedge.
    """
    if b <= 0 or l <= 0:
        raise ValueError("Footing dimensions must be positive.")
    if df < 0:
        raise ValueError("Founding depth must be >= 0.")
    if v <= 0:
        raise ValueError("Vertical load must be > 0.")
    if factor_of_safety <= 1.0:
        raise ValueError("Factor of safety must exceed 1.0.")

    warnings: list[str] = []

    # --- eccentricity / effective area (Meyerhof) --------------------------
    e_b = abs(m_b) / v
    e_l = abs(m_l) / v
    if e_b >= b / 2.0 or e_l >= l / 2.0:
        raise ValueError(
            f"Eccentricity exceeds half the footing dimension "
            f"(e_B/B = {e_b / b:.3f}, e_L/L = {e_l / l:.3f}). The footing overturns."
        )
    if e_b > b / 6.0 + 1e-12 or e_l > l / 6.0 + 1e-12:
        warnings.append(
            f"Resultant falls outside the kern (e_B/B = {e_b / b:.3f}, "
            f"e_L/L = {e_l / l:.3f} vs 1/6 = 0.167). Bearing pressure "
            "distribution is triangular with uplift at one edge; confirm the "
            "structural design accounts for partial contact."
        )
    b_eff_raw = b - 2.0 * e_b
    l_eff_raw = l - 2.0 * e_l
    # By convention B' is the shorter effective dimension.
    b_eff, l_eff = min(b_eff_raw, l_eff_raw), max(b_eff_raw, l_eff_raw)

    # --- averaged soil properties over the failure zone --------------------
    props = averaged_properties(profile, df, b, influence_depth_ratio)
    warnings.extend(props.warnings)
    phi = props.phi
    cohesion = props.cohesion
    drainage = props.drainage

    # --- surcharge ---------------------------------------------------------
    stress = profile.stress_at(df)
    if drainage is Drainage.UNDRAINED:
        # Total-stress analysis: surcharge is the TOTAL overburden.
        surcharge = stress.total
    else:
        surcharge = stress.effective

    # --- factors -----------------------------------------------------------
    f = bearing_factors(phi, method)
    sc, sq, sg = shape_factors(b_eff, l_eff, phi, f.nq, f.nc)
    dc, dq, dg, k = depth_factors(df, b, phi)
    ic, iq, ig, m = inclination_factors(
        v, h, b_eff, l_eff, phi, cohesion, f.nc, f.nq, theta_from_l
    )

    gamma_e, gw_note = effective_gamma(profile, df, b, props.gamma_moist)

    term_c = cohesion * f.nc * sc * dc * ic
    term_q = surcharge * f.nq * sq * dq * iq
    term_g = 0.5 * gamma_e * b_eff * f.ngamma * sg * dg * ig

    q_ult = term_c + term_q + term_g
    q_net_ult = q_ult - surcharge

    if not profile.extends_below(df + influence_depth_ratio * b):
        warnings.append(
            f"Boring terminates at {profile.total_depth:.2f} m but the bearing "
            f"failure zone extends to {df + influence_depth_ratio * b:.2f} m. "
            "The bottom layer has been extrapolated - verify with a deeper boring."
        )

    return BearingResult(
        q_ult=q_ult,
        q_net_ult=q_net_ult,
        q_allow=q_ult / factor_of_safety,
        q_net_allow=q_net_ult / factor_of_safety,
        factor_of_safety=factor_of_safety,
        b=b, l=l, b_eff=b_eff, l_eff=l_eff, df=df,
        cohesion=cohesion, phi=phi, surcharge_q=surcharge, gamma_e=gamma_e,
        drainage=drainage,
        factors=f, sc=sc, sq=sq, sg=sg, dc=dc, dq=dq, dg=dg,
        ic=ic, iq=iq, ig=ig, k_depth=k, m_incl=m,
        term_cohesion=term_c, term_surcharge=term_q, term_self_weight=term_g,
        gw_note=gw_note, warnings=warnings,
    )


@dataclass
class AveragedProperties:
    phi: float
    cohesion: float
    gamma_moist: float
    drainage: Drainage
    warnings: list[str] = field(default_factory=list)


def averaged_properties(
    profile: SoilProfile, df: float, b: float, influence_depth_ratio: float = 1.5
) -> AveragedProperties:
    """Thickness-weighted soil properties over the bearing failure zone.

    phi is averaged on tan(phi) rather than on degrees, which is the
    mechanically meaningful average for a friction angle.

    If the zone spans layers of materially different strength the result is
    flagged: the closed-form bearing equation assumes a homogeneous half
    space, and a strong-over-weak profile requires a punching-shear check
    (Meyerhof & Hanna 1978) that this function does NOT perform.
    """
    z_top = df
    z_bot = df + influence_depth_ratio * b
    warnings: list[str] = []

    seen: list[tuple[float, object]] = []  # (thickness in zone, layer)
    z = z_top
    while z < z_bot - 1e-9:
        layer = profile.layer_at(z)
        # Find where this layer ends.
        end = z_bot
        for i, lay in enumerate(profile.layers):
            if lay is layer:
                end = min(z_bot, profile.layer_bottom(i))
                break
        else:  # extrapolated bottom layer
            end = z_bot
        if end <= z:
            end = z_bot
        seen.append((end - z, layer))
        z = end

    total_t = sum(t for t, _ in seen)
    if total_t <= 0:  # pragma: no cover - defensive
        layer = profile.layer_at(df)
        return AveragedProperties(layer.phi, layer.cohesion, layer.gamma, layer.drainage)

    tan_phi = sum(t * math.tan(math.radians(lay.phi)) for t, lay in seen) / total_t
    cohesion = sum(t * lay.cohesion for t, lay in seen) / total_t
    gamma = sum(t * lay.gamma for t, lay in seen) / total_t

    drainages = {lay.drainage for _, lay in seen}
    if len(drainages) > 1:
        warnings.append(
            "The bearing failure zone spans both drained and undrained layers. "
            "Averaged properties are NOT a valid substitute for checking each "
            "condition separately - run the drained and undrained cases as two "
            "analyses and take the lower capacity."
        )
        drainage = Drainage.UNDRAINED if Drainage.UNDRAINED in drainages else Drainage.DRAINED
    else:
        drainage = drainages.pop()

    if len(seen) > 1:
        # Crude strength proxy, used only to decide whether to WARN - never to
        # compute capacity. It puts cohesion and friction on one axis by
        # evaluating shear strength at a nominal 50 kPa normal stress.
        def strength(layer) -> float:
            return layer.cohesion + 50.0 * math.tan(math.radians(layer.phi))

        strengths = [strength(lay) for _, lay in seen]
        lo, hi = min(strengths), max(strengths)
        if lo > 0 and hi / lo > 1.5:
            top = seen[0][1]
            weakest = min(seen, key=lambda item: strength(item[1]))[1]
            strongest = max(seen, key=lambda item: strength(item[1]))[1]
            if weakest is not top:
                warnings.append(
                    f"Strong layer ({top.name}) over weaker layer ({weakest.name}) "
                    "within the failure zone. The averaged solution is UNCONSERVATIVE "
                    "here; a punching-shear check (Meyerhof & Hanna 1978) is required."
                )
            elif strongest is not top:
                warnings.append(
                    f"Weak layer ({top.name}) over stronger layer ({strongest.name}) "
                    "within the failure zone. Averaging is conservative but crude; "
                    "consider founding on the deeper stratum."
                )

    phi = math.degrees(math.atan(tan_phi))
    if drainage is Drainage.UNDRAINED:
        phi = 0.0
    return AveragedProperties(phi, cohesion, gamma, drainage, warnings)


def sliding_resistance(
    v: float, b_eff: float, l_eff: float, phi: float, cohesion: float,
    interface_factor: float = 0.67,
) -> float:
    """Ultimate base sliding resistance [kN].

    R = V * tan(delta) + c_a * A', with delta = interface_factor * phi and
    adhesion c_a = interface_factor * c (capped at c).
    """
    delta = math.radians(interface_factor * phi)
    adhesion = min(cohesion, interface_factor * cohesion)
    return v * math.tan(delta) + adhesion * b_eff * l_eff
