"""Self-contained HTML report, suitable for emailing or hosting."""

from __future__ import annotations

from jinja2 import Environment, select_autoescape

from ..models import ScanReport

TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Land Opportunity Scan {{ report.generated_at.strftime('%Y-%m-%d') }}</title>
<style>
  :root {
    --bg: #0f1211; --card: #181d1b; --line: #2a322e;
    --text: #e8ede9; --muted: #93a09a; --accent: #7fc99a; --warn: #e0a458;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 2rem 1rem; background: var(--bg); color: var(--text);
    font: 15px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  }
  .wrap { max-width: 1040px; margin: 0 auto; }
  h1 { font-size: 1.65rem; margin: 0 0 .35rem; letter-spacing: -.02em; }
  h2 { font-size: 1.15rem; margin: 2.5rem 0 1rem; color: var(--accent);
       border-bottom: 1px solid var(--line); padding-bottom: .4rem; }
  .sub { color: var(--muted); margin-bottom: 2rem; font-size: .9rem; }
  table { width: 100%; border-collapse: collapse; font-size: .88rem; }
  th, td { padding: .55rem .6rem; text-align: left; border-bottom: 1px solid var(--line); }
  th { color: var(--muted); font-weight: 600; text-transform: uppercase;
       font-size: .72rem; letter-spacing: .06em; }
  td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
  .card { background: var(--card); border: 1px solid var(--line);
          border-radius: 10px; padding: 1.25rem 1.4rem; margin-bottom: 1.25rem; }
  .card-head { display: flex; justify-content: space-between;
               align-items: baseline; gap: 1rem; flex-wrap: wrap; }
  .card-head h3 { margin: 0; font-size: 1.1rem; }
  .score { font-size: 1.55rem; font-weight: 700; color: var(--accent);
           font-variant-numeric: tabular-nums; }
  .meta { color: var(--muted); font-size: .87rem; margin: .35rem 0 1rem; }
  .bars { margin: 1rem 0; }
  .bar-row { display: grid; grid-template-columns: 5.5rem 1fr 2.6rem;
             align-items: center; gap: .6rem; margin-bottom: .3rem;
             font-size: .82rem; }
  .bar { background: #232a26; border-radius: 3px; height: 9px; overflow: hidden; }
  .bar span { display: block; height: 100%; background: var(--accent); }
  .bar-label { color: var(--muted); }
  .bar-val { text-align: right; font-variant-numeric: tabular-nums; }
  .evidence { color: var(--muted); font-size: .82rem; margin: .1rem 0 .8rem 5.5rem; }
  .flags { background: #241f18; border-left: 3px solid var(--warn);
           padding: .7rem .9rem; border-radius: 4px; margin-top: 1rem; }
  .flags ul { margin: 0; padding-left: 1.1rem; }
  .flags li { color: #f0d5b0; font-size: .85rem; }
  .spec { color: var(--warn); font-size: .78rem; }
  .method { color: var(--muted); font-size: .84rem; }
  .method p { margin: .6rem 0; }
  a { color: var(--accent); }
</style>
</head>
<body>
<div class="wrap">
  <h1>Land Opportunity Scan</h1>
  <div class="sub">
    {{ report.generated_at.strftime('%A %d %B %Y, %H:%M UTC') }} &middot;
    top {{ report.opportunities|length }} of {{ report.listings_considered }}
    listings screened &middot; {{ report.listings_enriched }} fully enriched &middot;
    sources: {{ report.sources_used|join(', ') or 'none' }}
  </div>

  {% if not report.opportunities %}
    <div class="card"><p>No listings passed the screen in this run.</p></div>
  {% else %}
  <h2>Summary</h2>
  <table>
    <thead><tr>
      <th class="num">#</th><th>Location</th><th class="num">Price</th>
      <th class="num">Acres</th><th class="num">$/acre</th>
      <th class="num">Score</th><th class="num">Nat cap</th>
      <th class="num">Cap rate</th><th class="num">IRR</th>
    </tr></thead>
    <tbody>
    {% for o in report.opportunities %}
      <tr>
        <td class="num">{{ o.rank }}</td>
        <td>{{ [o.listing.city, o.listing.state]|select|join(', ') or 'unknown' }}</td>
        <td class="num">{{ money(o.listing.price) }}</td>
        <td class="num">{{ '%.0f'|format(o.listing.acres) if o.listing.acres else 'n/a' }}</td>
        <td class="num">{{ money(o.listing.price_per_acre) }}</td>
        <td class="num"><strong>{{ '%.1f'|format(o.composite_score) }}</strong></td>
        <td class="num">{{ '%.0f'|format(o.natural_capital.total) }}</td>
        <td class="num">{{ pct(o.business.cap_rate) }}</td>
        <td class="num">{{ pct(o.business.irr) }}</td>
      </tr>
    {% endfor %}
    </tbody>
  </table>

  <h2>Detail</h2>
  {% for o in report.opportunities %}
  <div class="card">
    <div class="card-head">
      <h3>{{ o.rank }}. {{ [o.listing.city, o.listing.state]|select|join(', ') or 'unknown' }}
        &mdash; {{ money(o.listing.price) }}</h3>
      <div class="score">{{ '%.1f'|format(o.composite_score) }}</div>
    </div>
    <div class="meta">
      {{ '%.1f'|format(o.listing.acres) if o.listing.acres else '?' }} acres at
      {{ money(o.listing.price_per_acre) }}/acre &middot;
      natural capital {{ '%.0f'|format(o.natural_capital.total) }}/100
      (confidence {{ '%.0f'|format(o.natural_capital.confidence * 100) }}%)
      {%- if o.listing.url %} &middot; <a href="{{ o.listing.url }}">listing</a>{% endif %}
      {%- if o.environment.soil_description %}<br>{{ o.environment.soil_description }}{% endif %}
    </div>

    <div class="bars">
    {% for s in o.natural_capital.subscores %}
      <div class="bar-row">
        <div class="bar-label">{{ s.name }}</div>
        {% set shown = s.score if s.confidence > 0 else 0 %}
        <div class="bar"><span style="width: {{ '%.0f'|format(shown) }}%"></span></div>
        <div class="bar-val">{{ '%.0f'|format(s.score) if s.confidence > 0 else '--' }}</div>
      </div>
      {% if s.drivers %}<div class="evidence">{{ s.drivers|join('; ') }}</div>{% endif %}
    {% endfor %}
    </div>

    {% if o.business.streams %}
    <table>
      <thead><tr><th>Revenue stream</th><th class="num">Gross/yr</th>
        <th class="num">Net/yr</th><th>Basis</th></tr></thead>
      <tbody>
      {% for st in o.business.streams|sort(attribute='annual_net', reverse=true) %}
        <tr>
          <td>{{ st.name.replace('_', ' ') }}
            {%- if st.speculative %} <span class="spec">speculative</span>{% endif %}</td>
          <td class="num">{{ money(st.annual_gross) }}</td>
          <td class="num">{{ money(st.annual_net) }}</td>
          <td>{{ st.rationale }}</td>
        </tr>
      {% endfor %}
      </tbody>
    </table>
    {% else %}
    <p class="meta">No revenue stream met its physical preconditions.</p>
    {% endif %}

    <div class="meta" style="margin-top:1rem">
      NOI <strong>{{ money(o.business.net_operating_income) }}/yr</strong> after
      {{ money(o.business.annual_carrying_cost) }} carrying cost &middot;
      cap rate <strong>{{ pct(o.business.cap_rate) }}</strong>
      {%- if o.business.streams|selectattr('speculative')|list %} &middot;
        excluding speculative
        {{ money(o.business.contracted_noi) }}/yr
        ({{ pct(o.business.contracted_cap_rate) }}){% endif %} &middot;
      10-yr NPV {{ money(o.business.npv) }} &middot; IRR {{ pct(o.business.irr) }}
      {%- if o.business.payback_years %} &middot;
        payback {{ '%.0f'|format(o.business.payback_years) }} yrs{% endif %}
    </div>

    {% if o.flags %}
    <div class="flags"><ul>
      {% for f in o.flags %}<li>{{ f }}</li>{% endfor %}
    </ul></div>
    {% endif %}
  </div>
  {% endfor %}
  {% endif %}

  <h2>Method and caveats</h2>
  <div class="method">
    <p><strong>Data sources.</strong> Soil productivity (NCCPI), available water
    storage and slope from USDA NRCS SSURGO. Precipitation, temperature, growing
    degree days, solar irradiance and 50 m wind speed from NASA POWER
    climatology. Land cover from NLCD 2021. Surface water from the USGS National
    Hydrography Dataset. Flood zones from FEMA NFHL. Elevation from USGS 3DEP.</p>
    <p><strong>Wildfire hazard is modelled, not measured.</strong> The USFS
    Wildfire Hazard Potential service refuses unauthenticated requests, so hazard
    class is derived from fuel type, aridity and slope.</p>
    <p><strong>Revenue figures are modelled, not quoted.</strong> Lease rates,
    stumpage and carbon prices are national approximations from
    <code>config/scoring.yaml</code>. Streams marked speculative depend on a
    third party acting and are probability-weighted.</p>
    <p><strong>Not visible to this screen:</strong> legal access and easements,
    mineral and water rights severance, title, zoning and permitted use, wetland
    delineation, utilities, and true parcel boundaries.</p>
    <p>A screening tool for building a shortlist. Not an appraisal, not
    investment advice.</p>
    {% if report.warnings %}
    <p><strong>Run warnings:</strong></p>
    <ul>{% for w in report.warnings %}<li>{{ w }}</li>{% endfor %}</ul>
    {% endif %}
  </div>
</div>
</body>
</html>
"""


def _money(value: float | None) -> str:
    return "n/a" if value is None else f"${value:,.0f}"


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def render(report: ScanReport) -> str:
    env = Environment(autoescape=select_autoescape(["html"]))
    env.filters["select"] = lambda seq: [item for item in seq if item]
    template = env.from_string(TEMPLATE)
    return template.render(report=report, money=_money, pct=_pct)
