"""Design code frameworks.

US and Canadian practice do not differ by a coefficient - they differ in what
is compared to what:

    US, allowable stress design (ASD)
        q_ult / FS          >=  SERVICE (unfactored) bearing pressure

    Canada, limit states design (LSD)
        Phi * q_ult         >=  FACTORED bearing pressure

Both evaluate settlement at service load, because serviceability is a
service-load question in every framework.

Mixing the two - checking a factored pressure against an allowable capacity,
or a service pressure against a factored resistance - is the single most
consequential error available here. It is roughly a 40% error in either
direction, so the approach is carried explicitly on the criteria object and
never inferred.

NOTHING IN THIS MODULE VERIFIES CODE COMPLIANCE. It supplies the limit-state
framework and customary factors so the arithmetic is done consistently. The
governing code edition, provincial or local amendments, and the project
geotechnical report take precedence over every default here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Approach(Enum):
    """Which quantity is compared to which."""

    ASD = "asd"
    """Allowable stress design: service load vs q_ult / FS."""

    LSD = "lsd"
    """Limit states design: factored load vs Phi * q_ult."""


@dataclass(frozen=True)
class LoadCombination:
    """One ultimate limit state load combination.

    ``dead`` and ``live`` are the factors applied to the respective service
    loads. ``dead`` is applied to the column dead load AND to the footing
    self-weight and soil backfill, which are themselves dead load.
    """

    name: str
    dead: float
    live: float = 0.0

    def factored(self, dead_load: float, live_load: float) -> float:
        return self.dead * dead_load + self.live * live_load


@dataclass(frozen=True)
class DesignCodeSpec:
    """A named framework with its customary factors.

    Every value is a starting point the engineer may override. The citation
    travels onto the calculation sheet so the basis is visible.
    """

    key: str
    name: str
    region: str
    approach: Approach
    #: ASD only - global factor of safety on ultimate bearing capacity.
    factor_of_safety: float | None = None
    #: LSD only - geotechnical resistance factor applied to q_ult.
    resistance_factor: float | None = None
    #: LSD only - resistance factor for sliding.
    resistance_factor_sliding: float | None = None
    #: ASD only - required factor of safety against sliding.
    factor_of_safety_sliding: float | None = None
    #: ULS combinations. Empty for ASD, where the check is at service load.
    combinations: tuple[LoadCombination, ...] = ()
    #: Combination used where dead load RESISTS (sliding, overturning): the
    #: minimum credible dead load, not the maximum.
    counteracting: LoadCombination | None = None
    #: Default total settlement limit, metres.
    settlement_limit: float = 0.025
    citation: str = ""
    notes: tuple[str, ...] = ()

    def governing_combination(
        self, dead_load: float, live_load: float
    ) -> tuple[LoadCombination, float]:
        """Return the combination producing the largest factored load."""
        if not self.combinations:
            raise ValueError(
                f"{self.name} is an {self.approach.value.upper()} framework and has "
                "no ULS load combinations; the check is made at service load."
            )
        best = max(self.combinations, key=lambda c: c.factored(dead_load, live_load))
        return best, best.factored(dead_load, live_load)


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------

US_ASD = DesignCodeSpec(
    key="us_asd",
    name="US - Allowable Stress Design",
    region="United States",
    approach=Approach.ASD,
    factor_of_safety=3.0,
    factor_of_safety_sliding=1.5,
    settlement_limit=0.0254,  # 1 in
    citation="IBC / ASCE 7 allowable stress design; FS per customary practice",
    notes=(
        "FS = 3.0 on ultimate bearing capacity is customary US geotechnical "
        "practice for sustained (dead plus live) loading. It is NOT a value the "
        "IBC prescribes - IBC Chapter 18 gives presumptive load-bearing values "
        "rather than a factor of safety. The project geotechnical report "
        "governs, and many reports specify 2.5 or 3.0 explicitly.",
        "Where a load combination includes wind or seismic, US practice commonly "
        "permits a reduced factor of safety (or the equivalent one-third "
        "increase in allowable pressure). This tool does not apply that "
        "automatically - set the factor of safety deliberately for the case you "
        "are checking.",
        "Bearing capacity and settlement are both checked at SERVICE "
        "(unfactored) load. Do not enter factored loads.",
    ),
)

#: NBC 2020 Table 4.1.3.2 reduces, for dead plus live only, to these two cases.
_NBCC_COMBOS = (
    LoadCombination("1.4D", dead=1.4, live=0.0),
    LoadCombination("1.25D + 1.5L", dead=1.25, live=1.5),
)

CANADA_LSD = DesignCodeSpec(
    key="canada_lsd",
    name="Canada - Limit States Design",
    region="Canada",
    approach=Approach.LSD,
    resistance_factor=0.5,
    resistance_factor_sliding=0.8,
    combinations=_NBCC_COMBOS,
    counteracting=LoadCombination("0.9D + 1.5L", dead=0.9, live=1.5),
    settlement_limit=0.025,  # 25 mm
    citation=(
        "NBC 2020 Part 4 limit states design; geotechnical resistance factors "
        "after the Canadian Foundation Engineering Manual"
    ),
    notes=(
        "Geotechnical resistance factor Phi = 0.5 for bearing resistance of "
        "shallow foundations at ULS, and 0.8 for sliding, follow the Canadian "
        "Foundation Engineering Manual. Confirm against the edition your "
        "jurisdiction adopts.",
        "Load combinations are NBC 2020 Table 4.1.3.2, reduced to the dead and "
        "live cases: 1.4D and 1.25D + 1.5L. A full design must also consider "
        "snow, wind and seismic combinations, which this tool does not form.",
        "Provinces amend the NBC. Ontario (OBC), British Columbia, Alberta and "
        "Quebec all publish their own editions; verify factors and combinations "
        "against the code actually in force for the site.",
        "Serviceability (settlement) is checked at UNFACTORED load, per NBC "
        "4.2.4. Only the ULS bearing check uses factored loads.",
    ),
)

CODES: dict[str, DesignCodeSpec] = {c.key: c for c in (US_ASD, CANADA_LSD)}


def get_code(key: str) -> DesignCodeSpec:
    if key not in CODES:
        raise ValueError(f"Unknown design code {key!r}; use one of {sorted(CODES)}.")
    return CODES[key]


@dataclass
class UlsCheck:
    """Result of the ultimate limit state bearing check, with the arithmetic
    exposed so the sheet can show how demand and capacity were formed."""

    approach: Approach
    demand: float          # bearing pressure being checked [kPa]
    capacity: float        # available resistance [kPa]
    combination: str       # "service" for ASD, else the governing combination
    factor_label: str      # "FS = 3.0" or "Phi = 0.5"
    q_ult: float = 0.0     # gross ultimate bearing capacity [kPa]
    q_service: float = 0.0  # unfactored gross bearing pressure [kPa]
    warnings: list[str] = field(default_factory=list)

    @property
    def utilisation(self) -> float:
        return self.demand / self.capacity if self.capacity > 0 else float("inf")

    @property
    def ok(self) -> bool:
        return self.demand <= self.capacity

    @property
    def load_factor_ratio(self) -> float:
        """Factored pressure / service pressure. 1.0 under ASD."""
        return self.demand / self.q_service if self.q_service > 0 else 1.0

    @property
    def equivalent_global_fs(self) -> float:
        """The global factor of safety this check is equivalent to.

        Lets the two frameworks be compared on one axis. At the limit the
        capacity equals the demand, so the service pressure that just satisfies
        the check is ``capacity / lambda``, and

            FS_equivalent = q_ult / (capacity / lambda) = lambda / Phi

        for LSD, and exactly the stated FS for ASD. A Canadian LSD check with
        Phi = 0.5 on a dead-dominated column is NOT equivalent to FS = 2: the
        load factors carry most of the margin.
        """
        if self.capacity <= 0:
            return float("inf")
        return self.q_ult * self.load_factor_ratio / self.capacity
