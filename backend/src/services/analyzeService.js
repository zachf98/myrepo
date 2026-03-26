const { getEventCard, enrichFightsWithFighterStats } = require("./ufcStatsService");
const { getMarketOddsForFights } = require("./oddsService");
const { projectFight } = require("../models/probabilityModel");

async function analyzeEvent(eventUrl) {
  const eventCard = await getEventCard(eventUrl);
  const fightsWithStats = await enrichFightsWithFighterStats(eventCard.fights);
  const marketOddsList = await getMarketOddsForFights(eventCard.eventName, fightsWithStats);

  const fightAnalyses = fightsWithStats.map((fight, index) => {
    const market = marketOddsList[index] || {
      available: false,
      source: "Unknown",
      note: "No market data was found for this fight.",
    };
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
      market,
      model: projection.model,
      edge: projection.edge,
    };
  });

  const sortedByBestEdge = [...fightAnalyses].sort((left, right) => {
    const leftEdge = left.edge.bestEdge?.edge ?? Number.NEGATIVE_INFINITY;
    const rightEdge = right.edge.bestEdge?.edge ?? Number.NEGATIVE_INFINITY;
    return rightEdge - leftEdge;
  });

  return {
    event: {
      name: eventCard.eventName,
      metadata: eventCard.eventMeta,
      eventUrl,
    },
    fights: sortedByBestEdge,
    notes: [
      "Model weights are deterministic and explainable, not black-box machine learning.",
      "Market odds are sourced from Action Network's publicly accessible UFC scoreboard feed.",
      "Method-specific market props are included if present in source data; currently unavailable in this feed snapshot.",
      "When odds are unavailable for a fight, edge values are set to null and displayed accordingly.",
    ],
  };
}

module.exports = {
  analyzeEvent,
};
