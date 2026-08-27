"""Markdown daily report.

The report is written to be actionable: every score is accompanied by the
measurement that produced it and the caveats that apply, so a reader can decide
whether to make a call rather than having to trust a number.
"""

from __future__ import annotations

from ..models import ScanReport, ScoredOpportunity

SUBSCORE_LABELS = {
    "water": "Water",
    "soil": "Soil",
    "timber": "Timber",
    "climate": "Climate",
    "solar": "Solar",
    "wind": "Wind",
    "resilience": "Resilience",
}


def _money(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"${value:,.0f}"


def _pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}%"


def render(report: ScanReport, top_n: int = 10) -> str:
    lines: list[str] = []
    stamp = report.generated_at.strftime("%Y-%m-%d %H:%M UTC")

    lines.append(f"# Land Opportunity Scan - {report.generated_at:%Y-%m-%d}")
    lines.append("")
    lines.append(
        f"Top {min(top_n, len(report.opportunities))} of "
        f"{report.listings_considered} listings screened. "
        f"{report.listings_enriched} received full enrichment."
    )
    lines.append("")
    lines.append(f"- Generated: {stamp}")
    lines.append(f"- Sources: {', '.join(report.sources_used) or 'none'}")
    lines.append("")

    if not report.opportunities:
        lines.append("## No qualifying opportunities")
        lines.append("")
        lines.append("No listings passed the screen in this run.")
        if report.warnings:
            lines.append("")
            lines.append("### Warnings")
            lines.extend(f"- {w}" for w in report.warnings)
        return "\n".join(lines)

    lines.append("## Summary")
    lines.append("")
    lines.append(
        "| # | Location | Price | Acres | $/acre | Score | Nat cap | Cap rate | IRR |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for opportunity in report.opportunities[:top_n]:
        listing = opportunity.listing
        location = ", ".join(p for p in (listing.city, listing.state) if p) or "unknown"
        acres = f"{listing.acres:,.0f}" if listing.acres else "n/a"
        cells = [
            str(opportunity.rank),
            location,
            _money(listing.price),
            acres,
            _money(listing.price_per_acre),
            f"**{opportunity.composite_score:.1f}**",
            f"{opportunity.natural_capital.total:.0f}",
            _pct(opportunity.business.cap_rate),
            _pct(opportunity.business.irr),
        ]
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")

    lines.append("## Detail")
    lines.append("")
    for opportunity in report.opportunities[:top_n]:
        lines.extend(_render_detail(opportunity))

    lines.append("## Method and caveats")
    lines.append("")
    lines.extend(_render_method())

    if report.warnings:
        lines.append("### Run warnings")
        lines.append("")
        lines.extend(f"- {w}" for w in report.warnings)
        lines.append("")

    return "\n".join(lines)


def _render_detail(opportunity: ScoredOpportunity) -> list[str]:
    listing = opportunity.listing
    env = opportunity.environment
    nc = opportunity.natural_capital
    business = opportunity.business

    location = ", ".join(p for p in (listing.city, listing.state) if p) or "unknown"
    lines: list[str] = []

    lines.append(f"### {opportunity.rank}. {location} - {_money(listing.price)}")
    lines.append("")

    acres = f"{listing.acres:,.1f} acres" if listing.acres else "acreage unknown"
    ppa = _money(listing.price_per_acre)
    lines.append(
        f"**{acres}** at **{ppa}/acre** | composite "
        f"**{opportunity.composite_score:.1f}/100** | natural capital "
        f"**{nc.total:.0f}/100** (confidence {nc.confidence:.0%})"
    )
    lines.append("")

    if listing.address:
        lines.append(f"- Address: {listing.address}")
    if listing.property_type:
        lines.append(f"- Type: {listing.property_type}")
    if listing.url:
        lines.append(f"- Listing: {listing.url}")
    if listing.description:
        lines.append(f"- Listed as: {listing.description}")
    lines.append("")

    lines.append("**Natural capital breakdown**")
    lines.append("")
    lines.append("| Component | Score | Weight | Evidence |")
    lines.append("|---|---|---|---|")
    for sub in nc.subscores:
        label = SUBSCORE_LABELS.get(sub.name, sub.name)
        if sub.confidence == 0:
            lines.append(f"| {label} | no data | {sub.weight:.0%} | - |")
            continue
        evidence = "; ".join(sub.drivers) if sub.drivers else "-"
        lines.append(
            f"| {label} | {sub.score:.0f} | {sub.weight:.0%} | {evidence} |"
        )
    lines.append("")

    if env.land_cover:
        cover = ", ".join(
            f"{name.replace('_', ' ')} {pct:.0f}%"
            for name, pct in list(env.land_cover.items())[:4]
        )
        lines.append(f"- Land cover: {cover}")
    if env.elevation_m.is_usable:
        relief = (
            f", {env.relief_m.value:.0f} m local relief"
            if env.relief_m.is_usable
            else ""
        )
        lines.append(f"- Elevation: {env.elevation_m.value:,.0f} m{relief}")
    lines.append("")

    lines.append("**Investment model**")
    lines.append("")
    if business.streams:
        lines.append("| Stream | Gross/yr | Net/yr | Basis |")
        lines.append("|---|---|---|---|")
        for stream in sorted(
            business.streams, key=lambda s: s.annual_net, reverse=True
        ):
            marker = " *(speculative)*" if stream.speculative else ""
            lines.append(
                f"| {stream.name.replace('_', ' ')}{marker} "
                f"| {_money(stream.annual_gross)} "
                f"| {_money(stream.annual_net)} "
                f"| {stream.rationale} |"
            )
        lines.append("")
    else:
        lines.append("No revenue stream met its physical preconditions.")
        lines.append("")

    lines.append(
        f"- Net operating income: **{_money(business.net_operating_income)}/yr** "
        f"(after {_money(business.annual_carrying_cost)} carrying cost)"
    )
    if any(s.speculative for s in business.streams):
        lines.append(
            f"- Excluding speculative streams: "
            f"**{_money(business.contracted_noi)}/yr** "
            f"({_pct(business.contracted_cap_rate)} cap rate)"
        )
    lines.append(f"- Cap rate: **{_pct(business.cap_rate)}**")
    if business.payback_years:
        lines.append(f"- Simple payback: {business.payback_years:.0f} years")
    lines.append(
        f"- 10-year NPV at 8%: {_money(business.npv)} | IRR: {_pct(business.irr)}"
    )
    lines.append("")

    if opportunity.flags:
        lines.append("**Risks and caveats**")
        lines.append("")
        lines.extend(f"- {flag}" for flag in opportunity.flags)
        lines.append("")

    lines.append("---")
    lines.append("")
    return lines


def _render_method() -> list[str]:
    return [
        "**Data sources.** Soil productivity (NCCPI), available water storage and "
        "slope from USDA NRCS SSURGO. Precipitation, temperature, growing degree "
        "days, solar irradiance and 50 m wind speed from NASA POWER climatology. "
        "Land cover from NLCD 2021. Surface water from the USGS National "
        "Hydrography Dataset. Flood zones from FEMA NFHL. Elevation from USGS 3DEP.",
        "",
        "**Wildfire hazard is modelled, not measured.** The USFS Wildfire Hazard "
        "Potential service refuses unauthenticated requests, so hazard class is "
        "derived from fuel type, aridity and slope. Treat it as a screening "
        "signal only.",
        "",
        "**Revenue figures are modelled, not quoted.** Lease rates, stumpage "
        "prices and carbon prices come from `config/scoring.yaml` and are "
        "national approximations. Streams marked speculative depend on a third "
        "party acting and are probability-weighted. Verify locally before "
        "committing capital.",
        "",
        "**What this screen cannot see.** Legal access and easements, mineral and "
        "water rights severance, title defects, zoning and permitted use, "
        "wetland delineation, utility availability, and parcel boundaries. "
        "Coordinates are treated as a point, so a large parcel's variability is "
        "approximated by sampling around that point.",
        "",
        "This is a screening tool for generating a shortlist. It is not an "
        "appraisal and not investment advice.",
        "",
    ]
