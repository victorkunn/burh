"""Unit-aware public API.

This is the layer engineers touch. Everything here accepts and returns the
units declared on the :class:`Project`; conversion to the internal SI base set
happens exactly once, on the way in and on the way out.
"""

from __future__ import annotations

from dataclasses import dataclass

from .bearing import BearingMethod
from .codes import CODES, Approach, DesignCodeSpec, get_code
from .design import ColumnLoad, DesignCriteria, FootingDesign, design_footing
from .soil import Drainage, PhiCorrelation, SoilLayer, SoilProfile, phi_from_spt
from .units import UnitSystem, Units

# Sensible defaults per unit system, expressed in USER units.
_DEFAULTS = {
    UnitSystem.US: dict(
        settlement_limit=1.0,      # in
        min_width=2.0,             # ft
        max_width=20.0,            # ft
        size_increment=0.25,       # ft (3 in)
        min_embedment=1.5,         # ft
    ),
    UnitSystem.SI: dict(
        settlement_limit=25.0,     # mm
        min_width=0.60,            # m
        max_width=6.00,            # m
        size_increment=0.05,       # m
        min_embedment=0.45,        # m
    ),
}


@dataclass
class ProjectResult:
    design: FootingDesign
    units: Units

    # -- convenience accessors in USER units --------------------------------
    @property
    def b(self) -> float:
        return self.units.from_si_length(self.design.b)

    @property
    def l(self) -> float:
        return self.units.from_si_length(self.design.l)

    @property
    def df(self) -> float:
        return self.units.from_si_length(self.design.df)

    @property
    def thickness(self) -> float:
        return self.units.from_si_length(self.design.thickness)

    @property
    def q_applied(self) -> float:
        return self.units.from_si_stress(self.design.q_applied_gross)

    @property
    def q_allow(self) -> float:
        return self.units.from_si_stress(self.design.q_allow_gross)

    @property
    def settlement(self) -> float:
        return self.units.from_si_settlement(self.design.total_settlement)

    @property
    def concrete_volume(self) -> float:
        f = self.units.from_si_length(1.0)
        return self.design.concrete_volume * f**3


class Project:
    """A foundation design job: one soil profile, one set of criteria, many
    columns."""

    def __init__(self, name: str = "Untitled", units: str | UnitSystem = "US",
                 code: str | DesignCodeSpec = "us_asd") -> None:
        self.name = name
        self.units = Units(units)
        self.code = code if isinstance(code, DesignCodeSpec) else get_code(code)
        self._layers: list[SoilLayer] = []
        self._water_table = float("inf")
        self._loads: list[ColumnLoad] = []
        self._criteria = self._default_criteria()
        self._profile: SoilProfile | None = None

    # -- criteria -----------------------------------------------------------
    def _default_criteria(self) -> DesignCriteria:
        u = self.units
        d = _DEFAULTS[u.system]
        return DesignCriteria(
            code=self.code,
            factor_of_safety_bearing=self.code.factor_of_safety or 3.0,
            settlement_limit=u.to_si_settlement(d["settlement_limit"]),
            min_width=u.to_si_length(d["min_width"]),
            max_width=u.to_si_length(d["max_width"]),
            size_increment=u.to_si_length(d["size_increment"]),
            min_embedment=u.to_si_length(d["min_embedment"]),
        )

    def set_criteria(
        self,
        fs_bearing: float | None = None,
        fs_sliding: float | None = None,
        settlement_limit: float | None = None,
        min_width: float | None = None,
        max_width: float | None = None,
        size_increment: float | None = None,
        min_embedment: float | None = None,
        aspect_ratio: float | None = None,
        bearing_method: str | BearingMethod | None = None,
        influence_depth_ratio: float | None = None,
        time_years: float | None = None,
        code: str | DesignCodeSpec | None = None,
        resistance_factor: float | None = None,
    ) -> "Project":
        u, c = self.units, self._criteria
        if code is not None:
            self.code = code if isinstance(code, DesignCodeSpec) else get_code(code)
            c.code = self.code
            if self.code.factor_of_safety is not None:
                c.factor_of_safety_bearing = self.code.factor_of_safety
        if resistance_factor is not None:
            c.resistance_factor_bearing = resistance_factor
        if fs_bearing is not None:
            c.factor_of_safety_bearing = fs_bearing
        if fs_sliding is not None:
            c.factor_of_safety_sliding = fs_sliding
        if settlement_limit is not None:
            c.settlement_limit = u.to_si_settlement(settlement_limit)
        if min_width is not None:
            c.min_width = u.to_si_length(min_width)
        if max_width is not None:
            c.max_width = u.to_si_length(max_width)
        if size_increment is not None:
            c.size_increment = u.to_si_length(size_increment)
        if min_embedment is not None:
            c.min_embedment = u.to_si_length(min_embedment)
        if aspect_ratio is not None:
            c.aspect_ratio = aspect_ratio
        if influence_depth_ratio is not None:
            c.influence_depth_ratio = influence_depth_ratio
        if time_years is not None:
            c.time_years = time_years
        if bearing_method is not None:
            c.bearing_method = (
                bearing_method if isinstance(bearing_method, BearingMethod)
                else BearingMethod(str(bearing_method).lower())
            )
        c.__post_init__()
        return self

    # -- soil ---------------------------------------------------------------
    def add_layer(
        self,
        name: str,
        thickness: float,
        gamma: float,
        gamma_sat: float | None = None,
        drainage: str | Drainage = "drained",
        phi: float = 0.0,
        cohesion: float = 0.0,
        elastic_modulus: float | None = None,
        spt_n: float | None = None,
        energy_ratio: float = 60.0,
        cc: float | None = None,
        cr: float | None = None,
        e0: float | None = None,
        ocr: float = 1.0,
        soil_class: str = "clean_sand_nc",
    ) -> "Project":
        """Add a stratum, working downward from grade. User units throughout."""
        u = self.units
        d = drainage if isinstance(drainage, Drainage) else Drainage(str(drainage).lower())
        self._layers.append(SoilLayer(
            name=name,
            thickness=u.to_si_length(thickness),
            gamma=u.to_si_unit_weight(gamma),
            gamma_sat=u.to_si_unit_weight(gamma_sat) if gamma_sat is not None else None,
            drainage=d,
            phi=phi,
            cohesion=u.to_si_stress(cohesion),
            elastic_modulus=u.to_si_stress(elastic_modulus) if elastic_modulus is not None else None,
            spt_n=spt_n,
            energy_ratio=energy_ratio,
            cc=cc, cr=cr, e0=e0, ocr=ocr, soil_class=soil_class,
        ))
        self._profile = None
        return self

    def set_water_table(self, depth: float) -> "Project":
        """Depth to groundwater below grade, in user length units."""
        self._water_table = self.units.to_si_length(depth)
        self._profile = None
        return self

    def infer_phi_from_spt(
        self, method: str | PhiCorrelation = PhiCorrelation.KULHAWY_MAYNE
    ) -> list[str]:
        """Fill in phi for any DRAINED layer that has an SPT N but no phi.

        Returns a list of human-readable notes recording exactly what was
        inferred and from which published correlation, so the assumption is
        visible in the calculation package instead of buried.
        """
        m = method if isinstance(method, PhiCorrelation) else PhiCorrelation(str(method))
        profile = self._build_profile(strict=False)
        notes: list[str] = []
        for i, layer in enumerate(self._layers):
            if layer.drainage is not Drainage.DRAINED:
                continue
            if layer.phi > 0 or layer.spt_n is None:
                continue
            z_mid = profile.layer_top(i) + layer.thickness / 2.0
            sigma = profile.effective_stress(z_mid)
            phi, cite = phi_from_spt(layer.spt_n, sigma, layer.energy_ratio, m)
            layer.phi = phi
            note = (
                f"{layer.name}: phi' = {phi:.1f} deg ESTIMATED from N = "
                f"{layer.spt_n:g} at sigma'v = {self.units.from_si_stress(sigma):.2f} "
                f"{self.units.label('stress')} per {cite}."
            )
            layer.notes.append(note)
            notes.append(note)
        self._profile = None
        return notes

    # -- loads --------------------------------------------------------------
    def add_column(
        self,
        mark: str,
        dead: float,
        live: float = 0.0,
        horizontal: float = 0.0,
        moment_b: float = 0.0,
        moment_l: float = 0.0,
        column_b: float | None = None,
        column_l: float | None = None,
        embedment: float | None = None,
    ) -> "Project":
        u = self.units
        default_col = 1.33 if u.system is UnitSystem.US else 0.40  # 16 in / 400 mm
        self._loads.append(ColumnLoad(
            mark=mark,
            dead=u.to_si_force(dead),
            live=u.to_si_force(live),
            horizontal=u.to_si_force(horizontal),
            moment_b=u.to_si_moment(moment_b),
            moment_l=u.to_si_moment(moment_l),
            column_b=u.to_si_length(column_b if column_b is not None else default_col),
            column_l=u.to_si_length(column_l if column_l is not None else default_col),
            embedment=u.to_si_length(embedment) if embedment is not None else None,
        ))
        return self

    # -- run ----------------------------------------------------------------
    def _build_profile(self, strict: bool = True) -> SoilProfile:
        if not self._layers:
            raise ValueError("No soil layers defined. Add at least one layer.")
        if self._profile is None:
            self._profile = SoilProfile(self._layers, self._water_table)
        return self._profile

    @property
    def profile(self) -> SoilProfile:
        return self._build_profile()

    @property
    def criteria(self) -> DesignCriteria:
        return self._criteria

    @property
    def loads(self) -> list[ColumnLoad]:
        return list(self._loads)

    def run(self) -> list[ProjectResult]:
        """Size every column. Failures are returned, not raised, so one bad
        column never kills a 200-footing batch."""
        profile = self._build_profile()
        if not self._loads:
            raise ValueError("No column loads defined.")
        out: list[ProjectResult] = []
        for load in self._loads:
            try:
                d = design_footing(profile, load, self._criteria, self.units)
            except ValueError as exc:
                d = FootingDesign(mark=load.mark, ok=False, governing="ERROR",
                                  message=str(exc))
            out.append(ProjectResult(design=d, units=self.units))
        return out
