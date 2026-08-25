/* =============================================================
   Fantasy Football League Manager Portal
   Central data fetcher + lightweight page router
   -------------------------------------------------------------
   Every page loads this one file. On DOM ready we read
   <body data-page="..."> and run the matching renderer against
   the data parsed from data.json.
   ============================================================= */

const DATA_URL = 'data.json';

/* Cached payload so repeated calls never refetch within a page load. */
let leagueDataCache = null;

document.addEventListener('DOMContentLoaded', () => {
  setupNavigation();
  stampCurrentYear();
  bootPage();
});

/* -------------------------------------------------------------
   Data layer
   ------------------------------------------------------------- */

async function loadLeagueData() {
  if (leagueDataCache) return leagueDataCache;

  if (window.location.protocol === 'file:') {
    throw new Error(
      'Browsers block fetch() on file:// URLs. Serve this folder over HTTP instead, ' +
        'for example: python3 -m http.server 8000'
    );
  }

  const response = await fetch(DATA_URL, { cache: 'no-store' });
  if (!response.ok) {
    throw new Error(`Could not load ${DATA_URL} (HTTP ${response.status} ${response.statusText}).`);
  }

  let parsed;
  try {
    parsed = await response.json();
  } catch (error) {
    throw new Error(`${DATA_URL} is not valid JSON. Check for a stray comma or missing quote.`);
  }

  leagueDataCache = normalizeData(parsed);
  return leagueDataCache;
}

/* Guarantees every collection exists as an array so renderers
   never have to defend against a missing key. */
function normalizeData(raw) {
  const data = raw && typeof raw === 'object' ? raw : {};
  return {
    league: data.league && typeof data.league === 'object' ? data.league : {},
    announcements: asArray(data.announcements),
    deadlines: asArray(data.deadlines),
    powerRankings: asArray(data.powerRankings),
    history: asArray(data.history)
  };
}

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

/* -------------------------------------------------------------
   Router
   ------------------------------------------------------------- */

async function bootPage() {
  const page = document.body.dataset.page || 'dashboard';

  try {
    const data = await loadLeagueData();
    applyLeagueBranding(data.league);

    if (page === 'dashboard') {
      renderAnnouncements(data.announcements);
      renderDeadlines(data.deadlines);
    } else if (page === 'rankings') {
      renderPowerRankings(data.powerRankings);
    } else if (page === 'history') {
      renderHistory(data.history);
    }
  } catch (error) {
    console.error('[League Portal]', error);
    showLoadError(error.message);
  }
}

/* -------------------------------------------------------------
   Shared chrome: nav, branding, footer
   ------------------------------------------------------------- */

function setupNavigation() {
  const page = document.body.dataset.page;

  document.querySelectorAll('[data-nav]').forEach((link) => {
    const isActive = link.dataset.nav === page;
    link.classList.toggle('nav-link-active', isActive);
    if (isActive) {
      link.setAttribute('aria-current', 'page');
    } else {
      link.removeAttribute('aria-current');
    }
  });

  const toggle = document.getElementById('nav-toggle');
  const menu = document.getElementById('nav-menu');
  if (!toggle || !menu) return;

  toggle.addEventListener('click', () => {
    const isHidden = menu.classList.toggle('hidden');
    toggle.setAttribute('aria-expanded', String(!isHidden));
  });
}

function applyLeagueBranding(league) {
  setText('[data-league-name]', league.name);
  setText('[data-league-tagline]', league.tagline);
  setText('[data-league-season]', league.season);
  setText('[data-league-teams]', league.teamCount);
  setText('[data-league-playoff-teams]', league.playoffTeams);
  setText('[data-league-commissioner]', league.commissioner);

  if (league.name) {
    document.title = `${document.title.split(' | ')[0]} | ${league.name}`;
  }

  if (league.espnLeagueUrl) {
    document.querySelectorAll('[data-espn-link]').forEach((link) => {
      link.href = league.espnLeagueUrl;
    });
  }
}

function stampCurrentYear() {
  setText('[data-current-year]', new Date().getFullYear());
}

function showLoadError(message) {
  document.querySelectorAll('[data-loading]').forEach(hide);

  const banner = document.getElementById('error-banner');
  const target = document.getElementById('error-message');
  if (target) target.textContent = message;
  if (banner) show(banner);
}

/* -------------------------------------------------------------
   Page 1: Dashboard - announcements
   ------------------------------------------------------------- */

function renderAnnouncements(announcements) {
  const list = document.getElementById('announcements-list');
  const loading = document.getElementById('announcements-loading');
  const empty = document.getElementById('announcements-empty');
  if (!list) return;

  hide(loading);
  setText('[data-announcements-count]', announcements.length);

  if (!announcements.length) {
    show(empty);
    return;
  }

  /* Pinned posts float to the top, then newest first. */
  const ordered = [...announcements].sort((a, b) => {
    if (Boolean(a.isPinned) !== Boolean(b.isPinned)) return a.isPinned ? -1 : 1;
    return dateValue(b.date) - dateValue(a.date);
  });

  list.innerHTML = ordered.map(announcementCard).join('');
}

function announcementCard(item) {
  const pinned = Boolean(item.isPinned);
  const accent = pinned ? 'border-emerald-400/40 bg-emerald-400/[0.04]' : 'border-slate-800 bg-slate-900/60';

  const pinnedBadge = pinned
    ? `<span class="inline-flex items-center gap-1.5 rounded-full bg-emerald-400/15 px-2.5 py-1 text-[11px] font-bold uppercase tracking-widest text-emerald-300">
         ${iconPin()} Pinned
       </span>`
    : '';

  return `
    <article class="card-hover rounded-2xl border ${accent} p-6 shadow-lg shadow-black/20">
      <div class="flex flex-wrap items-center gap-3">
        ${pinnedBadge}
        <time class="text-xs font-semibold uppercase tracking-widest text-slate-500" datetime="${escapeHtml(item.date)}">
          ${formatDate(item.date)}
        </time>
      </div>
      <h3 class="mt-3 text-xl font-bold leading-snug text-white">${escapeHtml(item.title)}</h3>
      <div class="mt-3 space-y-3 text-[15px] leading-relaxed text-slate-300">
        ${toParagraphs(item.content)}
      </div>
    </article>
  `;
}

/* -------------------------------------------------------------
   Page 1: Dashboard - deadlines
   ------------------------------------------------------------- */

function renderDeadlines(deadlines) {
  const list = document.getElementById('deadlines-list');
  const loading = document.getElementById('deadlines-loading');
  const empty = document.getElementById('deadlines-empty');
  if (!list) return;

  hide(loading);

  if (!deadlines.length) {
    show(empty);
    return;
  }

  /* Chronological, but anything already past drops below the upcoming items. */
  const ordered = [...deadlines].sort((a, b) => {
    const aPast = daysUntil(a.date) < 0;
    const bPast = daysUntil(b.date) < 0;
    if (aPast !== bPast) return aPast ? 1 : -1;
    return dateValue(a.date) - dateValue(b.date);
  });

  const upcoming = ordered.filter((item) => daysUntil(item.date) >= 0);
  setText('[data-deadlines-count]', upcoming.length);
  setText('[data-next-deadline]', upcoming.length ? formatDate(upcoming[0].date, { withYear: false }) : 'None scheduled');

  list.innerHTML = ordered.map(deadlineRow).join('');
}

function deadlineRow(item) {
  const days = daysUntil(item.date);
  const isPast = days < 0;
  const badge = importanceBadge(item.importance);
  const countdown = countdownLabel(days);

  return `
    <li class="flex gap-3 rounded-xl border border-slate-800 bg-slate-900/60 p-4 transition hover:border-slate-700 ${
      isPast ? 'opacity-55' : ''
    }">
      <span class="mt-1 h-2.5 w-2.5 flex-none rounded-full ${importanceDot(item.importance)}"></span>
      <div class="min-w-0 flex-1">
        <div class="flex flex-wrap items-start justify-between gap-2">
          <p class="text-sm font-semibold leading-snug text-white">${escapeHtml(item.event)}</p>
          ${badge}
        </div>
        <div class="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-400">
          <time datetime="${escapeHtml(item.date)}" class="font-medium text-slate-300">${formatDate(item.date, {
            weekday: true
          })}</time>
          <span class="${countdown.className}">${countdown.label}</span>
        </div>
      </div>
    </li>
  `;
}

function importanceBadge(importance) {
  const key = String(importance || '').toLowerCase();
  const styles = {
    high: 'bg-rose-500/15 text-rose-300 ring-rose-500/30',
    medium: 'bg-amber-400/15 text-amber-300 ring-amber-400/30',
    low: 'bg-slate-500/15 text-slate-300 ring-slate-500/30'
  };
  const style = styles[key] || styles.low;
  const label = key ? key.toUpperCase() : 'INFO';

  return `<span class="inline-flex flex-none items-center rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-widest ring-1 ring-inset ${style}">${escapeHtml(
    label
  )}</span>`;
}

function importanceDot(importance) {
  const key = String(importance || '').toLowerCase();
  if (key === 'high') return 'bg-rose-400';
  if (key === 'medium') return 'bg-amber-400';
  return 'bg-slate-500';
}

function countdownLabel(days) {
  if (days < 0) {
    const ago = Math.abs(days);
    return { label: `${ago} day${ago === 1 ? '' : 's'} ago`, className: 'text-slate-500' };
  }
  if (days === 0) return { label: 'Today', className: 'font-bold text-emerald-300' };
  if (days === 1) return { label: 'Tomorrow', className: 'font-bold text-emerald-300' };
  if (days <= 7) return { label: `In ${days} days`, className: 'font-semibold text-amber-300' };
  return { label: `In ${days} days`, className: 'text-slate-400' };
}

/* -------------------------------------------------------------
   Page 2: Power rankings
   ------------------------------------------------------------- */

function renderPowerRankings(rankings) {
  const list = document.getElementById('rankings-list');
  const loading = document.getElementById('rankings-loading');
  const empty = document.getElementById('rankings-empty');
  if (!list) return;

  hide(loading);

  if (!rankings.length) {
    show(empty);
    return;
  }

  const ordered = [...rankings].sort((a, b) => dateValue(b.publishedDate) - dateValue(a.publishedDate));

  setText('[data-rankings-count]', ordered.length);
  setText('[data-latest-week]', ordered[0].week || '--');
  setText('[data-latest-author]', ordered[0].author || 'Unknown');

  list.innerHTML = ordered.map(rankingArticle).join('');
  renderRankingFilters(ordered);
}

function renderRankingFilters(rankings) {
  const container = document.getElementById('rankings-filter');
  if (!container) return;

  const weeks = ['All weeks', ...rankings.map((entry) => entry.week || 'Untitled')];

  container.innerHTML = weeks
    .map(
      (week, index) => `
        <button type="button" data-week-filter="${escapeHtml(index === 0 ? 'all' : week)}"
          class="filter-chip ${index === 0 ? 'filter-chip-active' : ''}">
          ${escapeHtml(week)}
        </button>`
    )
    .join('');

  container.addEventListener('click', (event) => {
    const button = event.target.closest('[data-week-filter]');
    if (!button) return;

    const selected = button.dataset.weekFilter;

    container.querySelectorAll('[data-week-filter]').forEach((chip) => {
      chip.classList.toggle('filter-chip-active', chip === button);
    });

    document.querySelectorAll('[data-article-week]').forEach((article) => {
      const matches = selected === 'all' || article.dataset.articleWeek === selected;
      article.classList.toggle('hidden', !matches);
    });
  });
}

function rankingArticle(entry) {
  const teams = asArray(entry.rankingsList);
  const week = entry.week || 'Untitled week';

  return `
    <article data-article-week="${escapeHtml(week)}"
      class="overflow-hidden rounded-3xl border border-slate-800 bg-slate-900/60 shadow-xl shadow-black/30">

      <header class="border-b border-slate-800 bg-gradient-to-r from-emerald-500/10 via-slate-900/10 to-transparent px-6 py-6 sm:px-8">
        <div class="flex flex-wrap items-center gap-3">
          <span class="inline-flex items-center rounded-full bg-emerald-400/15 px-3 py-1 text-xs font-bold uppercase tracking-widest text-emerald-300 ring-1 ring-inset ring-emerald-400/30">
            ${escapeHtml(week)}
          </span>
          ${
            entry.publishedDate
              ? `<time datetime="${escapeHtml(entry.publishedDate)}" class="text-xs font-semibold uppercase tracking-widest text-slate-500">${formatDate(
                  entry.publishedDate
                )}</time>`
              : ''
          }
        </div>

        <h2 class="mt-3 text-2xl font-extrabold tracking-tight text-white sm:text-3xl">
          ${escapeHtml(entry.title || `${week} Power Rankings`)}
        </h2>

        <div class="mt-3 flex items-center gap-3">
          <span class="grid h-9 w-9 flex-none place-items-center rounded-full bg-slate-800 text-sm font-bold text-emerald-300">
            ${escapeHtml(initials(entry.author))}
          </span>
          <p class="text-sm text-slate-400">
            Written by <span class="font-semibold text-white">${escapeHtml(entry.author || 'Anonymous')}</span>
            ${entry.authorTeam ? `<span class="text-slate-500"> &middot; ${escapeHtml(entry.authorTeam)}</span>` : ''}
          </p>
        </div>
      </header>

      <div class="grid gap-8 px-6 py-8 sm:px-8 lg:grid-cols-5">
        <div class="lg:col-span-2">
          <h3 class="flex items-center gap-2 text-xs font-bold uppercase tracking-[0.2em] text-slate-400">
            ${iconLayers()} Tier breakdown
          </h3>
          <div class="mt-4 space-y-6">
            ${teams.length ? tierGroups(teams) : emptyInline('No teams were included in this ranking.')}
          </div>
        </div>

        <div class="lg:col-span-3">
          <h3 class="flex items-center gap-2 text-xs font-bold uppercase tracking-[0.2em] text-slate-400">
            ${iconQuote()} The write up
          </h3>
          <div class="mt-4 space-y-4 text-[15px] leading-7 text-slate-300 first-letter-drop">
            ${entry.writeup ? toParagraphs(entry.writeup) : emptyInline('No write up was submitted for this week.')}
          </div>
        </div>
      </div>
    </article>
  `;
}

/* Groups teams under their tier heading, preserving the order
   the tiers first appear in the data. */
function tierGroups(teams) {
  const groups = new Map();

  teams
    .slice()
    .sort((a, b) => numberOr(a.rank, 999) - numberOr(b.rank, 999))
    .forEach((team) => {
      const tier = team.tier || 'Unranked';
      if (!groups.has(tier)) groups.set(tier, []);
      groups.get(tier).push(team);
    });

  return [...groups.entries()]
    .map(
      ([tier, members]) => `
        <section>
          <div class="flex items-center gap-3">
            <h4 class="text-sm font-bold uppercase tracking-widest text-emerald-300">${escapeHtml(tier)}</h4>
            <span class="h-px flex-1 bg-slate-800"></span>
            <span class="text-[11px] font-semibold text-slate-500">${members.length} team${
        members.length === 1 ? '' : 's'
      }</span>
          </div>
          <ol class="mt-3 space-y-2">
            ${members.map(teamRow).join('')}
          </ol>
        </section>`
    )
    .join('');
}

function teamRow(team) {
  const move = movementBadge(team.movement);

  return `
    <li class="rounded-xl border border-slate-800 bg-slate-950/60 p-3 transition hover:border-emerald-400/30">
      <div class="flex items-center gap-3">
        <span class="grid h-8 w-8 flex-none place-items-center rounded-lg bg-slate-800 text-sm font-extrabold text-white">
          ${escapeHtml(team.rank)}
        </span>
        <div class="min-w-0 flex-1">
          <p class="truncate text-sm font-bold text-white">${escapeHtml(team.team)}</p>
          <p class="truncate text-xs text-slate-500">
            ${escapeHtml(team.manager || 'Unclaimed')}${team.record ? ` &middot; ${escapeHtml(team.record)}` : ''}
          </p>
        </div>
        ${move}
      </div>
      ${
        team.note
          ? `<p class="mt-2 border-l-2 border-slate-800 pl-3 text-xs leading-relaxed text-slate-400">${escapeHtml(
              team.note
            )}</p>`
          : ''
      }
    </li>
  `;
}

function movementBadge(movement) {
  if (movement === null || movement === undefined || movement === '') {
    return `<span class="flex-none text-[10px] font-bold uppercase tracking-widest text-slate-600">Base</span>`;
  }

  const value = Number(movement);
  if (!Number.isFinite(value) || value === 0) {
    return `<span class="flex-none text-xs font-bold text-slate-500" title="No change">&ndash;</span>`;
  }

  const up = value > 0;
  const cls = up ? 'text-emerald-400' : 'text-rose-400';
  const arrow = up ? '&#9650;' : '&#9660;';

  return `<span class="flex-none text-xs font-bold ${cls}" title="${up ? 'Up' : 'Down'} ${Math.abs(value)} spot${
    Math.abs(value) === 1 ? '' : 's'
  }">${arrow} ${Math.abs(value)}</span>`;
}

/* -------------------------------------------------------------
   Page 3: History vault (empty state protection)
   ------------------------------------------------------------- */

function renderHistory(history) {
  const list = document.getElementById('history-list');
  const empty = document.getElementById('history-empty');
  if (!list) return;

  /* The locked-vault card ships visible in the HTML so the page is
     never blank, even before JS runs or if the fetch fails. */
  if (!history.length) {
    show(empty);
    hide(list);
    return;
  }

  hide(empty);
  show(list);

  const ordered = [...history].sort((a, b) => numberOr(b.season, 0) - numberOr(a.season, 0));
  setText('[data-seasons-count]', ordered.length);
  list.innerHTML = ordered.map(seasonCard).join('');
}

function seasonCard(season) {
  const standings = asArray(season.standings);
  const playoffs = asArray(season.playoffResults);
  const archive = asArray(season.powerRankingsArchive);

  return `
    <article class="overflow-hidden rounded-3xl border border-slate-800 bg-slate-900/60 shadow-xl shadow-black/30">
      <header class="flex flex-wrap items-center justify-between gap-4 border-b border-slate-800 bg-gradient-to-r from-amber-400/10 to-transparent px-6 py-6 sm:px-8">
        <div>
          <p class="text-xs font-bold uppercase tracking-[0.2em] text-amber-300">Season archive</p>
          <h2 class="mt-1 text-3xl font-extrabold tracking-tight text-white">${escapeHtml(season.season)}</h2>
        </div>
        ${
          season.champion
            ? `<div class="rounded-2xl border border-amber-400/30 bg-amber-400/10 px-4 py-3 text-right">
                 <p class="text-[10px] font-bold uppercase tracking-widest text-amber-300">Champion</p>
                 <p class="text-lg font-bold text-white">${escapeHtml(nameOf(season.champion))}</p>
                 <p class="text-xs text-amber-200/70">${escapeHtml(managerOf(season.champion))}</p>
               </div>`
            : ''
        }
      </header>

      <div class="grid gap-8 px-6 py-8 sm:px-8 lg:grid-cols-2">
        <div>
          <h3 class="text-xs font-bold uppercase tracking-[0.2em] text-slate-400">Final standings</h3>
          ${
            standings.length
              ? `<div class="mt-4 overflow-hidden rounded-xl border border-slate-800">
                   <table class="w-full text-left text-sm">
                     <thead class="bg-slate-950/80 text-[10px] uppercase tracking-widest text-slate-500">
                       <tr>
                         <th class="px-3 py-2">#</th>
                         <th class="px-3 py-2">Team</th>
                         <th class="px-3 py-2">Record</th>
                         <th class="px-3 py-2 text-right">PF</th>
                       </tr>
                     </thead>
                     <tbody class="divide-y divide-slate-800">
                       ${standings
                         .map(
                           (row) => `
                             <tr class="text-slate-300">
                               <td class="px-3 py-2 font-bold text-white">${escapeHtml(row.rank)}</td>
                               <td class="px-3 py-2">
                                 <span class="font-semibold text-white">${escapeHtml(row.team)}</span>
                                 <span class="block text-xs text-slate-500">${escapeHtml(row.manager || '')}</span>
                               </td>
                               <td class="px-3 py-2">${escapeHtml(row.record || '--')}</td>
                               <td class="px-3 py-2 text-right tabular-nums">${escapeHtml(row.pointsFor || '--')}</td>
                             </tr>`
                         )
                         .join('')}
                     </tbody>
                   </table>
                 </div>`
              : emptyInline('Standings were not archived for this season.')
          }
        </div>

        <div class="space-y-8">
          <div>
            <h3 class="text-xs font-bold uppercase tracking-[0.2em] text-slate-400">Playoff results</h3>
            ${
              playoffs.length
                ? `<ul class="mt-4 space-y-3">
                     ${playoffs
                       .map(
                         (game) => `
                           <li class="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
                             <p class="text-[10px] font-bold uppercase tracking-widest text-emerald-300">${escapeHtml(
                               game.round || 'Playoff game'
                             )}</p>
                             <p class="mt-1 text-sm text-slate-300">
                               <span class="font-semibold text-white">${escapeHtml(game.winner || '')}</span>
                               defeated ${escapeHtml(game.loser || '')}
                               ${game.score ? `<span class="text-slate-500"> (${escapeHtml(game.score)})</span>` : ''}
                             </p>
                           </li>`
                       )
                       .join('')}
                   </ul>`
                : emptyInline('Playoff results were not archived for this season.')
            }
          </div>

          <div>
            <h3 class="text-xs font-bold uppercase tracking-[0.2em] text-slate-400">Archived power rankings</h3>
            ${
              archive.length
                ? `<ul class="mt-4 space-y-2">
                     ${archive
                       .map(
                         (entry) => `
                           <li class="flex items-center justify-between gap-3 rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-2 text-sm">
                             <span class="font-semibold text-white">${escapeHtml(entry.week || 'Week')}</span>
                             <span class="text-xs text-slate-500">${escapeHtml(entry.author || 'Unknown author')}</span>
                           </li>`
                       )
                       .join('')}
                   </ul>`
                : emptyInline('No weekly rankings were archived for this season.')
            }
          </div>
        </div>
      </div>
    </article>
  `;
}

function nameOf(entity) {
  if (!entity) return '';
  return typeof entity === 'string' ? entity : entity.team || entity.name || '';
}

function managerOf(entity) {
  if (!entity || typeof entity === 'string') return '';
  return entity.manager || '';
}

/* -------------------------------------------------------------
   Small shared helpers
   ------------------------------------------------------------- */

function setText(selector, value) {
  if (value === null || value === undefined || value === '') return;
  document.querySelectorAll(selector).forEach((node) => {
    node.textContent = String(value);
  });
}

function show(node) {
  if (node) node.classList.remove('hidden');
}

function hide(node) {
  if (node) node.classList.add('hidden');
}

function emptyInline(message) {
  return `<p class="mt-4 rounded-xl border border-dashed border-slate-800 p-4 text-sm text-slate-500">${escapeHtml(
    message
  )}</p>`;
}

function escapeHtml(value) {
  if (value === null || value === undefined) return '';
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/* Splits a text blob on blank lines into escaped <p> elements. */
function toParagraphs(text) {
  return String(text || '')
    .split(/\n\s*\n/)
    .map((block) => block.trim())
    .filter(Boolean)
    .map((block) => `<p>${escapeHtml(block).replace(/\n/g, '<br>')}</p>`)
    .join('');
}

/* Parses YYYY-MM-DD as a local date so the calendar day never
   shifts backwards in western time zones. */
function parseDate(value) {
  if (!value) return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value).trim());
  const date = match
    ? new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]))
    : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function dateValue(value) {
  const date = parseDate(value);
  return date ? date.getTime() : 0;
}

function formatDate(value, options = {}) {
  const date = parseDate(value);
  if (!date) return 'Date TBD';

  const format = {
    month: 'short',
    day: 'numeric'
  };
  if (options.withYear !== false) format.year = 'numeric';
  if (options.weekday) format.weekday = 'short';

  return date.toLocaleDateString(undefined, format);
}

/* Whole days from today to the given date. Negative means past. */
function daysUntil(value) {
  const date = parseDate(value);
  if (!date) return Number.MAX_SAFE_INTEGER;

  const today = new Date();
  today.setHours(0, 0, 0, 0);
  date.setHours(0, 0, 0, 0);

  return Math.round((date - today) / 86400000);
}

function numberOr(value, fallback) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function initials(name) {
  const parts = String(name || '')
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  if (!parts.length) return '?';
  return (parts[0][0] + (parts.length > 1 ? parts[parts.length - 1][0] : '')).toUpperCase();
}

/* -------------------------------------------------------------
   Inline icons (kept as functions so markup stays readable)
   ------------------------------------------------------------- */

function iconPin() {
  return `<svg class="h-3 w-3" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
    <path d="M9.5 1.5a1 1 0 0 1 1 0l.5.3 4.2 4.2.3.5a1 1 0 0 1-.9 1.5l-2 .1-3.4 3.4.4 2.6a1 1 0 0 1-1.7.9L5.6 12.6l-3.4 3.4a1 1 0 0 1-1.4-1.4l3.4-3.4L1.8 8.8a1 1 0 0 1 .9-1.7l2.6.4L8.7 4l.1-2 .7-.5Z"/>
  </svg>`;
}

function iconLayers() {
  return `<svg class="h-4 w-4 text-emerald-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <path d="M12 2 2 7l10 5 10-5-10-5Z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/>
  </svg>`;
}

function iconQuote() {
  return `<svg class="h-4 w-4 text-emerald-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <path d="M4 5h16"/><path d="M4 10h16"/><path d="M4 15h10"/><path d="M4 20h7"/>
  </svg>`;
}
