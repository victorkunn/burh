"""Settlement of shallow foundations.

Granular layers  -> Schmertmann (1978) strain-influence-factor method.
Cohesive layers  -> Terzaghi 1-D consolidation with OCR / recompression.
Cohesive layers  -> plus an elastic (immediate, undrained) component.

Settlement usually governs the design of footings on sand, and bearing
capacity usually governs on clay. Tools that check only bearing capacity
oversize clay footings and undersize sand footings. Both are checked here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .soil import Drainage, SoilProfile, es_from_spt
from .units import P_ATM_KPA
from .stress import boussinesq_rectangle_center, influence_depth


# --------------------------------------------------------------------------
# Schmertmann strain influence factor
# --------------------------------------------------------------------------


def schmertmann_geometry(l_over_b: float) -> tuple[float, float, float]:
    """Return ``(iz_at_surface, zp_over_b, zmax_over_b)``.

    Axisymmetric (L/B = 1) : Iz0 = 0.1, peak at 0.5B, zero at 2B
    Plane strain (L/B >= 10): Iz0 = 0.2, peak at 1.0B, zero at 4B

    Interpolated linearly on log10(L/B) in between, which is standard
    practice for rectangular footings.
    """
    if l_over_b < 1.0:
        l_over_b = 1.0
    t = min(1.0, math.log10(l_over_b))  # 0 at L/B=1, 1 at L/B=10
    iz0 = 0.1 + 0.1 * t
    zp = 0.5 + 0.5 * t
    zmax = 2.0 + 2.0 * t
    return iz0, zp, zmax


def strain_influence(z_over_b: float, iz0: float, zp: float, zmax: float, izp: float) -> float:
    """Iz at depth ``z_over_b`` below the footing base (z normalised by B)."""
    if z_over_b <= 0.0:
        return iz0
    if z_over_b >= zmax:
        return 0.0
    if z_over_b <= zp:
        return iz0 + (izp - iz0) * (z_over_b / zp)
    return izp * (zmax - z_over_b) / (zmax - zp)


@dataclass
class SublayerResult:
    z_top: float
    z_bot: float
    layer_name: str
    method: str
    sigma0: float = 0.0
    delta_sigma: float = 0.0
    sigma_p: float = 0.0
    iz: float = 0.0
    es: float = 0.0
    settlement: float = 0.0  # [m]


@dataclass
class SettlementResult:
    total: float                      # [m]
    immediate: float                  # [m] Schmertmann + elastic
    consolidation: float              # [m]
    c1: float
    c2: float
    net_pressure: float               # [kPa]
    sigma_v0_base: float              # [kPa]
    izp: float
    zp_over_b: float
    zmax_over_b: float
    sublayers: list[SublayerResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _sublayer_grid(profile: SoilProfile, df: float, z_bottom: float, b: float,
                   target: float, forced: tuple[float, ...] = ()) -> list[tuple[float, float]]:
    """Split ``df``..``z_bottom`` into sublayers that never straddle a soil
    layer boundary and are no thicker than ``target``.

    ``forced`` adds extra mandatory boundaries. The Schmertmann Iz profile is
    piecewise linear with a kink at the peak depth; midpoint integration is
    exact on each linear piece, so forcing a boundary at the kink removes the
    only real quadrature error in the summation.
    """
    bounds = {df, z_bottom}
    for z in forced:
        if df < z < z_bottom:
            bounds.add(z)
    for i in range(len(profile.layers)):
        for z in (profile.layer_top(i), profile.layer_bottom(i)):
            if df < z < z_bottom:
                bounds.add(z)
    ordered = sorted(bounds)
    out: list[tuple[float, float]] = []
    for a, bnd in zip(ordered[:-1], ordered[1:]):
        n = max(1, math.ceil((bnd - a) / target))
        step = (bnd - a) / n
        for k in range(n):
            out.append((a + k * step, a + (k + 1) * step))
    return out


def settlement(
    profile: SoilProfile,
    b: float,
    l: float,
    df: float,
    q_gross: float,
    time_years: float = 50.0,
    creep: bool = True,
    poisson: float = 0.3,
) -> SettlementResult:
    """Total settlement [m] under a rectangular footing.

    ``q_gross`` is the gross bearing pressure applied at founding level.
    """
    if b <= 0 or l <= 0:
        raise ValueError("Footing dimensions must be positive.")
    if time_years <= 0:
        raise ValueError("time_years must be > 0.")

    warnings: list[str] = []
    sigma_v0 = profile.effective_stress(df)
    net_q = q_gross - sigma_v0

    if net_q <= 0:
        return SettlementResult(
            total=0.0, immediate=0.0, consolidation=0.0, c1=1.0, c2=1.0,
            net_pressure=net_q, sigma_v0_base=sigma_v0, izp=0.0,
            zp_over_b=0.0, zmax_over_b=0.0,
            warnings=[
                "Net bearing pressure is zero or negative (full compensation); "
                "settlement taken as zero. Check heave/rebound separately."
            ],
        )

    # --- Schmertmann geometry and peak influence factor --------------------
    iz0, zp_b, zmax_b = schmertmann_geometry(l / b)
    sigma_zp = profile.effective_stress(df + zp_b * b)
    izp = 0.5 + 0.1 * math.sqrt(net_q / max(sigma_zp, 1e-6))

    c1 = max(0.5, 1.0 - 0.5 * (sigma_v0 / net_q))
    c2 = 1.0 + 0.2 * math.log10(time_years / 0.1) if creep else 1.0

    # --- depth of analysis -------------------------------------------------
    z_schmertmann = df + zmax_b * b
    z_consol = df + max(influence_depth(b, l, net_q, threshold=0.10), 0.01)
    z_bottom = max(z_schmertmann, z_consol)

    if not profile.extends_below(z_bottom):
        warnings.append(
            f"Settlement summation extends to {z_bottom:.2f} m but the boring "
            f"ends at {profile.total_depth:.2f} m. The bottom layer has been "
            "extrapolated; settlement may be underestimated if softer material "
            "exists below."
        )

    grid = _sublayer_grid(
        profile, df, z_bottom, b,
        target=max(b / 10.0, 0.05),
        forced=(df + zp_b * b, df + zmax_b * b),
    )

    immediate = 0.0
    consol = 0.0
    sub_results: list[SublayerResult] = []
    schmertmann_sum = 0.0

    for z_top, z_bot in grid:
        thickness = z_bot - z_top
        z_mid = 0.5 * (z_top + z_bot)
        layer = profile.layer_at(z_mid)
        dz_below = z_mid - df

        if layer.drainage is Drainage.DRAINED:
            # Schmertmann, only within its own influence depth.
            if dz_below > zmax_b * b:
                continue
            iz = strain_influence(dz_below / b, iz0, zp_b, zmax_b, izp)
            es = layer.elastic_modulus
            if es is None:
                if layer.spt_n is None:
                    raise ValueError(
                        f"Layer {layer.name!r}: settlement requires either "
                        "elastic_modulus or spt_n."
                    )
                es = es_from_spt(layer.spt_n, layer.energy_ratio, layer.soil_class)
                warnings.append(
                    f"Layer {layer.name!r}: Es correlated from N = {layer.spt_n:g} "
                    f"as {es / P_ATM_KPA:.0f} x atmospheric pressure, assuming "
                    f"soil_class {layer.soil_class!r} (Kulhawy & Mayne 1990). "
                    "Scatter is roughly a factor of 2 - confirm with CPT or lab data."
                )
                layer.elastic_modulus = es  # memoise so the warning fires once
            if es <= 0:
                raise ValueError(f"Layer {layer.name!r}: elastic modulus must be > 0.")
            schmertmann_sum += (iz / es) * thickness
            sub_results.append(SublayerResult(
                z_top=z_top, z_bot=z_bot, layer_name=layer.name,
                method="Schmertmann", iz=iz, es=es,
                delta_sigma=boussinesq_rectangle_center(net_q, b, l, dz_below),
                sigma0=profile.effective_stress(z_mid),
            ))
        else:
            # Cohesive: consolidation (+ elastic immediate if Es supplied).
            sigma0 = profile.effective_stress(z_mid)
            dsig = boussinesq_rectangle_center(net_q, b, l, dz_below)
            if dsig < 0.01 * net_q:
                continue
            sigma_p = layer.ocr * sigma0
            sigma_f = sigma0 + dsig

            if not layer.can_consolidate():
                warnings.append(
                    f"Layer {layer.name!r} is cohesive but has no Cc/e0; its "
                    "consolidation settlement is NOT included. Supply cc and e0 "
                    "or the total settlement is unconservative."
                )
                continue

            cc = layer.cc
            cr = layer.cr if layer.cr is not None else cc / 6.0
            s = 0.0
            if sigma_f <= sigma_p:
                s = thickness * cr / (1.0 + layer.e0) * math.log10(sigma_f / sigma0)
            else:
                if sigma_p > sigma0:
                    s += thickness * cr / (1.0 + layer.e0) * math.log10(sigma_p / sigma0)
                s += thickness * cc / (1.0 + layer.e0) * math.log10(sigma_f / max(sigma_p, sigma0))
            consol += s

            si = 0.0
            if layer.elastic_modulus:
                si = dsig * (1.0 - poisson**2) * thickness / layer.elastic_modulus
                immediate += si

            sub_results.append(SublayerResult(
                z_top=z_top, z_bot=z_bot, layer_name=layer.name,
                method="Consolidation", sigma0=sigma0, delta_sigma=dsig,
                sigma_p=sigma_p, es=layer.elastic_modulus or 0.0,
                settlement=s + si,
            ))

    s_schmertmann = c1 * c2 * net_q * schmertmann_sum
    for r in sub_results:
        if r.method == "Schmertmann":
            r.settlement = c1 * c2 * net_q * (r.iz / r.es) * (r.z_bot - r.z_top)
    immediate += s_schmertmann

    # de-duplicate repeated correlation warnings
    seen: set[str] = set()
    uniq = [w for w in warnings if not (w in seen or seen.add(w))]

    return SettlementResult(
        total=immediate + consol,
        immediate=immediate,
        consolidation=consol,
        c1=c1, c2=c2, net_pressure=net_q, sigma_v0_base=sigma_v0,
        izp=izp, zp_over_b=zp_b, zmax_over_b=zmax_b,
        sublayers=sub_results, warnings=uniq,
    )
