"""Investment modelling for a land parcel.

Each revenue stream is gated on the physical preconditions actually required to
realise it, and scaled by the measured quality of the underlying resource. Three
principles keep the output honest:

1. Streams that depend on a third party deciding to act (a solar developer
   signing a lease, a carbon registry issuing credits) are probability-weighted
   and flagged speculative, because treating them as certain is how land
   pro-formas end up fictional.
2. Every stream is charged against the acres that can physically host it, taken
   from measured land cover. Billing row crop rent across a parcel that is two
   thirds forest is the single easiest way to manufacture a fake cap rate.
3. Streams that compete for the same acres do not both count. Only the strongest
   use of the forested portion, and of the open portion, survives.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import Config, clamp, default_config, interpolate
from ..models import BusinessCase, Listing, ParcelEnvironment, RevenueStream

# Streams competing for the same ground. Within a group only the strongest
# survives. Hunting, wind and recreation are absent deliberately: a hunting
# lease coexists with timber, and turbines occupy roughly 2% of the acres they
# sit on, so neither displaces another use.
EXCLUSIVE_GROUPS = (
    {"row_crop_lease", "solar_lease", "grazing"},  # the open portion
    {"timber", "carbon"},  # the forested portion
)

# NLCD groupings used to split a parcel into usable portions.
FOREST_COVERS = ("deciduous_forest", "evergreen_forest", "mixed_forest")
# Cropping requires soil, so shrubland is excluded here but allowed for grazing.
CROPPABLE_COVERS = ("cultivated_crops", "pasture_hay", "grassland")
RANGE_COVERS = (*CROPPABLE_COVERS, "shrub_scrub", "dwarf_scrub", "barren", "sedge")


@dataclass(frozen=True)
class AcreAllocation:
    """How many acres can physically host each class of use."""

    total: float
    forest: float
    croppable: float
    rangeland: float

    @classmethod
    def from_environment(
        cls, acres: float, env: ParcelEnvironment
    ) -> AcreAllocation:
        cover = env.land_cover
        if cover:
            forest = acres * cls._share(cover, FOREST_COVERS)
            # Woody wetland carries timber but is not reliably harvestable.
            forest += acres * cover.get("woody_wetlands", 0.0) / 100.0 * 0.5
            croppable = acres * cls._share(cover, CROPPABLE_COVERS)
            rangeland = acres * cls._share(cover, RANGE_COVERS)
            return cls(
                total=acres,
                forest=min(acres, forest),
                croppable=min(acres, croppable),
                rangeland=min(acres, rangeland),
            )

        # Without land cover, fall back to the forest-cover measurement and
        # treat the remainder as open ground.
        if env.forest_cover_pct.is_usable:
            forest = acres * env.forest_cover_pct.value / 100.0
            open_acres = max(0.0, acres - forest)
            return cls(
                total=acres, forest=forest, croppable=open_acres, rangeland=open_acres
            )

        return cls(total=acres, forest=0.0, croppable=0.0, rangeland=0.0)

    @staticmethod
    def _share(cover: dict[str, float], keys: tuple[str, ...]) -> float:
        return sum(cover.get(key, 0.0) for key in keys) / 100.0


class BusinessModeler:
    def __init__(self, config: Config | None = None) -> None:
        self.config = config or default_config()

    def model(self, listing: Listing, env: ParcelEnvironment) -> BusinessCase:
        acres = listing.acres or 0.0
        if acres <= 0 or listing.price <= 0:
            return BusinessCase()

        allocation = AcreAllocation.from_environment(acres, env)
        candidates = [
            self._timber(env, allocation),
            self._row_crop(env, allocation),
            self._grazing(env, allocation),
            self._solar(env, allocation),
            self._wind(env, allocation),
            self._hunting(env, allocation),
            self._carbon(env, allocation),
            self._recreation(env, allocation),
        ]
        streams = self._resolve_exclusivity([s for s in candidates if s])
        return self._finance(listing, streams)

    # ------------------------------------------------------------------
    # Revenue streams
    # ------------------------------------------------------------------

    def _timber(
        self, env: ParcelEnvironment, alloc: AcreAllocation
    ) -> RevenueStream | None:
        cfg = self.config.revenue_model("timber")
        if not cfg.get("enabled"):
            return None
        cover = env.forest_cover_pct
        if not cover.is_usable or cover.value < cfg["min_forest_cover_pct"]:
            return None
        if alloc.forest <= 0:
            return None

        # Sustainable annual increment per forested acre, scaled by site
        # productivity (moisture and heat). Stocking is already captured by
        # charging only the forested acres.
        productivity = self._site_productivity(env)
        mbf = cfg["max_mbf_per_acre_year"] * productivity
        gross = mbf * cfg["stumpage_price_per_mbf"] * alloc.forest
        if gross <= 0:
            return None

        return RevenueStream(
            name="timber",
            annual_gross=gross,
            annual_net=gross * (1 - cfg["opex_ratio"]),
            rationale=(
                f"{alloc.forest:.0f} forested acres at {mbf:.2f} MBF/acre/yr "
                f"sustainable increment, ${cfg['stumpage_price_per_mbf']}/MBF stumpage"
            ),
        )

    def _row_crop(
        self, env: ParcelEnvironment, alloc: AcreAllocation
    ) -> RevenueStream | None:
        cfg = self.config.revenue_model("row_crop_lease")
        if not cfg.get("enabled"):
            return None
        nccpi, slope = env.nccpi, env.slope_pct
        if not nccpi.is_usable or nccpi.value < cfg["min_nccpi"]:
            return None
        if slope.is_usable and slope.value > cfg["max_slope_pct"]:
            return None
        if alloc.croppable <= 0:
            return None

        # Cash rent tracks productivity closely; NCCPI is scaled across the
        # qualifying band rather than used raw.
        span = max(1e-6, 1.0 - cfg["min_nccpi"])
        quality = (nccpi.value - cfg["min_nccpi"]) / span
        rent = cfg["max_rent_per_acre"] * (0.35 + 0.65 * quality)
        gross = rent * alloc.croppable

        return RevenueStream(
            name="row_crop_lease",
            annual_gross=gross,
            annual_net=gross * (1 - cfg["opex_ratio"]),
            rationale=(
                f"NCCPI {nccpi.value:.2f} supports ~${rent:.0f}/acre cash rent "
                f"on {alloc.croppable:.0f} croppable acres"
            ),
        )

    def _grazing(
        self, env: ParcelEnvironment, alloc: AcreAllocation
    ) -> RevenueStream | None:
        cfg = self.config.revenue_model("grazing")
        if not cfg.get("enabled"):
            return None
        precip = env.precipitation_mm
        if not precip.is_usable or precip.value < cfg["min_precipitation_mm"]:
            return None
        if env.slope_pct.is_usable and env.slope_pct.value > cfg["max_slope_pct"]:
            return None
        if alloc.rangeland <= 0:
            return None

        # Forage production is close to linear in growing-season moisture across
        # the rangeland band; 900mm is treated as the point of full stocking.
        forage = clamp(precip.value / 900.0, 0.0, 1.0)
        aum = cfg["max_aum_per_acre"] * forage
        gross = aum * cfg["price_per_aum"] * alloc.rangeland
        if gross <= 0:
            return None

        return RevenueStream(
            name="grazing",
            annual_gross=gross,
            annual_net=gross * (1 - cfg["opex_ratio"]),
            rationale=(
                f"{precip.value:.0f} mm/yr supports ~{aum:.2f} AUM/acre "
                f"on {alloc.rangeland:.0f} grazeable acres at "
                f"${cfg['price_per_aum']}/AUM"
            ),
        )

    def _solar(
        self, env: ParcelEnvironment, alloc: AcreAllocation
    ) -> RevenueStream | None:
        cfg = self.config.revenue_model("solar_lease")
        if not cfg.get("enabled"):
            return None
        ghi = env.solar_ghi
        if not ghi.is_usable or ghi.value < cfg["min_ghi"]:
            return None
        # Developers need contiguous open ground, not total deeded acres.
        usable = alloc.rangeland
        if usable < cfg["min_acres"]:
            return None
        if env.slope_pct.is_usable and env.slope_pct.value > cfg["max_slope_pct"]:
            return None

        probability = cfg["probability"]
        note = ""
        grid = env.grid_distance_km
        if grid.is_usable:
            if grid.value > cfg["max_grid_distance_km"]:
                return None
        else:
            # Interconnection proximity dominates whether a lease ever happens.
            # Without it the stream is kept but heavily discounted, and the
            # report tells the reader to verify it.
            probability *= 0.5
            note = "; grid proximity unverified"

        gross = cfg["rent_per_acre"] * usable * probability
        return RevenueStream(
            name="solar_lease",
            annual_gross=gross,
            annual_net=gross,  # a ground lease carries no operating cost to the owner
            rationale=(
                f"{ghi.value:.2f} kWh/m2/day irradiance on {usable:.0f} open acres, "
                f"${cfg['rent_per_acre']}/acre lease at {probability * 100:.0f}% "
                f"probability{note}"
            ),
            probability=probability,
            speculative=True,
        )

    def _wind(
        self, env: ParcelEnvironment, alloc: AcreAllocation
    ) -> RevenueStream | None:
        cfg = self.config.revenue_model("wind_lease")
        if not cfg.get("enabled"):
            return None
        wind = env.wind_ws50m
        if not wind.is_usable or wind.value < cfg["min_ws50m"]:
            return None

        # Turbines occupy a small footprint, so they can share the parcel with
        # another use; spacing is what limits the count.
        turbines = alloc.total / cfg["acres_per_turbine"]
        if turbines < 1:
            return None

        gross = (
            int(turbines) * cfg["royalty_per_turbine_year"] * cfg["probability"]
        )
        return RevenueStream(
            name="wind_lease",
            annual_gross=gross,
            annual_net=gross,
            rationale=(
                f"{wind.value:.2f} m/s at 50 m supports ~{int(turbines)} turbine "
                f"site(s) at ${cfg['royalty_per_turbine_year']:,}/yr royalty, "
                f"{cfg['probability'] * 100:.0f}% probability"
            ),
            probability=cfg["probability"],
            speculative=True,
        )

    def _hunting(
        self, env: ParcelEnvironment, alloc: AcreAllocation
    ) -> RevenueStream | None:
        cfg = self.config.revenue_model("hunting_lease")
        if not cfg.get("enabled"):
            return None
        cover = env.forest_cover_pct
        if not cover.is_usable or cover.value < cfg["min_forest_cover_pct"]:
            return None
        if alloc.total < cfg["min_acres"]:
            return None

        # A hunting lease covers the whole parcel: game moves across it, and it
        # coexists with timber or grazing rather than displacing them.
        quality = 0.5 + 0.5 * (cover.value / 100.0)
        if env.water_distance_m.is_usable and env.water_distance_m.value < 1500:
            quality = min(1.0, quality * 1.15)

        rent = cfg["max_rent_per_acre"] * quality
        gross = rent * alloc.total
        return RevenueStream(
            name="hunting_lease",
            annual_gross=gross,
            annual_net=gross * (1 - cfg["opex_ratio"]),
            rationale=(
                f"{cover.value:.0f}% cover on {alloc.total:.0f} acres supports "
                f"~${rent:.0f}/acre recreational lease"
            ),
        )

    def _carbon(
        self, env: ParcelEnvironment, alloc: AcreAllocation
    ) -> RevenueStream | None:
        cfg = self.config.revenue_model("carbon")
        if not cfg.get("enabled"):
            return None
        cover = env.forest_cover_pct
        if not cover.is_usable or cover.value < cfg["min_forest_cover_pct"]:
            return None
        if alloc.forest <= 0:
            return None

        productivity = self._site_productivity(env)
        tonnes = cfg["tonnes_co2_per_acre_year"] * productivity
        gross = (
            tonnes * cfg["price_per_tonne"] * alloc.forest * cfg["probability"]
        )
        if gross <= 0:
            return None

        return RevenueStream(
            name="carbon",
            annual_gross=gross,
            annual_net=gross * (1 - cfg["opex_ratio"]),
            rationale=(
                f"~{tonnes:.2f} tCO2e/acre/yr across {alloc.forest:.0f} forested "
                f"acres at ${cfg['price_per_tonne']}/t, "
                f"{cfg['probability'] * 100:.0f}% probability of a viable "
                "registry project"
            ),
            probability=cfg["probability"],
            speculative=True,
        )

    def _recreation(
        self, env: ParcelEnvironment, alloc: AcreAllocation
    ) -> RevenueStream | None:
        cfg = self.config.revenue_model("recreation")
        if not cfg.get("enabled"):
            return None
        scenery = self.scenery_score(env)
        if scenery < cfg["min_scenery_score"]:
            return None

        town = env.town_distance_km
        probability = cfg["probability"]
        note = ""
        if town.is_usable:
            if town.value > cfg["max_town_distance_km"]:
                return None
        else:
            probability *= 0.6
            note = "; travel-market access unverified"

        # Only a small share of a parcel can be developed for lodging, so the
        # per-acre figure is applied to the whole parcel at low intensity.
        revenue = cfg["max_revenue_per_acre"] * (scenery / 100.0)
        gross = revenue * alloc.total * probability
        return RevenueStream(
            name="recreation",
            annual_gross=gross,
            annual_net=gross * (1 - cfg["opex_ratio"]),
            rationale=(
                f"scenery score {scenery:.0f}/100 supports agritourism or "
                f"glamping at {probability * 100:.0f}% probability{note}"
            ),
            probability=probability,
            speculative=True,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def scenery_score(env: ParcelEnvironment) -> float:
        """Relief, forest and water presence as a proxy for scenic appeal.

        These are the three attributes that consistently drive recreational and
        cabin-site demand for rural land.
        """
        parts: list[tuple[float, float]] = []
        if env.relief_m.is_usable:
            # 150m of local relief within a parcel reads as dramatic terrain.
            parts.append((clamp(env.relief_m.value / 150.0 * 100.0), 0.4))
        if env.forest_cover_pct.is_usable:
            parts.append((env.forest_cover_pct.value, 0.35))
        if env.water_distance_m.is_usable:
            parts.append((clamp(100.0 - env.water_distance_m.value / 30.0), 0.25))
        if not parts:
            return 0.0
        total = sum(w for _, w in parts)
        return sum(s * w for s, w in parts) / total

    @staticmethod
    def _site_productivity(env: ParcelEnvironment) -> float:
        """0-1 biological growth potential from moisture and heat."""
        factors: list[float] = []
        if env.precipitation_mm.is_usable:
            factors.append(clamp(env.precipitation_mm.value / 1100.0, 0.0, 1.0))
        if env.growing_degree_days.is_usable:
            factors.append(clamp(env.growing_degree_days.value / 2500.0, 0.0, 1.0))
        if not factors:
            return 0.5
        return sum(factors) / len(factors)

    @staticmethod
    def _resolve_exclusivity(streams: list[RevenueStream]) -> list[RevenueStream]:
        """Drop weaker streams that compete for the same acres."""
        by_name = {s.name: s for s in streams}
        dropped: set[str] = set()

        for group in EXCLUSIVE_GROUPS:
            present = [by_name[n] for n in group if n in by_name]
            if len(present) < 2:
                continue
            best = max(present, key=lambda s: s.annual_net)
            for stream in present:
                if stream.name != best.name:
                    dropped.add(stream.name)

        return [s for s in streams if s.name not in dropped]

    # ------------------------------------------------------------------
    # Finance
    # ------------------------------------------------------------------

    def _finance(self, listing: Listing, streams: list[RevenueStream]) -> BusinessCase:
        fin = self.config.finance
        price = listing.price

        gross = sum(s.annual_gross for s in streams)
        net_revenue = sum(s.annual_net for s in streams)
        opex = gross - net_revenue
        carrying = price * (
            fin["property_tax_rate"] + fin["insurance_and_admin_rate"]
        )
        noi = net_revenue - carrying

        # Carrying cost falls due whether or not the speculative income ever
        # arrives, so it is charged in full against the contracted figure too.
        contracted_noi = (
            sum(s.annual_net for s in streams if not s.speculative) - carrying
        )

        cap_rate = noi / price if price else 0.0
        contracted_cap_rate = contracted_noi / price if price else 0.0
        payback = price / noi if noi > 0 else None

        npv = self._npv(price, noi, fin)
        irr = self._irr(price, noi, fin)

        curve = self.config.section("cap_rate_normalisation")
        risk = self.config.section("return_risk_weighting") or {
            "contracted": 0.65,
            "total": 0.35,
        }
        score = risk["contracted"] * interpolate(curve, contracted_cap_rate) + risk[
            "total"
        ] * interpolate(curve, cap_rate)

        return BusinessCase(
            streams=streams,
            annual_gross_revenue=gross,
            annual_operating_expense=opex,
            annual_carrying_cost=carrying,
            net_operating_income=noi,
            contracted_noi=contracted_noi,
            cap_rate=cap_rate,
            contracted_cap_rate=contracted_cap_rate,
            payback_years=payback,
            npv=npv,
            irr=irr,
            score=clamp(score),
        )

    @staticmethod
    def _cashflows(price: float, noi: float, fin: dict) -> list[float]:
        """Purchase, annual NOI, and a sale at appreciated value on exit."""
        years = int(fin["hold_years"])
        flows = [-price * (1 + fin["transaction_cost_rate"])]
        flows.extend([noi] * years)
        exit_value = price * ((1 + fin["annual_appreciation"]) ** years)
        flows[-1] += exit_value * (1 - fin["transaction_cost_rate"])
        return flows

    def _npv(self, price: float, noi: float, fin: dict) -> float:
        rate = fin["discount_rate"]
        return sum(
            cf / ((1 + rate) ** t)
            for t, cf in enumerate(self._cashflows(price, noi, fin))
        )

    def _irr(self, price: float, noi: float, fin: dict) -> float | None:
        """Bisection on the discount rate. Robust enough for this cashflow shape.

        The flows here are a single outflow followed by inflows, so NPV is
        monotonically decreasing in the rate and bisection cannot land on a
        spurious root the way it can with sign-alternating flows.
        """
        flows = self._cashflows(price, noi, fin)

        def npv_at(rate: float) -> float:
            return sum(cf / ((1 + rate) ** t) for t, cf in enumerate(flows))

        low, high = -0.95, 2.0
        npv_low, npv_high = npv_at(low), npv_at(high)
        if npv_low * npv_high > 0:
            return None

        for _ in range(200):
            mid = (low + high) / 2
            value = npv_at(mid)
            if abs(value) < 1e-6:
                return mid
            if value > 0:
                low = mid
            else:
                high = mid
        return (low + high) / 2
