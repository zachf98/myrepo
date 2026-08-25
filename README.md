# Fantasy Football League Manager Portal

A static, multi-page portal for a 14-team ESPN fantasy football league. Built with plain HTML,
Tailwind CSS (via CDN), and vanilla JavaScript. All league content lives in a single `data.json`
file, so updating the site means editing one file, no database and no build step.

## Files

| File             | Purpose                                                                        |
| ---------------- | ------------------------------------------------------------------------------ |
| `data.json`      | The local database: league info, announcements, deadlines, power rankings, history |
| `index.html`     | Dashboard with the announcements feed and the deadline tracker                  |
| `rankings.html`  | Weekly power rankings articles with tier breakdowns and write ups               |
| `history.html`   | History vault, with an empty-state card until a season finishes                 |
| `app.js`         | Fetches `data.json` and renders it into whichever page is open                  |

## Running it locally

Browsers block `fetch()` on `file://` URLs, so open the site through a local web server rather than
double-clicking the HTML files:

```bash
python3 -m http.server 8000
# then visit http://localhost:8000
```

Any static server works (`npx serve`, VS Code Live Server, etc.), and the folder can be dropped
straight onto GitHub Pages, Netlify, or Vercel with no configuration.

## Updating league content

Everything is driven by `data.json`. Save the file and refresh the browser.

- **League + ESPN link**: set `league.espnLeagueUrl` to your public ESPN league URL. It fills in
  every ESPN button on the site. Also edit `league.name`, `tagline`, `season`, `teamCount`,
  `playoffTeams`, and `commissioner`.
- **Announcements**: `id`, `title`, `content`, `date` (`YYYY-MM-DD`), `isPinned`. Pinned posts sort
  to the top, then newest first. Separate paragraphs in `content` with a blank line (`\n\n`).
- **Deadlines**: `id`, `event`, `date`, `importance` (`high`, `medium`, or `low`). Upcoming items sort
  first with a live countdown; past items drop to the bottom and dim out.
- **Power rankings**: `week`, `author`, `rankingsList`, and `writeup`. Each entry in `rankingsList`
  takes `rank`, `team`, `manager`, `tier`, `movement` (positive is a climb, `null` for a baseline
  edition), and an optional `note`. Teams are grouped automatically under their `tier` heading.
- **History**: starts as `[]`, which is what keeps the vault locked. Add a season object with
  `season`, `champion`, `standings`, `playoffResults`, and `powerRankingsArchive` and the page
  switches from the locked card to the full archive layout.
