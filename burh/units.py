"""Unit handling.

Everything inside the engine is computed in a single consistent SI base set:

    length          m
    force           kN
    stress          kPa  (= kN/m2)
    unit weight     kN/m3
    moment          kN-m

Conversion happens ONLY at the public API boundary. No mixed-unit arithmetic
is possible internally, which removes the single most common source of error
in foundation spreadsheets.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# --- Exact conversion constants (NIST SP 811) -------------------------------
FT_TO_M = 0.3048  # exact
IN_TO_M = 0.0254  # exact
KIP_TO_KN = 4.4482216152605  # exact (1 lbf = 4.4482216152605 N)
KSF_TO_KPA = KIP_TO_KN / (FT_TO_M**2)  # 47.8802589803...
PCF_TO_KNM3 = (KIP_TO_KN / 1000.0) / (FT_TO_M**3)  # 0.157087478...

#: Atmospheric reference pressure used for SPT overburden normalisation.
P_ATM_KPA = 101.325
#: Unit weight of water. 9.81 kN/m3 == 62.43 pcf.
GAMMA_WATER_KNM3 = 9.81


class UnitSystem(Enum):
    """Input/output unit system selected by the caller."""

    SI = "SI"
    """m, kN, kPa, kN/m3 - identical to the internal base set."""

    US = "US"
    """ft, kip, ksf, pcf - US customary structural practice."""


@dataclass(frozen=True)
class _Factors:
    """Multipliers that take *user* units -> *internal* SI units."""

    length: float
    force: float
    stress: float
    unit_weight: float

    @property
    def moment(self) -> float:
        return self.force * self.length

    @property
    def area(self) -> float:
        return self.length**2


_SI = _Factors(length=1.0, force=1.0, stress=1.0, unit_weight=1.0)
_US = _Factors(
    length=FT_TO_M,
    force=KIP_TO_KN,
    stress=KSF_TO_KPA,
    unit_weight=PCF_TO_KNM3,
)

_FACTORS = {UnitSystem.SI: _SI, UnitSystem.US: _US}

_LABELS = {
    UnitSystem.SI: {
        "length": "m",
        "force": "kN",
        "stress": "kPa",
        "unit_weight": "kN/m3",
        "moment": "kN-m",
        "small_length": "mm",
    },
    UnitSystem.US: {
        "length": "ft",
        "force": "kip",
        "stress": "ksf",
        "unit_weight": "pcf",
        "moment": "kip-ft",
        "small_length": "in",
    },
}

# Settlement is conventionally reported in mm (SI) or in (US), not m/ft.
_SMALL_LENGTH_FROM_M = {UnitSystem.SI: 1000.0, UnitSystem.US: 1.0 / IN_TO_M}


class Units:
    """Bidirectional converter bound to one :class:`UnitSystem`.

    ``to_si_*``   : user units -> internal SI
    ``from_si_*`` : internal SI -> user units
    """

    __slots__ = ("system", "_f")

    def __init__(self, system: UnitSystem | str = UnitSystem.SI) -> None:
        if isinstance(system, str):
            try:
                system = UnitSystem(system.upper())
            except ValueError as exc:  # pragma: no cover - defensive
                raise ValueError(
                    f"Unknown unit system {system!r}; use 'SI' or 'US'."
                ) from exc
        self.system = system
        self._f = _FACTORS[system]

    # -- user -> SI ---------------------------------------------------------
    def to_si_length(self, v: float) -> float:
        return v * self._f.length

    def to_si_force(self, v: float) -> float:
        return v * self._f.force

    def to_si_stress(self, v: float) -> float:
        return v * self._f.stress

    def to_si_unit_weight(self, v: float) -> float:
        return v * self._f.unit_weight

    def to_si_moment(self, v: float) -> float:
        return v * self._f.moment

    # -- SI -> user ---------------------------------------------------------
    def from_si_length(self, v: float) -> float:
        return v / self._f.length

    def from_si_force(self, v: float) -> float:
        return v / self._f.force

    def from_si_stress(self, v: float) -> float:
        return v / self._f.stress

    def from_si_unit_weight(self, v: float) -> float:
        return v / self._f.unit_weight

    def from_si_moment(self, v: float) -> float:
        return v / self._f.moment

    def from_si_settlement(self, v_m: float) -> float:
        """Metres -> mm (SI) or inches (US)."""
        return v_m * _SMALL_LENGTH_FROM_M[self.system]

    def to_si_settlement(self, v: float) -> float:
        """mm (SI) or inches (US) -> metres."""
        return v / _SMALL_LENGTH_FROM_M[self.system]

    # -- labels -------------------------------------------------------------
    @property
    def labels(self) -> dict[str, str]:
        return _LABELS[self.system]

    def label(self, quantity: str) -> str:
        return _LABELS[self.system][quantity]

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"Units({self.system.value})"
