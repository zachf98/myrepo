"""Command line interface."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from .config import load_config
from .http import CachedClient
from .models import ScanReport
from .pipeline import ScanPipeline
from .report import render_csv, render_html, render_json, render_markdown
from .sources import available_sources, build_source

app = typer.Typer(
    add_completion=False,
    help="Scan US land listings for natural capital and investment upside.",
)
console = Console()


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True, show_path=False)],
    )
    # httpx logs every request at INFO, which drowns out everything else.
    logging.getLogger("httpx").setLevel(logging.WARNING)


def _print_table(report: ScanReport) -> None:
    table = Table(title=f"Top opportunities - {report.generated_at:%Y-%m-%d}")
    table.add_column("#", justify="right")
    table.add_column("Location")
    table.add_column("Price", justify="right")
    table.add_column("Acres", justify="right")
    table.add_column("$/ac", justify="right")
    table.add_column("Score", justify="right", style="bold green")
    table.add_column("NatCap", justify="right")
    table.add_column("Cap", justify="right")
    table.add_column("Streams")

    for o in report.opportunities:
        listing = o.listing
        table.add_row(
            str(o.rank),
            ", ".join(p for p in (listing.city, listing.state) if p) or "?",
            f"${listing.price:,.0f}",
            f"{listing.acres:,.0f}" if listing.acres else "n/a",
            f"${listing.price_per_acre:,.0f}" if listing.price_per_acre else "n/a",
            f"{o.composite_score:.1f}",
            f"{o.natural_capital.total:.0f}",
            f"{o.business.cap_rate * 100:.1f}%",
            ", ".join(s.name.replace("_", " ") for s in o.business.streams) or "-",
        )
    console.print(table)


@app.command()
def scan(
    source: Annotated[
        list[str],
        typer.Option(
            "--source",
            "-s",
            help=f"Listing source(s). Available: {', '.join(available_sources())}",
        ),
    ] = None,
    top: Annotated[int, typer.Option("--top", "-n", help="How many to report")] = 10,
    limit: Annotated[
        int, typer.Option("--limit", help="Max listings to pull per source")
    ] = 500,
    prescreen: Annotated[
        int,
        typer.Option(
            "--prescreen",
            help="Listings kept for full enrichment after the cheap pass",
        ),
    ] = 60,
    out_dir: Annotated[
        Path, typer.Option("--out", help="Directory for report files")
    ] = Path("reports"),
    formats: Annotated[
        str, typer.Option("--formats", help="Comma-separated: md,html,json,csv")
    ] = "md,html,json",
    config_path: Annotated[
        Path | None, typer.Option("--config", help="Path to scoring.yaml")
    ] = None,
    no_cache: Annotated[
        bool, typer.Option("--no-cache", help="Bypass the HTTP cache")
    ] = False,
    workers: Annotated[
        int, typer.Option("--workers", help="Parallel enrichment workers")
    ] = 4,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Run a scan and write the daily report."""
    _setup_logging(verbose)
    sources = source or ["fixtures"]
    config = load_config(config_path)

    with CachedClient(use_cache=not no_cache) as client:
        try:
            built = [build_source(name, client) for name in sources]
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(code=2) from exc

        unavailable = [s.name for s in built if not s.is_available()]
        if unavailable and len(unavailable) == len(built):
            console.print(
                f"[yellow]No configured source is available "
                f"({', '.join(unavailable)}).[/yellow]\n"
                "Set credentials, or use --source fixtures to exercise the "
                "pipeline. See the README for how to obtain listing access."
            )

        pipeline = ScanPipeline(
            client,
            built,
            config=config,
            prescreen_keep=prescreen,
            max_workers=workers,
        )
        console.print(f"[cyan]Scanning[/cyan] sources: {', '.join(sources)}")
        report = pipeline.run(top_n=top, limit=limit)
        console.print(
            f"[dim]HTTP: {client.stats['hits']} cached, "
            f"{client.stats['misses']} fetched, "
            f"{client.stats['errors']} failed[/dim]"
        )

    _print_table(report)
    for warning in report.warnings:
        console.print(f"[yellow]warning:[/yellow] {warning}")

    written = _write_reports(report, out_dir, formats, top)
    for path in written:
        console.print(f"[green]wrote[/green] {path}")


def _write_reports(
    report: ScanReport, out_dir: Path, formats: str, top: int
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = report.generated_at.strftime("%Y-%m-%d")
    written: list[Path] = []

    renderers = {
        "md": lambda: render_markdown(report, top_n=top),
        "html": lambda: render_html(report),
        "json": lambda: render_json(report),
        "csv": lambda: render_csv(report),
    }

    for fmt in (f.strip() for f in formats.split(",")):
        if not fmt:
            continue
        if fmt not in renderers:
            console.print(f"[yellow]unknown format {fmt!r}, skipping[/yellow]")
            continue
        path = out_dir / f"scan-{stamp}.{fmt}"
        path.write_text(renderers[fmt]())
        written.append(path)

        # A stable filename makes it easy to link to "today's report".
        latest = out_dir / f"latest.{fmt}"
        latest.write_text(path.read_text())
        written.append(latest)

    return written


@app.command()
def sources() -> None:
    """List listing sources and whether each is configured."""
    with CachedClient() as client:
        table = Table(title="Listing sources")
        table.add_column("Name")
        table.add_column("Configured")
        table.add_column("Notes")
        notes = {
            "fixtures": "Synthetic listings at real coordinates; always available",
            "bridge": "Zillow Group / Bridge Interactive; needs BRIDGE_API_TOKEN",
            "reso": "Any RESO Web API feed; needs RESO_BASE_URL + RESO_ACCESS_TOKEN",
        }
        for name in available_sources():
            source_obj = build_source(name, client)
            ok = source_obj.is_available()
            table.add_row(
                name,
                "[green]yes[/green]" if ok else "[red]no[/red]",
                notes.get(name, ""),
            )
        console.print(table)


@app.command()
def explain(
    latitude: Annotated[float, typer.Argument(help="Parcel latitude")],
    longitude: Annotated[float, typer.Argument(help="Parcel longitude")],
    price: Annotated[float, typer.Option("--price", help="Asking price")] = 150000,
    acres: Annotated[float, typer.Option("--acres", help="Parcel acreage")] = 100,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Score a single parcel by coordinate. Useful for spot-checking the model."""
    _setup_logging(verbose)
    from .enrich import EnrichmentPipeline
    from .models import Listing
    from .scoring import BusinessModeler, CompositeScorer, NaturalCapitalScorer

    listing = Listing(
        listing_id="manual",
        source="manual",
        price=price,
        acres=acres,
        latitude=latitude,
        longitude=longitude,
    )

    with CachedClient() as client:
        env = EnrichmentPipeline(client).enrich_one(listing)

    nc = NaturalCapitalScorer().score(env)
    business = BusinessModeler().model(listing, env)
    ranked = CompositeScorer().rank([(listing, env, nc, business)])
    opportunity = ranked[0]

    console.print(
        f"\n[bold]Natural capital: {nc.total:.1f}/100[/bold] "
        f"(confidence {nc.confidence:.0%})"
    )
    for sub in nc.subscores:
        if sub.confidence == 0:
            console.print(f"  {sub.name:12s} [dim]no data[/dim]")
            continue
        console.print(
            f"  {sub.name:12s} {sub.score:5.1f}  w={sub.weight:.0%}  "
            f"[dim]{'; '.join(sub.drivers)}[/dim]"
        )

    console.print(f"\n[bold]Investment model[/bold] on ${price:,.0f} / {acres} acres")
    for stream in sorted(business.streams, key=lambda s: s.annual_net, reverse=True):
        tag = " [yellow](speculative)[/yellow]" if stream.speculative else ""
        console.print(
            f"  {stream.name:16s} ${stream.annual_net:>10,.0f}/yr{tag}\n"
            f"      [dim]{stream.rationale}[/dim]"
        )
    irr = f"{business.irr * 100:.1f}%" if business.irr is not None else "n/a"
    console.print(
        f"\n  NOI ${business.net_operating_income:,.0f}/yr  "
        f"cap {business.cap_rate * 100:.1f}%  IRR {irr}"
    )
    if opportunity.flags:
        console.print("\n[yellow]Flags[/yellow]")
        for flag in opportunity.flags:
            console.print(f"  - {flag}")


if __name__ == "__main__":
    app()
