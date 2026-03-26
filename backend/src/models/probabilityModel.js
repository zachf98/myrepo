const { clamp } = require("../utils/probability");

function safeNumber(value, fallback = 0) {
  return Number.isFinite(value) ? value : fallback;
}

function normalizeSigned(value, scale) {
  const v = safeNumber(value, 0);
  if (!scale) return 0;
  return clamp(v / scale, -1, 1);
}

function buildFeatureVector(stats) {
  return {
    striking:
      0.45 * normalizeSigned(stats.sigDiffPerFight, 20) +
      0.3 * (safeNumber(stats.strikingAccuracy, 0.5) - 0.5) +
      0.25 * (safeNumber(stats.strikingDefense, 0.5) - 0.5),
    grappling:
      0.45 * normalizeSigned(stats.tdDiffPerFight, 4) +
      0.35 * (safeNumber(stats.takedownAccuracy, 0.4) - 0.4) +
      0.2 * normalizeSigned(stats.subAttemptsPerFight, 2.5),
    finish:
      0.55 * (safeNumber(stats.finishRate, 0.35) - 0.35) +
      0.25 * (safeNumber(stats.koWinRate, 0.2) - 0.2) +
      0.2 * (safeNumber(stats.subWinRate, 0.1) - 0.1),
    schedule: safeNumber(stats.opponentWinPct, 0.5) - 0.5,
  };
}

function logistic(x) {
  return 1 / (1 + Math.exp(-x));
}

function computeWinProbabilities(fighterAStats, fighterBStats) {
  const a = buildFeatureVector(fighterAStats);
  const b = buildFeatureVector(fighterBStats);

  const strikingDiff = a.striking - b.striking;
  const grapplingDiff = a.grappling - b.grappling;
  const finishDiff = a.finish - b.finish;
  const scheduleDiff = a.schedule - b.schedule;

  const linearScore =
    0.37 * strikingDiff +
    0.27 * grapplingDiff +
    0.2 * finishDiff +
    0.16 * scheduleDiff;

  const fighterAWinProbability = clamp(logistic(linearScore * 3.1), 0.03, 0.97);
  const fighterBWinProbability = 1 - fighterAWinProbability;

  return {
    fighterAWinProbability,
    fighterBWinProbability,
    components: {
      strikingDiff,
      grapplingDiff,
      finishDiff,
      scheduleDiff,
      linearScore,
    },
  };
}

function methodPotentials(fighterStats, opponentStats) {
  const koPotential =
    0.4 * safeNumber(fighterStats.koWinRate, 0.2) +
    0.25 * clamp(safeNumber(fighterStats.sigLandedPerMin, 3.5) / 6, 0, 1) +
    0.2 * safeNumber(fighterStats.strikingAccuracy, 0.45) +
    0.15 * (1 - safeNumber(opponentStats.strikingDefense, 0.52));

  const subPotential =
    0.4 * safeNumber(fighterStats.subWinRate, 0.1) +
    0.3 * clamp(safeNumber(fighterStats.subAttemptsPerFight, 0.5) / 2.5, 0, 1) +
    0.2 * safeNumber(fighterStats.takedownAccuracy, 0.35) +
    0.1 * (1 - safeNumber(opponentStats.takedownDefense, 0.6));

  const decisionPotential =
    0.45 * safeNumber(fighterStats.decisionWinRate, 0.25) +
    0.25 * safeNumber(fighterStats.strikingDefense, 0.5) +
    0.15 * clamp(safeNumber(fighterStats.totalFights, 8) / 20, 0, 1) +
    0.15 * (1 - safeNumber(fighterStats.finishRate, 0.35));

  const koAdjusted = koPotential * (1 + (safeNumber(opponentStats.koLossRate, 0.2) - 0.2));
  const subAdjusted =
    subPotential * (1 + (safeNumber(opponentStats.subLossRate, 0.15) - 0.15));
  const decisionAdjusted =
    decisionPotential *
    (1 + (safeNumber(opponentStats.decisionLossRate, 0.3) - 0.3) * 0.5);

  return {
    ko: Math.max(koAdjusted, 0.01),
    submission: Math.max(subAdjusted, 0.01),
    decision: Math.max(decisionAdjusted, 0.01),
  };
}

function computeMethodProbabilities(fighterAStats, fighterBStats, fighterAWinProbability) {
  const fighterAPotentials = methodPotentials(fighterAStats, fighterBStats);
  const fighterBPotentials = methodPotentials(fighterBStats, fighterAStats);

  const totalA =
    fighterAPotentials.ko + fighterAPotentials.submission + fighterAPotentials.decision;
  const totalB =
    fighterBPotentials.ko + fighterBPotentials.submission + fighterBPotentials.decision;

  const fighterA = {
    ko_tko: fighterAWinProbability * (fighterAPotentials.ko / totalA),
    submission: fighterAWinProbability * (fighterAPotentials.submission / totalA),
    decision: fighterAWinProbability * (fighterAPotentials.decision / totalA),
  };

  const fighterBWinProbability = 1 - fighterAWinProbability;
  const fighterB = {
    ko_tko: fighterBWinProbability * (fighterBPotentials.ko / totalB),
    submission: fighterBWinProbability * (fighterBPotentials.submission / totalB),
    decision: fighterBWinProbability * (fighterBPotentials.decision / totalB),
  };

  return { fighterA, fighterB };
}

function computeEdge(modelProbability, marketProbability) {
  if (!Number.isFinite(marketProbability)) return null;
  return modelProbability - marketProbability;
}

function projectFight(fight, marketOdds) {
  const fighterAStats = fight.fighterA.stats || {};
  const fighterBStats = fight.fighterB.stats || {};

  const win = computeWinProbabilities(fighterAStats, fighterBStats);
  const method = computeMethodProbabilities(
    fighterAStats,
    fighterBStats,
    win.fighterAWinProbability,
  );

  const marketA =
    marketOdds?.implied?.noVigFighterA ??
    marketOdds?.implied?.fighterA ??
    null;
  const marketB =
    marketOdds?.implied?.noVigFighterB ??
    marketOdds?.implied?.fighterB ??
    null;

  const fighterAEdge = computeEdge(win.fighterAWinProbability, marketA);
  const fighterBEdge = computeEdge(win.fighterBWinProbability, marketB);

  const rankedEdges = [
    { fighter: fight.fighterA.name, edge: fighterAEdge },
    { fighter: fight.fighterB.name, edge: fighterBEdge },
  ].filter((entry) => Number.isFinite(entry.edge));

  rankedEdges.sort((left, right) => right.edge - left.edge);

  return {
    model: {
      winProbabilities: {
        fighterA: win.fighterAWinProbability,
        fighterB: win.fighterBWinProbability,
      },
      methodProbabilities: method,
      featureBreakdown: win.components,
    },
    edge: {
      fighterA: fighterAEdge,
      fighterB: fighterBEdge,
      bestEdge: rankedEdges[0] || null,
    },
  };
}

module.exports = {
  projectFight,
};

