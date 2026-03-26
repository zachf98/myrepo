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

function randomStandardNormal() {
  let u = 0;
  let v = 0;
  while (u === 0) u = Math.random();
  while (v === 0) v = Math.random();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

function agePrimeScore(ageYears) {
  const age = safeNumber(ageYears, 31);
  const distanceFromPrime = Math.abs(age - 31);
  return clamp(1 - distanceFromPrime / 12, -1, 1);
}

function activityScore(stats) {
  const fightsLast365 = safeNumber(stats.fightsLast365, 1);
  const fightsLast730 = safeNumber(stats.fightsLast730, 2);
  const daysSinceLastFight = safeNumber(stats.daysSinceLastFight, 240);
  const frequency = 0.65 * clamp(fightsLast365 / 3, 0, 1) + 0.35 * clamp(fightsLast730 / 5, 0, 1);
  const freshness = clamp(1 - daysSinceLastFight / 520, 0, 1);
  return 0.6 * frequency + 0.4 * freshness - 0.5;
}

function ufcExperienceScore(stats) {
  const ufcFightCount = safeNumber(stats.totalFights, 0);
  const totalCareer = Math.max(safeNumber(stats.totalCareerFights, ufcFightCount), 1);
  const preUfcFights = safeNumber(stats.preUfcFightCount, 0);
  const ufcShare = clamp(ufcFightCount / totalCareer, 0, 1);
  const depth = clamp(Math.log1p(ufcFightCount) / Math.log(30), 0, 1);
  const unknownPreUfcPenalty = clamp(preUfcFights / totalCareer, 0, 1) * 0.15;
  return depth * 0.7 + ufcShare * 0.3 - 0.5 - unknownPreUfcPenalty;
}

function computeWinProbabilities(fighterAStats, fighterBStats) {
  const a = buildFeatureVector(fighterAStats);
  const b = buildFeatureVector(fighterBStats);

  const strikingDiff = a.striking - b.striking;
  const grapplingDiff = a.grappling - b.grappling;
  const finishDiff = a.finish - b.finish;
  const scheduleDiff = a.schedule - b.schedule;
  const recencyDiff =
    normalizeSigned(fighterAStats.weightedSigDiffPerFight, 20) -
    normalizeSigned(fighterBStats.weightedSigDiffPerFight, 20);
  const activityDiff = activityScore(fighterAStats) - activityScore(fighterBStats);
  const agePrimeDiff = agePrimeScore(fighterAStats.ageYears) - agePrimeScore(fighterBStats.ageYears);
  const decisionSkillDiff =
    (safeNumber(fighterAStats.decisionWinPctWhenDecision, 0.5) - 0.5) -
    (safeNumber(fighterBStats.decisionWinPctWhenDecision, 0.5) - 0.5);
  const roundDurabilityDiff =
    normalizeSigned(fighterAStats.lateRoundSigDiff, 20) -
    normalizeSigned(fighterBStats.lateRoundSigDiff, 20);
  const experienceDiff = ufcExperienceScore(fighterAStats) - ufcExperienceScore(fighterBStats);

  const fighterAUfcFights = safeNumber(fighterAStats.totalFights, 0);
  const fighterBUfcFights = safeNumber(fighterBStats.totalFights, 0);
  const aIsDebutant = fighterAUfcFights <= 2;
  const bIsDebutant = fighterBUfcFights <= 2;
  const aIsVet = fighterAUfcFights >= 12;
  const bIsVet = fighterBUfcFights >= 12;
  const debutantVsVetSwing = aIsDebutant && bIsVet ? -0.08 : bIsDebutant && aIsVet ? 0.08 : 0;

  const linearScore =
    0.24 * strikingDiff +
    0.17 * grapplingDiff +
    0.12 * finishDiff +
    0.12 * scheduleDiff +
    0.11 * recencyDiff +
    0.08 * activityDiff +
    0.06 * decisionSkillDiff +
    0.05 * agePrimeDiff +
    0.05 * roundDurabilityDiff +
    0.04 * experienceDiff +
    debutantVsVetSwing;

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
      recencyDiff,
      activityDiff,
      agePrimeDiff,
      decisionSkillDiff,
      roundDurabilityDiff,
      experienceDiff,
      debutantVsVetSwing,
      linearScore,
    },
    matchupArchetype: {
      aIsDebutant,
      bIsDebutant,
      aIsVet,
      bIsVet,
    },
  };
}

function methodContextTilt(fighterStats, opponentStats, matchupArchetype, side) {
  const fighterDecisionRate = safeNumber(fighterStats.decisionAppearanceRate, 0.3);
  const opponentDecisionRate = safeNumber(opponentStats.decisionAppearanceRate, 0.3);
  const bothGoLong = fighterDecisionRate > 0.42 && opponentDecisionRate > 0.42;
  const bothFastFinishers =
    safeNumber(fighterStats.finishRate, 0.35) > 0.58 &&
    safeNumber(opponentStats.finishRate, 0.35) > 0.58;

  let tilt = 0;
  if (bothGoLong) tilt += 0.06;
  if (bothFastFinishers) tilt -= 0.05;

  if (matchupArchetype?.aIsDebutant && matchupArchetype?.bIsVet) {
    tilt += side === "fighterB" ? 0.05 : 0.02;
  }
  if (matchupArchetype?.bIsDebutant && matchupArchetype?.aIsVet) {
    tilt += side === "fighterA" ? 0.05 : 0.02;
  }
  return clamp(tilt, -0.12, 0.12);
}

function methodPotentials(fighterStats, opponentStats, matchupArchetype, side) {
  const koPotential =
    0.32 * safeNumber(fighterStats.koWinRate, 0.2) +
    0.2 * clamp(safeNumber(fighterStats.sigLandedPerMin, 3.5) / 6, 0, 1) +
    0.18 * safeNumber(fighterStats.strikingAccuracy, 0.45) +
    0.14 * (1 - safeNumber(opponentStats.strikingDefense, 0.52)) +
    0.16 * clamp(safeNumber(fighterStats.quickFinishWinRate, 0.2), 0, 1);

  const subPotential =
    0.35 * safeNumber(fighterStats.subWinRate, 0.1) +
    0.3 * clamp(safeNumber(fighterStats.subAttemptsPerFight, 0.5) / 2.5, 0, 1) +
    0.2 * safeNumber(fighterStats.takedownAccuracy, 0.35) +
    0.1 * (1 - safeNumber(opponentStats.takedownDefense, 0.6)) +
    0.05 * clamp(safeNumber(fighterStats.weightedSubAttemptsPerFight, 0.4) / 2, 0, 1);

  const decisionTilt = methodContextTilt(fighterStats, opponentStats, matchupArchetype, side);
  const decisionPotential =
    0.3 * safeNumber(fighterStats.decisionWinPctWhenDecision, 0.5) +
    0.23 * safeNumber(fighterStats.decisionAppearanceRate, 0.3) +
    0.15 * safeNumber(fighterStats.strikingDefense, 0.5) +
    0.12 * clamp(safeNumber(fighterStats.totalFights, 8) / 20, 0, 1) +
    0.12 * (1 - safeNumber(fighterStats.finishRate, 0.35)) +
    0.08 * clamp(0.5 + normalizeSigned(fighterStats.lateRoundSigDiff, 20), 0, 1) +
    decisionTilt;

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

function computeMethodProbabilities(
  fighterAStats,
  fighterBStats,
  fighterAWinProbability,
  matchupArchetype,
) {
  const fighterAPotentials = methodPotentials(
    fighterAStats,
    fighterBStats,
    matchupArchetype,
    "fighterA",
  );
  const fighterBPotentials = methodPotentials(
    fighterBStats,
    fighterAStats,
    matchupArchetype,
    "fighterB",
  );

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

function expectedValueFromAmericanOdds(winProbability, americanOdds) {
  if (!Number.isFinite(winProbability) || !Number.isFinite(americanOdds) || americanOdds === 0) {
    return null;
  }
  const profitIfWin = americanOdds > 0 ? americanOdds / 100 : 100 / Math.abs(americanOdds);
  const loseAmount = 1;
  return winProbability * profitIfWin - (1 - winProbability) * loseAmount;
}

function simulateFightOutcomes({
  fighterAStats,
  fighterBStats,
  baseWinProbabilityA,
  baseMethodA,
  baseMethodB,
  simulations = 6000,
}) {
  const countA = safeNumber(fighterAStats.totalFights, 0);
  const countB = safeNumber(fighterBStats.totalFights, 0);
  const lowSamplePenalty = 0.09 / Math.sqrt(Math.max(Math.min(countA, countB), 1));
  const inactivityPenalty =
    (safeNumber(fighterAStats.daysSinceLastFight, 220) > 430 ? 0.015 : 0) +
    (safeNumber(fighterBStats.daysSinceLastFight, 220) > 430 ? 0.015 : 0);
  const sigma = clamp(0.045 + lowSamplePenalty + inactivityPenalty, 0.04, 0.12);

  const baseCondA = {
    ko_tko: safeNumber(baseMethodA.ko_tko, 0) / Math.max(baseWinProbabilityA, 0.001),
    submission: safeNumber(baseMethodA.submission, 0) / Math.max(baseWinProbabilityA, 0.001),
    decision:
      safeNumber(baseMethodA.decision, 0) / Math.max(baseWinProbabilityA, 0.001),
  };
  const baseCondB = {
    ko_tko: safeNumber(baseMethodB.ko_tko, 0) / Math.max(1 - baseWinProbabilityA, 0.001),
    submission: safeNumber(baseMethodB.submission, 0) / Math.max(1 - baseWinProbabilityA, 0.001),
    decision:
      safeNumber(baseMethodB.decision, 0) / Math.max(1 - baseWinProbabilityA, 0.001),
  };

  function drawMethod(conditionals) {
    const pKo = clamp(conditionals.ko_tko, 0, 1);
    const pSub = clamp(conditionals.submission, 0, 1);
    const pDec = clamp(conditionals.decision, 0, 1);
    const total = pKo + pSub + pDec;
    const ko = pKo / total;
    const sub = pSub / total;
    const roll = Math.random();
    if (roll < ko) return "ko_tko";
    if (roll < ko + sub) return "submission";
    return "decision";
  }

  let aWins = 0;
  const methodTotals = {
    fighterA: { ko_tko: 0, submission: 0, decision: 0 },
    fighterB: { ko_tko: 0, submission: 0, decision: 0 },
  };

  for (let i = 0; i < simulations; i += 1) {
    const perturbation = randomStandardNormal() * sigma;
    const pA = clamp(baseWinProbabilityA + perturbation, 0.01, 0.99);
    const aWinsThisRun = Math.random() < pA;
    if (aWinsThisRun) {
      aWins += 1;
      const method = drawMethod(baseCondA);
      methodTotals.fighterA[method] += 1;
    } else {
      const method = drawMethod(baseCondB);
      methodTotals.fighterB[method] += 1;
    }
  }

  return {
    simulations,
    fighterAWinProbability: aWins / simulations,
    fighterBWinProbability: 1 - aWins / simulations,
    methodProbabilities: {
      fighterA: {
        ko_tko: methodTotals.fighterA.ko_tko / simulations,
        submission: methodTotals.fighterA.submission / simulations,
        decision: methodTotals.fighterA.decision / simulations,
      },
      fighterB: {
        ko_tko: methodTotals.fighterB.ko_tko / simulations,
        submission: methodTotals.fighterB.submission / simulations,
        decision: methodTotals.fighterB.decision / simulations,
      },
    },
    uncertaintySigma: sigma,
  };
}

function buildValueBlurb(fight, bestValueSide, modelProbability, marketProbability, ev, breakdown) {
  if (!bestValueSide || !Number.isFinite(ev) || ev < 0.05) return null;

  const fighterName =
    bestValueSide === "fighterA" ? fight.fighterA.name : fight.fighterB.name;
  const direction = bestValueSide === "fighterA" ? "A" : "B";
  const reasons = [];

  if (Math.abs(safeNumber(breakdown.recencyDiff, 0)) > 0.12) {
    const stronger =
      (direction === "A" && breakdown.recencyDiff > 0) ||
      (direction === "B" && breakdown.recencyDiff < 0);
    if (stronger) reasons.push("better recent form and recency-weighted output");
  }
  if (Math.abs(safeNumber(breakdown.activityDiff, 0)) > 0.12) {
    const stronger =
      (direction === "A" && breakdown.activityDiff > 0) ||
      (direction === "B" && breakdown.activityDiff < 0);
    if (stronger) reasons.push("higher recent activity and less layoff risk");
  }
  if (Math.abs(safeNumber(breakdown.roundDurabilityDiff, 0)) > 0.1) {
    const stronger =
      (direction === "A" && breakdown.roundDurabilityDiff > 0) ||
      (direction === "B" && breakdown.roundDurabilityDiff < 0);
    if (stronger) reasons.push("stronger late-round trend from round-level stats");
  }
  if (Math.abs(safeNumber(breakdown.decisionSkillDiff, 0)) > 0.1) {
    const stronger =
      (direction === "A" && breakdown.decisionSkillDiff > 0) ||
      (direction === "B" && breakdown.decisionSkillDiff < 0);
    if (stronger) reasons.push("better decision win profile when fights reach the cards");
  }
  if (!reasons.length) {
    reasons.push("a stronger aggregate profile across striking, grappling, and schedule");
  }

  return `${fighterName} shows +EV: model ${Math.round(
    modelProbability * 100,
  )}% vs market ${Math.round(marketProbability * 100)}% with est. ROI ${(
    ev * 100
  ).toFixed(1)}%, driven by ${reasons.slice(0, 2).join(" and ")}.`;
}

function projectFight(fight, marketOdds) {
  const fighterAStats = fight.fighterA.stats || {};
  const fighterBStats = fight.fighterB.stats || {};

  const win = computeWinProbabilities(fighterAStats, fighterBStats);
  const method = computeMethodProbabilities(
    fighterAStats,
    fighterBStats,
    win.fighterAWinProbability,
    win.matchupArchetype,
  );
  const simulation = simulateFightOutcomes({
    fighterAStats,
    fighterBStats,
    baseWinProbabilityA: win.fighterAWinProbability,
    baseMethodA: method.fighterA,
    baseMethodB: method.fighterB,
  );

  const marketA =
    marketOdds?.implied?.noVigFighterA ??
    marketOdds?.implied?.fighterA ??
    null;
  const marketB =
    marketOdds?.implied?.noVigFighterB ??
    marketOdds?.implied?.fighterB ??
    null;

  const fighterAEdge = computeEdge(simulation.fighterAWinProbability, marketA);
  const fighterBEdge = computeEdge(simulation.fighterBWinProbability, marketB);
  const fighterAEv = expectedValueFromAmericanOdds(
    simulation.fighterAWinProbability,
    marketOdds?.odds?.fighterA,
  );
  const fighterBEv = expectedValueFromAmericanOdds(
    simulation.fighterBWinProbability,
    marketOdds?.odds?.fighterB,
  );

  const rankedEdges = [
    { fighter: fight.fighterA.name, edge: fighterAEdge },
    { fighter: fight.fighterB.name, edge: fighterBEdge },
  ].filter((entry) => Number.isFinite(entry.edge));

  rankedEdges.sort((left, right) => right.edge - left.edge);
  const evRank = [
    { side: "fighterA", fighter: fight.fighterA.name, ev: fighterAEv },
    { side: "fighterB", fighter: fight.fighterB.name, ev: fighterBEv },
  ]
    .filter((entry) => Number.isFinite(entry.ev))
    .sort((left, right) => right.ev - left.ev);
  const bestValue = evRank[0] || null;
  const blurb = buildValueBlurb(
    fight,
    bestValue?.side || null,
    bestValue?.side === "fighterA"
      ? simulation.fighterAWinProbability
      : simulation.fighterBWinProbability,
    bestValue?.side === "fighterA" ? marketA : marketB,
    bestValue?.ev ?? null,
    win.components,
  );

  return {
    model: {
      winProbabilities: {
        fighterA: simulation.fighterAWinProbability,
        fighterB: simulation.fighterBWinProbability,
      },
      methodProbabilities: simulation.methodProbabilities,
      featureBreakdown: win.components,
      matchupArchetype: win.matchupArchetype,
      monteCarlo: simulation,
    },
    edge: {
      fighterA: fighterAEdge,
      fighterB: fighterBEdge,
      bestEdge: rankedEdges[0] || null,
    },
    ev: {
      fighterA: fighterAEv,
      fighterB: fighterBEv,
      bestValue,
    },
    insightBlurb: blurb,
  };
}

module.exports = {
  projectFight,
};

