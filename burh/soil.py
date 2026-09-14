"""Soil layer / profile model and SPT correlations.

All quantities stored on these objects are INTERNAL SI (m, kN, kPa, kN/m3).
Build them through :func:`burh.api.soil_layer` if you are working in US units.

Correlations are deliberately explicit about provenance. Every correlated
value carries the citation it came from so the calculation package can be
defended in review. Correlations are ESTIMATES; where laboratory or in-situ
data exist they must be used instead.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum

from .units import GAMMA_WATER_KNM3, P_ATM_KPA


class Drainage(Enum):
    """Governing drainage condition for the bearing analysis."""

    DRAINED = "drained"
    """Effective-stress analysis: c', phi'. Sands, gravels, long-term clay."""

    UNDRAINED = "undrained"
    """Total-stress analysis: phi = 0, c = su. Short-term saturated clay."""


class PhiCorrelation(Enum):
    """Available SPT -> effective friction angle correlations."""

    KULHAWY_MAYNE = "kulhawy_mayne_1990"
    HATANAKA_UCHIDA = "hatanaka_uchida_1996"
    WOLFF = "wolff_1989"


#: Kulhawy & Mayne (1990): Es / Pa = ALPHA_E * N60.
#: These are the published bracket values. The scatter is roughly a factor of
#: two; a measured or CPT-derived Es beats any of them.
ALPHA_E = {
    "sand_with_fines": 5.0,
    "clean_sand_nc": 10.0,
    "clean_sand_oc": 15.0,
}
#: Default soil class assumed when a layer does not declare one.
DEFAULT_SOIL_CLASS = "clean_sand_nc"


@dataclass
class SoilLayer:
    """One soil stratum.

    Parameters
    ----------
    name:
        Free text description as it appears on the boring log.
    thickness:
        Layer thickness [m]. Must be > 0.
    gamma:
        Moist (above water table) total unit weight [kN/m3].
    gamma_sat:
        Saturated total unit weight [kN/m3]. Defaults to ``gamma``, which is
        conservative-neutral but should be supplied explicitly whenever the
        water table falls inside or above the layer.
    drainage:
        Analysis condition governing this layer.
    phi:
        Effective friction angle [degrees]. 0 for an undrained clay analysis.
    cohesion:
        c' [kPa] for a drained analysis, or su [kPa] for an undrained analysis.
    elastic_modulus:
        Drained Young's modulus Es [kPa] used for Schmertmann / elastic
        settlement. If omitted it is correlated from SPT.
    spt_n:
        Representative *field* SPT blow count for the layer (uncorrected).
    energy_ratio:
        Hammer energy ratio [%] used for the N60 correction. 60 => no change.
    cc, cr, e0, ocr:
        Consolidation parameters for cohesive layers. ``cc`` is the virgin
        compression index, ``cr`` the recompression index, ``e0`` the initial
        void ratio, ``ocr`` the overconsolidation ratio.
    """

    name: str
    thickness: float
    gamma: float
    gamma_sat: float | None = None
    drainage: Drainage = Drainage.DRAINED
    phi: float = 0.0
    cohesion: float = 0.0
    elastic_modulus: float | None = None
    spt_n: float | None = None
    energy_ratio: float = 60.0
    cc: float | None = None
    cr: float | None = None
    e0: float | None = None
    ocr: float = 1.0
    soil_class: str = DEFAULT_SOIL_CLASS
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.thickness <= 0:
            raise ValueError(f"Layer {self.name!r}: thickness must be > 0.")
        if self.gamma <= 0:
            raise ValueError(f"Layer {self.name!r}: gamma must be > 0.")
        if self.gamma_sat is None:
            self.gamma_sat = self.gamma
        if self.gamma_sat < self.gamma:
            raise ValueError(
                f"Layer {self.name!r}: gamma_sat ({self.gamma_sat:.2f}) cannot be "
                f"less than moist gamma ({self.gamma:.2f})."
            )
        if self.gamma_sat <= GAMMA_WATER_KNM3:
            raise ValueError(
                f"Layer {self.name!r}: gamma_sat ({self.gamma_sat:.2f} kN/m3) is not "
                f"greater than the unit weight of water ({GAMMA_WATER_KNM3} kN/m3); "
                "buoyant unit weight would be non-positive."
            )
        if not 0.0 <= self.phi < 60.0:
            raise ValueError(
                f"Layer {self.name!r}: phi = {self.phi} deg is outside the "
                "physically plausible range 0 <= phi < 60."
            )
        if self.cohesion < 0:
            raise ValueError(f"Layer {self.name!r}: cohesion must be >= 0.")
        if self.ocr < 1.0:
            raise ValueError(
                f"Layer {self.name!r}: OCR = {self.ocr} < 1 is not physically valid."
            )
        if self.drainage is Drainage.UNDRAINED and self.phi != 0.0:
            raise ValueError(
                f"Layer {self.name!r}: an undrained (total stress) analysis requires "
                f"phi = 0, got {self.phi}. Use Drainage.DRAINED for a c'-phi' analysis."
            )
        if self.drainage is Drainage.UNDRAINED and self.cohesion <= 0:
            raise ValueError(
                f"Layer {self.name!r}: undrained analysis requires su > 0."
            )
        if self.soil_class not in ALPHA_E:
            raise ValueError(
                f"Layer {self.name!r}: unknown soil_class {self.soil_class!r}; "
                f"use one of {sorted(ALPHA_E)}."
            )

    @property
    def gamma_buoyant(self) -> float:
        """Submerged (effective) unit weight [kN/m3]."""
        return self.gamma_sat - GAMMA_WATER_KNM3

    @property
    def is_cohesive(self) -> bool:
        return self.drainage is Drainage.UNDRAINED

    def can_consolidate(self) -> bool:
        """True if the layer carries a complete consolidation parameter set."""
        return (
            self.cc is not None
            and self.e0 is not None
            and self.cc > 0
            and self.e0 > 0
        )


@dataclass
class StressState:
    """Vertical stress state at a depth, with the components kept separate
    so they can be printed on the calculation sheet."""

    depth: float
    total: float
    pore_pressure: float

    @property
    def effective(self) -> float:
        return self.total - self.pore_pressure


class SoilProfile:
    """An ordered stack of :class:`SoilLayer` with a water table.

    Depths are measured downward from existing grade (z = 0).
    """

    def __init__(
        self,
        layers: list[SoilLayer],
        water_table_depth: float = float("inf"),
    ) -> None:
        if not layers:
            raise ValueError("A soil profile requires at least one layer.")
        if water_table_depth < 0:
            raise ValueError(
                "water_table_depth must be >= 0 (measured down from grade). "
                "Artesian / above-grade water requires an explicit surcharge."
            )
        self.layers = list(layers)
        self.water_table_depth = water_table_depth

        self._tops: list[float] = []
        z = 0.0
        for layer in self.layers:
            self._tops.append(z)
            z += layer.thickness
        self.total_depth = z

    # -- geometry -----------------------------------------------------------
    def layer_at(self, depth: float) -> SoilLayer:
        """Layer containing ``depth``. The bottom layer is extended
        indefinitely so an analysis never falls off the end of the boring."""
        if depth < 0:
            raise ValueError("Depth must be >= 0.")
        for layer, top in zip(self.layers, self._tops):
            if depth < top + layer.thickness:
                return layer
        return self.layers[-1]

    def layer_top(self, index: int) -> float:
        return self._tops[index]

    def layer_bottom(self, index: int) -> float:
        return self._tops[index] + self.layers[index].thickness

    def extends_below(self, depth: float) -> bool:
        """True if the boring actually reached ``depth``."""
        return self.total_depth >= depth - 1e-9

    # -- stress -------------------------------------------------------------
    def stress_at(self, depth: float) -> StressState:
        """Total / pore / effective vertical stress at ``depth`` [kPa].

        Integrates layer by layer, switching from moist to saturated unit
        weight exactly at the water table even when it falls mid-layer.
        """
        if depth < 0:
            raise ValueError("Depth must be >= 0.")
        wt = self.water_table_depth
        total = 0.0
        z = 0.0
        for layer, top in zip(self.layers, self._tops):
            bottom = top + layer.thickness
            seg_bottom = min(bottom, depth)
            if seg_bottom <= z:
                continue
            # Portion of this segment above the water table (moist).
            dry_top = z
            dry_bottom = min(seg_bottom, max(wt, z))
            if dry_bottom > dry_top:
                total += layer.gamma * (dry_bottom - dry_top)
            # Portion below the water table (saturated).
            wet_top = max(z, min(wt, seg_bottom))
            if seg_bottom > wet_top:
                total += layer.gamma_sat * (seg_bottom - wet_top)
            z = seg_bottom
            if z >= depth:
                break
        if depth > z:
            # Below the boring: extend the bottom layer.
            last = self.layers[-1]
            dry_bottom = min(depth, max(wt, z))
            if dry_bottom > z:
                total += last.gamma * (dry_bottom - z)
            wet_top = max(z, min(wt, depth))
            if depth > wet_top:
                total += last.gamma_sat * (depth - wet_top)

        u = GAMMA_WATER_KNM3 * max(0.0, depth - wt) if math.isfinite(wt) else 0.0
        return StressState(depth=depth, total=total, pore_pressure=u)

    def effective_stress(self, depth: float) -> float:
        return self.stress_at(depth).effective

    def describe(self) -> list[str]:
        out = []
        for i, layer in enumerate(self.layers):
            out.append(
                f"{self.layer_top(i):6.2f} - {self.layer_bottom(i):6.2f} m  "
                f"{layer.name}"
            )
        return out


# --------------------------------------------------------------------------
# SPT corrections
# --------------------------------------------------------------------------


def rod_length_factor(rod_length: float) -> float:
    """C_R, rod-length energy correction (Youd et al. 2001). ``rod_length`` [m]."""
    if rod_length < 3.0:
        return 0.75
    if rod_length < 4.0:
        return 0.80
    if rod_length < 6.0:
        return 0.85
    if rod_length < 10.0:
        return 0.95
    return 1.00


def n60(
    n_field: float,
    energy_ratio: float = 60.0,
    borehole_factor: float = 1.0,
    sampler_factor: float = 1.0,
    rod_length: float | None = None,
) -> float:
    """Energy-corrected blow count N60.

    N60 = N_field * (ER/60) * C_B * C_S * C_R
    """
    if n_field < 0:
        raise ValueError("SPT N cannot be negative.")
    if energy_ratio <= 0:
        raise ValueError("Hammer energy ratio must be > 0 %.")
    c_r = 1.0 if rod_length is None else rod_length_factor(rod_length)
    return n_field * (energy_ratio / 60.0) * borehole_factor * sampler_factor * c_r


def overburden_factor(sigma_v_eff: float, cap: float = 1.7) -> float:
    """C_N after Liao & Whitman (1986): C_N = sqrt(Pa / sigma'_v), capped.

    The cap matters near the surface where sigma'_v -> 0 and the raw
    expression diverges.
    """
    if sigma_v_eff <= 0:
        return cap
    return min(cap, math.sqrt(P_ATM_KPA / sigma_v_eff))


def n1_60(n_field: float, sigma_v_eff: float, energy_ratio: float = 60.0, **kw) -> float:
    """Overburden- and energy-corrected blow count (N1)60."""
    return n60(n_field, energy_ratio=energy_ratio, **kw) * overburden_factor(
        sigma_v_eff
    )


def phi_from_spt(
    n_field: float,
    sigma_v_eff: float,
    energy_ratio: float = 60.0,
    method: PhiCorrelation = PhiCorrelation.KULHAWY_MAYNE,
) -> tuple[float, str]:
    """Estimate phi' [degrees] from SPT.

    Returns ``(phi_deg, citation)``. THIS IS AN ESTIMATE, not a measurement.
    """
    n_60 = n60(n_field, energy_ratio=energy_ratio)
    if method is PhiCorrelation.KULHAWY_MAYNE:
        # phi' = atan[ (N60 / (12.2 + 20.3 * sigma'_v/Pa)) ^ 0.34 ]
        denom = 12.2 + 20.3 * (max(sigma_v_eff, 1e-6) / P_ATM_KPA)
        phi = math.degrees(math.atan((max(n_60, 1e-6) / denom) ** 0.34))
        cite = "Kulhawy & Mayne (1990)"
    elif method is PhiCorrelation.HATANAKA_UCHIDA:
        n1 = n_60 * overburden_factor(sigma_v_eff)
        phi = math.sqrt(20.0 * n1) + 20.0
        cite = "Hatanaka & Uchida (1996)"
    else:
        n1 = n_60 * overburden_factor(sigma_v_eff)
        phi = 27.1 + 0.3 * n1 - 0.00054 * n1**2
        cite = "Wolff (1989)"
    # Clamp to a defensible range for a design parameter.
    phi = max(25.0, min(45.0, phi))
    return phi, cite


def es_from_spt(
    n_field: float,
    energy_ratio: float = 60.0,
    soil_class: str = DEFAULT_SOIL_CLASS,
) -> float:
    """Drained Young's modulus [kPa] correlated from SPT.

    Es = ALPHA_E * N60 * Pa, after Kulhawy & Mayne (1990).

    This is an ESTIMATE with roughly a factor-of-two scatter. It exists so a
    preliminary run is possible from a boring log alone; it is not a
    substitute for a measured modulus.
    """
    n_60 = n60(n_field, energy_ratio=energy_ratio)
    if soil_class not in ALPHA_E:
        raise ValueError(
            f"Unknown soil_class {soil_class!r}; use one of {sorted(ALPHA_E)}."
        )
    return ALPHA_E[soil_class] * n_60 * P_ATM_KPA
