const { http } = require("../utils/http");
const {
  americanToImpliedProbability,
  normalizeTwoWayProbabilities,
} = require("../utils/probability");
const { similarityScore } = require("../utils/text");

const ACTION_SCOREBOARD_URL = "https://api.actionnetwork.com/web/v1/scoreboard/ufc";

function hasValidMoneyline(odds) {
  return Number.isFinite(odds?.ml_home) && Number.isFinite(odds?.ml_away);
}

function pickMoneylineSnapshot(oddsArray) {
  if (!Array.isArray(oddsArray) || !oddsArray.length) return null;
  const valid = oddsArray.filter(hasValidMoneyline);
  if (!valid.length) return null;
  return valid.find((entry) => entry.book_id === 15) || valid[0];
}

function mapCompetitionFighters(competition) {
  const competitors = Array.isArray(competition?.competitors) ? competition.competitors : [];
  const away = competitors.find((entry) => entry?.side === "away");
  const home = competitors.find((entry) => entry?.side === "home");
  if (!away?.player?.full_name || !home?.player?.full_name) return null;
  return {
    away: away.player.full_name,
    home: home.player.full_name,
  };
}

function computeFightMatchScore(fight, competition, eventName) {
  const mapped = mapCompetitionFighters(competition);
  if (!mapped) return { score: -Infinity, orientation: null };

  const direct =
    similarityScore(fight.fighterA.name, mapped.away) +
    similarityScore(fight.fighterB.name, mapped.home);
  const swapped =
    similarityScore(fight.fighterA.name, mapped.home) +
    similarityScore(fight.fighterB.name, mapped.away);

  const orientation = direct >= swapped ? "direct" : "swapped";
  const fighterScore = Math.max(direct, swapped);

  const actionEventTitle =
    competition?.meta?.title || competition?.league_name || "UFC Competition";
  const eventScore = similarityScore(eventName, actionEventTitle);

  return {
    score: fighterScore + eventScore * 0.7,
    orientation,
    fighterScore,
    eventScore,
  };
}

function buildMarketFromMoneyline({
  selectedOdds,
  orientation,
  actionFighters,
  fighterAName,
  fighterBName,
}) {
  if (!selectedOdds) {
    return {
      available: false,
      source: "Action Network public UFC scoreboard",
      note: "No moneyline values were available for this matchup.",
    };
  }

  const homeOdds = selectedOdds.ml_home;
  const awayOdds = selectedOdds.ml_away;
  const fighterAOdds = orientation === "direct" ? awayOdds : homeOdds;
  const fighterBOdds = orientation === "direct" ? homeOdds : awayOdds;

  const impliedA = americanToImpliedProbability(fighterAOdds);
  const impliedB = americanToImpliedProbability(fighterBOdds);
  const normalized = normalizeTwoWayProbabilities(impliedA, impliedB);

  return {
    available: true,
    source: "Action Network public UFC scoreboard",
    sportsbookBookId: selectedOdds.book_id ?? null,
    matchupFromSource: {
      away: actionFighters.away,
      home: actionFighters.home,
    },
    odds: {
      fighterA: fighterAOdds,
      fighterB: fighterBOdds,
    },
    implied: {
      fighterA: impliedA,
      fighterB: impliedB,
      noVigFighterA: normalized.pA,
      noVigFighterB: normalized.pB,
      vig: normalized.vig,
    },
    methodProps: null,
    methodPropsNote:
      "Method-specific props were not present in this free endpoint snapshot.",
    fighterLabels: {
      fighterA: fighterAName,
      fighterB: fighterBName,
    },
  };
}

async function fetchActionCompetitions() {
  const response = await http.get(ACTION_SCOREBOARD_URL);
  return Array.isArray(response?.data?.competitions) ? response.data.competitions : [];
}

async function getMarketOddsForFights(eventName, fights) {
  let competitions = [];
  try {
    competitions = await fetchActionCompetitions();
  } catch (error) {
    return fights.map(() => ({
      available: false,
      source: "Action Network public UFC scoreboard",
      note: `Odds source request failed: ${error.message}`,
    }));
  }

  return fights.map((fight) => {
    const candidates = competitions
      .map((competition) => {
        const scoreBundle = computeFightMatchScore(fight, competition, eventName);
        return { competition, ...scoreBundle };
      })
      .filter((entry) => entry.fighterScore >= 1.25)
      .sort((a, b) => b.score - a.score);

    if (!candidates.length) {
      return {
        available: false,
        source: "Action Network public UFC scoreboard",
        note:
          "No close name-matched odds entry found for this fight in the current public feed.",
      };
    }

    const best = candidates[0];
    const actionFighters = mapCompetitionFighters(best.competition);
    const selectedOdds = pickMoneylineSnapshot(best.competition.odds);

    return {
      ...buildMarketFromMoneyline({
        selectedOdds,
        orientation: best.orientation,
        actionFighters,
        fighterAName: fight.fighterA.name,
        fighterBName: fight.fighterB.name,
      }),
      matchQuality: {
        total: best.score,
        fighterNames: best.fighterScore,
        eventName: best.eventScore,
      },
      sourceEvent: best.competition?.meta?.title || null,
      sourceStartTime: best.competition?.start_time || null,
    };
  });
}

module.exports = {
  getMarketOddsForFights,
};
