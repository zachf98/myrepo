const cheerio = require("cheerio");
const pLimit = require("p-limit");
const { http } = require("../utils/http");

const UFCSTATS_COMPLETED_EVENTS =
  "http://ufcstats.com/statistics/events/completed?page=all";
const UFCSTATS_UPCOMING_EVENTS = "http://ufcstats.com/statistics/events/upcoming";

const fighterProfileCache = new Map();
const fighterRecordCache = new Map();
const opponentRecordLimiter = pLimit(5);

function parseNumber(text) {
  const value = Number(String(text || "").replace(/[^0-9.-]/g, ""));
  return Number.isFinite(value) ? value : null;
}

function parsePercent(text) {
  const raw = parseNumber(text);
  return raw === null ? null : raw / 100;
}

function parseRecord(recordText) {
  const match = String(recordText || "")
    .trim()
    .match(/(\d+)\s*-\s*(\d+)(?:\s*-\s*(\d+))?/);

  if (!match) {
    return { wins: 0, losses: 0, draws: 0 };
  }

  return {
    wins: Number(match[1]) || 0,
    losses: Number(match[2]) || 0,
    draws: Number(match[3] || 0) || 0,
  };
}

function safeRatio(numerator, denominator, fallback = 0.5) {
  if (!Number.isFinite(numerator) || !Number.isFinite(denominator) || denominator <= 0) {
    return fallback;
  }
  return numerator / denominator;
}

function recordToWinPct(record) {
  const total = (record?.wins || 0) + (record?.losses || 0) + (record?.draws || 0);
  return total > 0 ? (record.wins || 0) / total : 0.5;
}

async function getFighterRecordOnly(fighterUrl) {
  if (!fighterUrl) return { wins: 0, losses: 0, draws: 0 };
  if (fighterRecordCache.has(fighterUrl)) {
    return fighterRecordCache.get(fighterUrl);
  }

  try {
    const response = await http.get(fighterUrl);
    const $ = cheerio.load(response.data);
    const recordText = $(".b-content__title-record").first().text().replace("Record:", "").trim();
    const record = parseRecord(recordText);
    fighterRecordCache.set(fighterUrl, record);
    return record;
  } catch (error) {
    const fallback = { wins: 0, losses: 0, draws: 0 };
    fighterRecordCache.set(fighterUrl, fallback);
    return fallback;
  }
}

async function getEventList() {
  const [upcomingRes, completedRes] = await Promise.all([
    http.get(UFCSTATS_UPCOMING_EVENTS),
    http.get(UFCSTATS_COMPLETED_EVENTS),
  ]);

  const events = [];
  const seen = new Set();

  function parseRows(html, category) {
    const $ = cheerio.load(html);
    $("tbody tr")
      .slice(1)
      .each((_, row) => {
        const link = $(row).find("a").attr("href");
        if (!link || seen.has(link)) return;
        seen.add(link);

        const cells = $(row)
          .find("td")
          .map((__, td) => $(td).text().replace(/\s+/g, " ").trim())
          .get();

        const [name = "", date = "", location = ""] = cells;
        events.push({
          id: link.split("/").pop(),
          eventUrl: link,
          name,
          date,
          location,
          category,
        });
      });
  }

  parseRows(upcomingRes.data, "upcoming");
  parseRows(completedRes.data, "completed");

  return events;
}

function parseFightRow($, row) {
  const onclick = $(row).attr("onclick") || "";
  const fightUrl = (onclick.match(/'(.*?)'/) || [])[1] || null;
  const cols = $(row).find("td");

  const fighterAnchors = cols
    .eq(1)
    .find("a.b-link.b-link_style_black")
    .map((_, a) => ({
      name: $(a).text().trim(),
      url: $(a).attr("href"),
    }))
    .get();

  if (fighterAnchors.length < 2) return null;

  return {
    fightUrl,
    weightClass: cols.eq(6).text().replace(/\s+/g, " ").trim(),
    resultMethod: cols.eq(7).text().replace(/\s+/g, " ").trim(),
    fighterA: fighterAnchors[0],
    fighterB: fighterAnchors[1],
  };
}

async function getEventCard(eventUrl) {
  const response = await http.get(eventUrl);
  const $ = cheerio.load(response.data);

  const eventName = $(".b-content__title-highlight").first().text().trim();
  const eventMeta = $(".b-list__box-list li")
    .map((_, li) => $(li).text().replace(/\s+/g, " ").trim())
    .get()
    .filter(Boolean);

  const fights = $("tbody.b-fight-details__table-body tr.b-fight-details__table-row")
    .map((_, row) => parseFightRow($, row))
    .get()
    .filter(Boolean);

  return {
    eventName,
    eventMeta,
    fights,
  };
}

function parseMethodGroup(methodText) {
  const text = String(methodText || "").toLowerCase();
  if (text.includes("ko") || text.includes("tko")) return "ko_tko";
  if (text.includes("sub")) return "submission";
  if (text.includes("dec")) return "decision";
  return "other";
}

function buildFighterHistoryRows($, fighterName) {
  const normalizedName = String(fighterName || "").toLowerCase().trim();
  return $("tr.b-fight-details__table-row")
    .slice(2)
    .map((_, row) => {
      const columns = $(row).find("td");
      if (!columns.length) return null;

      const result = columns.eq(0).find("a").first().text().trim().toLowerCase();
      if (!result) return null;

      const fighterLinks = columns
        .eq(1)
        .find("a")
        .map((__, a) => ({
          name: $(a).text().trim(),
          url: $(a).attr("href"),
        }))
        .get();

      if (fighterLinks.length < 2) return null;

      const fighterIndex = fighterLinks.findIndex(
        (entry) =>
          entry.name.toLowerCase() === normalizedName ||
          entry.name.toLowerCase().includes(normalizedName),
      );
      const index = fighterIndex >= 0 ? fighterIndex : 0;
      const oppIndex = index === 0 ? 1 : 0;

      const strValues = columns
        .eq(3)
        .find("p")
        .map((__, p) => parseNumber($(p).text()))
        .get();
      const tdValues = columns
        .eq(4)
        .find("p")
        .map((__, p) => parseNumber($(p).text()))
        .get();
      const subValues = columns
        .eq(5)
        .find("p")
        .map((__, p) => parseNumber($(p).text()))
        .get();

      const method = columns.eq(7).find("p").first().text().trim();

      return {
        result,
        sigFor: strValues[index] ?? null,
        sigAgainst: strValues[oppIndex] ?? null,
        tdFor: tdValues[index] ?? null,
        tdAgainst: tdValues[oppIndex] ?? null,
        subFor: subValues[index] ?? null,
        methodGroup: parseMethodGroup(method),
        opponent: fighterLinks[oppIndex],
      };
    })
    .get()
    .filter(Boolean);
}

function aggregateHistory(rows) {
  const completed = rows.filter((row) => row.result !== "next");

  let wins = 0;
  let losses = 0;
  let draws = 0;
  let totalSigLanded = 0;
  let totalSigAbsorbed = 0;
  let totalTdLanded = 0;
  let totalTdAgainst = 0;
  let totalSubs = 0;
  let finishWins = 0;
  let koWins = 0;
  let subWins = 0;
  let decisionWins = 0;
  let koLosses = 0;
  let subLosses = 0;
  let decisionLosses = 0;

  const opponentWinPcts = completed
    .map((row) => row.opponentWinPct)
    .filter((value) => Number.isFinite(value));

  completed.forEach((row) => {
    if (row.result === "win") wins += 1;
    if (row.result === "loss") losses += 1;
    if (row.result === "draw") draws += 1;

    totalSigLanded += row.sigFor || 0;
    totalSigAbsorbed += row.sigAgainst || 0;
    totalTdLanded += row.tdFor || 0;
    totalTdAgainst += row.tdAgainst || 0;
    totalSubs += row.subFor || 0;

    if (row.result === "win") {
      if (row.methodGroup === "ko_tko") {
        finishWins += 1;
        koWins += 1;
      } else if (row.methodGroup === "submission") {
        finishWins += 1;
        subWins += 1;
      } else if (row.methodGroup === "decision") {
        decisionWins += 1;
      }
    }

    if (row.result === "loss") {
      if (row.methodGroup === "ko_tko") koLosses += 1;
      if (row.methodGroup === "submission") subLosses += 1;
      if (row.methodGroup === "decision") decisionLosses += 1;
    }
  });

  const finishedFights = wins + losses + draws;
  const opponentWinPct = opponentWinPcts.length
    ? opponentWinPcts.reduce((sum, value) => sum + value, 0) / opponentWinPcts.length
    : 0.5;

  return {
    totalFights: finishedFights,
    wins,
    losses,
    draws,
    sigDiffPerFight: finishedFights ? (totalSigLanded - totalSigAbsorbed) / finishedFights : 0,
    tdDiffPerFight: finishedFights ? (totalTdLanded - totalTdAgainst) / finishedFights : 0,
    subAttemptsPerFight: finishedFights ? totalSubs / finishedFights : 0,
    finishRate: safeRatio(finishWins, Math.max(wins, 1), 0.3),
    koWinRate: safeRatio(koWins, Math.max(wins, 1), 0.2),
    subWinRate: safeRatio(subWins, Math.max(wins, 1), 0.1),
    decisionWinRate: safeRatio(decisionWins, Math.max(wins, 1), 0.25),
    koLossRate: safeRatio(koLosses, Math.max(losses, 1), 0.2),
    subLossRate: safeRatio(subLosses, Math.max(losses, 1), 0.15),
    decisionLossRate: safeRatio(decisionLosses, Math.max(losses, 1), 0.3),
    opponentWinPct,
  };
}

async function enrichRowsWithOpponentStrength(rows) {
  const targets = rows
    .filter((row) => row.result !== "next" && row.opponent?.url)
    .slice(0, 8);
  const uniqueOpponentUrls = [...new Set(targets.map((row) => row.opponent.url))];

  await Promise.all(
    uniqueOpponentUrls.map((url) =>
      opponentRecordLimiter(async () => {
        await getFighterRecordOnly(url);
      }),
    ),
  );

  return rows.map((row) => {
    if (!row.opponent?.url) return row;
    const record = fighterRecordCache.get(row.opponent.url);
    return {
      ...row,
      opponentWinPct: recordToWinPct(record),
    };
  });
}

async function getFighterProfile(fighterUrl) {
  if (fighterProfileCache.has(fighterUrl)) {
    return fighterProfileCache.get(fighterUrl);
  }

  const response = await http.get(fighterUrl);
  const $ = cheerio.load(response.data);

  const fighterName = $(".b-content__title-highlight").first().text().trim();
  const recordText = $(".b-content__title-record").first().text().replace("Record:", "").trim();

  const statPairs = {};
  $(".b-list__box-list li").each((_, li) => {
    const text = $(li).text().replace(/\s+/g, " ").trim();
    if (!text.includes(":")) return;
    const [key, ...rest] = text.split(":");
    statPairs[key.trim()] = rest.join(":").trim();
  });

  const historyRows = buildFighterHistoryRows($, fighterName);
  const enrichedHistoryRows = await enrichRowsWithOpponentStrength(historyRows);
  const historyAgg = aggregateHistory(enrichedHistoryRows);

  const profile = {
    fighterUrl,
    fighterName,
    record: parseRecord(recordText),
    strikingAccuracy: parsePercent(statPairs["Str. Acc."]),
    strikingDefense: parsePercent(statPairs["Str. Def"]),
    takedownAccuracy: parsePercent(statPairs["TD Acc."]),
    takedownDefense: parsePercent(statPairs["TD Def."]),
    submissionAttemptsPer15: parseNumber(statPairs["Sub. Avg."]),
    sigLandedPerMin: parseNumber(statPairs["SLpM"]),
    sigAbsorbedPerMin: parseNumber(statPairs["SApM"]),
    tdAvgPer15: parseNumber(statPairs["TD Avg."]),
    ...historyAgg,
  };

  fighterProfileCache.set(fighterUrl, profile);
  fighterRecordCache.set(fighterUrl, profile.record);
  return profile;
}

async function enrichFightsWithFighterStats(fights) {
  const limit = pLimit(5);
  return Promise.all(
    fights.map((fight) =>
      limit(async () => {
        const [fighterAStats, fighterBStats] = await Promise.all([
          getFighterProfile(fight.fighterA.url),
          getFighterProfile(fight.fighterB.url),
        ]);

        return {
          ...fight,
          fighterA: { ...fight.fighterA, stats: fighterAStats },
          fighterB: { ...fight.fighterB, stats: fighterBStats },
        };
      }),
    ),
  );
}

module.exports = {
  getEventList,
  getEventCard,
  enrichFightsWithFighterStats,
};
