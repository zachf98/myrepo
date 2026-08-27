"""Climate, solar and wind resource from NASA POWER.

NASA POWER serves a 30+ year satellite and reanalysis climatology on a global
grid with no API key. One request returns everything needed for the water,
solar, wind and climate subscores, which keeps the per-parcel cost to a single
round trip.

Docs: https://power.larc.nasa.gov/docs/services/api/temporal/climatology/
"""

from __future__ import annotations

from ..models import DataQuality, Listing, Measurement, ParcelEnvironment
from .base import Enricher

POWER_URL = "https://power.larc.nasa.gov/api/temporal/climatology/point"

PARAMETERS = (
    "ALLSKY_SFC_SW_DWN",  # global horizontal irradiance, kWh/m2/day
    "WS50M",  # wind speed at 50m, m/s
    "PRECTOTCORR",  # bias-corrected precipitation, mm/day
    "T2M",  # mean air temperature at 2m, C
    "T2M_MIN",
)

MONTH_KEYS = (
    "JAN", "FEB", "MAR", "APR", "MAY", "JUN",
    "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
)
DAYS_IN_MONTH = (31, 28.25, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)

# POWER uses -999 as its fill value; treating it as data would be a silent bug.
FILL_VALUE = -900.0


def _clean(value: float | None) -> float | None:
    if value is None:
        return None
    return None if value <= FILL_VALUE else float(value)


class NasaPowerEnricher(Enricher):
    name = "nasa_power"

    def enrich(self, listing: Listing, env: ParcelEnvironment) -> None:
        payload = self.client.get_json(
            POWER_URL,
            params={
                "parameters": ",".join(PARAMETERS),
                "community": "RE",
                "latitude": round(listing.latitude, 4),
                "longitude": round(listing.longitude, 4),
                "format": "JSON",
            },
        )
        if not payload:
            env.failed_enrichers.append(self.name)
            return

        params = (payload.get("properties") or {}).get("parameter") or {}
        if not params:
            env.failed_enrichers.append(self.name)
            return

        source = "NASA POWER climatology"

        ghi = _clean((params.get("ALLSKY_SFC_SW_DWN") or {}).get("ANN"))
        if ghi is not None:
            env.solar_ghi = Measurement(
                value=ghi,
                unit="kWh/m2/day",
                source=source,
                quality=DataQuality.MODELED,
            )

        wind = _clean((params.get("WS50M") or {}).get("ANN"))
        if wind is not None:
            env.wind_ws50m = Measurement(
                value=wind, unit="m/s", source=source, quality=DataQuality.MODELED
            )

        # POWER reports precipitation as a daily mean per month; converting to an
        # annual total requires weighting each month by its length.
        precip = params.get("PRECTOTCORR") or {}
        monthly = [_clean(precip.get(m)) for m in MONTH_KEYS]
        if all(v is not None for v in monthly):
            annual_mm = sum(v * d for v, d in zip(monthly, DAYS_IN_MONTH, strict=True))
            env.precipitation_mm = Measurement(
                value=annual_mm,
                unit="mm/yr",
                source=source,
                quality=DataQuality.MODELED,
            )
        else:
            daily_ann = _clean(precip.get("ANN"))
            if daily_ann is not None:
                env.precipitation_mm = Measurement(
                    value=daily_ann * 365.25,
                    unit="mm/yr",
                    source=source,
                    quality=DataQuality.MODELED,
                    note="derived from annual daily mean",
                )

        temps = params.get("T2M") or {}
        mean_temp = _clean(temps.get("ANN"))
        if mean_temp is not None:
            env.mean_temp_c = Measurement(
                value=mean_temp, unit="C", source=source, quality=DataQuality.MODELED
            )

        gdd = self._growing_degree_days(temps)
        if gdd is not None:
            env.growing_degree_days = Measurement(
                value=gdd,
                unit="GDD base 10C",
                source=source,
                quality=DataQuality.MODELED,
                note="from monthly mean temperatures, base 10C",
            )

    @staticmethod
    def _growing_degree_days(temps: dict[str, float]) -> float | None:
        """Accumulate growing degree days from monthly means, base 10C.

        Monthly means understate GDD relative to a daily accumulation, but the
        measure is only used comparatively across parcels, so the bias is
        consistent and harmless.
        """
        monthly = [_clean(temps.get(m)) for m in MONTH_KEYS]
        if any(v is None for v in monthly):
            return None
        return sum(
            max(0.0, v - 10.0) * d for v, d in zip(monthly, DAYS_IN_MONTH, strict=True)
        )
