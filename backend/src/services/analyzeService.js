const { getEventCard, enrichFightsWithFighterStats } = require("./ufcStatsService");
const { getMarketOddsForFights } = require("./oddsService");
const { projectFight } = require("../models/probabilityModel");

function defaultMarket() {
  return {
    available: false,
    source: "Unavailable",
    note: "Market data was not requested for this analysis.",
  };
}

async function analyzeEvent(eventUrl, options = {}) {
  const includeOdds = options.includeOdds !== false;
  const eventCard = await getEventCard(eventUrl);
  const asOfDate = options.asOfDate || eventCard.eventDate || null;
  const fightsWithStats = await enrichFightsWithFighterStats(eventCard.fights, { asOfDate });
  const marketOddsList = includeOdds
    ? await getMarketOddsForFights(eventCard.eventName, fightsWithStats)
    : fightsWithStats.map(() => defaultMarket());

  const fightAnalyses = fightsWithStats.map((fight, index) => {
    const market =
      marketOddsList[index] ||
      (includeOdds
        ? {
            available: false,
            source: "Unknown",
            note: "No market data was found for this fight.",
          }
        : defaultMarket());
    const projection = projectFight(fight, market);

    return {
      fightId: `${fight.fighterA.name}__${fight.fighterB.name}`.replace(/\s+/g, "_"),
      matchup: `${fight.fighterA.name} vs ${fight.fighterB.name}`,
      weightClass: fight.weightClass,
      fighters: {
        fighterA: {
          name: fight.fighterA.name,
          profileUrl: fight.fighterA.url,
          stats: fight.fighterA.stats,
        },
        fighterB: {
          name: fight.fighterB.name,
          profileUrl: fight.fighterB.url,
          stats: fight.fighterB.stats,
        },
      },
      result: {
        resultFlag: fight.resultFlag || null,
        winnerName: fight.winnerName || null,
      },
      market,
      model: projection.model,
      edge: projection.edge,
      ev: projection.ev,
      insightBlurb: projection.insightBlurb,
    };
  });

  const sortedByBestEdge = [...fightAnalyses].sort((left, right) => {
    const leftEdge = left.edge.bestEdge?.edge ?? Number.NEGATIVE_INFINITY;
    const rightEdge = right.edge.bestEdge?.edge ?? Number.NEGATIVE_INFINITY;
    return rightEdge - leftEdge;
  });
  const valuePlays = [...fightAnalyses]
    .map((fight) => ({
      matchup: fight.matchup,
      fighter: fight.ev?.bestValue?.fighter || null,
      ev: fight.ev?.bestValue?.ev ?? null,
      modelWinProbability: fight.ev?.bestValueModelProbability ?? null,
      methodAlignment: fight.model?.methodAlignment || null,
      blurb: fight.insightBlurb,
    }))
    .filter(
      (entry) =>
        Number.isFinite(entry.ev) &&
        entry.ev > 0.05 &&
        Number.isFinite(entry.modelWinProbability) &&
        entry.modelWinProbability >= 0.4,
    )
    .sort((left, right) => right.ev - left.ev)
    .slice(0, 6);

  return {
    event: {
      name: eventCard.eventName,
      metadata: eventCard.eventMeta,
      eventDate: eventCard.eventDate,
      eventDateText: eventCard.eventDateText,
      eventUrl,
    },
    fights: sortedByBestEdge,
    valuePlays,
    notes: [
      "Model weights are deterministic and explainable, not black-box machine learning.",
      "Market odds are sourced from Action Network's publicly accessible UFC scoreboard feed.",
      "Win and method outputs blend deterministic feature scoring with Monte Carlo simulation to represent uncertainty in fight outcomes.",
      "Recency weighting, age/activity gaps, decision profile, and round-level trend proxies are included in the model feature set.",
      "Method-specific market props are included if present in source data; currently unavailable in this feed snapshot.",
      "When odds are unavailable for a fight, edge values are set to null and displayed accordingly.",
    ],
  };
}

module.exports = {
  analyzeEvent,
};
