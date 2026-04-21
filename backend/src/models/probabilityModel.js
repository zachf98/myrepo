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

function veteranCraftScore(stats) {
  const experience = ufcExperienceScore(stats) + 0.5;
  const decisionIQ =
    safeNumber(stats.decisionAppearanceRate, 0.3) *
    safeNumber(stats.decisionWinPctWhenDecision, 0.5);
  const scheduleQuality = safeNumber(stats.weightedOpponentWinPct, 0.5);
  const pressure =
    0.6 * clamp(safeNumber(stats.sigLandedPerMin, 3.2) / 6, 0, 1) +
    0.4 * safeNumber(stats.koWinRate, 0.2);
  return (
    0.4 * experience + 0.25 * decisionIQ + 0.2 * scheduleQuality + 0.15 * pressure - 0.5
  );
}

function computeWinProbabilities(fighterAStats, fighterBStats) {
  const a = buildFeatureVector(fighterAStats);
  const b = buildFeatureVector(fighterBStats);

  const strikingDiff = a.striking - b.striking;
  const grapplingDiff = a.grappling - b.grappling;
  const finishDiff = a.finish - b.finish;
  const scheduleDiff = a.schedule - b.schedule;
  const recencyDiff =
    (normalizeSigned(fighterAStats.weightedSigDiffPerFight, 22) -
      normalizeSigned(fighterBStats.weightedSigDiffPerFight, 22)) /
    2;
  const activityDiff = activityScore(fighterAStats) - activityScore(fighterBStats);
  const agePrimeDiff =
    (agePrimeScore(fighterAStats.ageYears) - agePrimeScore(fighterBStats.ageYears)) / 2;
  const decisionSkillDiff =
    (safeNumber(fighterAStats.decisionWinPctWhenDecision, 0.5) - 0.5) -
    (safeNumber(fighterBStats.decisionWinPctWhenDecision, 0.5) - 0.5);
  const roundDurabilityDiff =
    (normalizeSigned(fighterAStats.lateRoundSigDiff, 24) -
      normalizeSigned(fighterBStats.lateRoundSigDiff, 24)) /
    2;
  const experienceDiff = ufcExperienceScore(fighterAStats) - ufcExperienceScore(fighterBStats);
  const veteranCraftDiff = veteranCraftScore(fighterAStats) - veteranCraftScore(fighterBStats);

  const fighterAUfcFights = safeNumber(fighterAStats.totalFights, 0);
  const fighterBUfcFights = safeNumber(fighterBStats.totalFights, 0);
  const aIsDebutant = fighterAUfcFights <= 2;
  const bIsDebutant = fighterBUfcFights <= 2;
  const aIsVet = fighterAUfcFights >= 12;
  const bIsVet = fighterBUfcFights >= 12;
  const debutantVsVetSwing = aIsDebutant && bIsVet ? -0.08 : bIsDebutant && aIsVet ? 0.08 : 0;

  const linearScore =
    0.26 * strikingDiff +
    0.18 * grapplingDiff +
    0.12 * finishDiff +
    0.11 * scheduleDiff +
    0.08 * recencyDiff +
    0.06 * activityDiff +
    0.06 * decisionSkillDiff +
    0.03 * agePrimeDiff +
    0.03 * roundDurabilityDiff +
    0.04 * experienceDiff +
    0.03 * veteranCraftDiff +
    debutantVsVetSwing;

  const rawProbability = clamp(logistic(linearScore * 2.9), 0.03, 0.97);
  const minFightSample = Math.min(
    safeNumber(fighterAStats.totalFights, 0),
    safeNumber(fighterBStats.totalFights, 0),
  );
  const sampleShrink = minFightSample < 4 ? 0.2 : minFightSample < 8 ? 0.12 : 0.06;
  const inactivityShrink =
    safeNumber(fighterAStats.daysSinceLastFight, 240) > 430 ||
    safeNumber(fighterBStats.daysSinceLastFight, 240) > 430
      ? 0.04
      : 0;
  const shrinkage = clamp(sampleShrink + inactivityShrink, 0.04, 0.28);
  const fighterAWinProbability = clamp(
    0.5 + (rawProbability - 0.5) * (1 - shrinkage),
    0.04,
    0.96,
  );
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
      veteranCraftDiff,
      debutantVsVetSwing,
      shrinkage,
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

function buildRoundFinishShares(fighterStats, opponentStats) {
  const quick = safeNumber(fighterStats.quickFinishWinRate, 0.2);
  const oppEarlyFragility =
    0.55 * safeNumber(opponentStats.koLossRate, 0.2) +
    0.45 * safeNumber(opponentStats.subLossRate, 0.15);
  const lateStability = clamp(0.5 + normalizeSigned(fighterStats.lateRoundSigDiff, 20), 0, 1);

  const round1 = clamp(0.22 + 0.42 * quick + 0.2 * oppEarlyFragility - 0.1 * lateStability, 0.1, 0.7);
  const round2 = clamp(0.24 + 0.25 * (1 - quick) + 0.15 * oppEarlyFragility, 0.15, 0.6);
  const round3Plus = clamp(1 - round1 - round2, 0.1, 0.7);
  const total = round1 + round2 + round3Plus;

  return {
    round1: round1 / total,
    round2: round2 / total,
    round3_plus: round3Plus / total,
  };
}

const METHOD_KEYS = ["ko_tko", "submission", "decision"];

function getFighterMethodDistributions(stats) {
  const ufcWins = Math.max(safeNumber(stats.wins, 0), 0);
  const ufcLosses = Math.max(safeNumber(stats.losses, 0), 0);
  const preUfcFights = Math.max(safeNumber(stats.preUfcFightCount, 0), 0);
  const hasReliableUfcWins = ufcWins >= 3;
  const hasReliableUfcLosses = ufcLosses >= 3;

  let win = {
    ko_tko: safeNumber(stats.koWinRate, 0.2),
    submission: safeNumber(stats.subWinRate, 0.1),
    decision: safeNumber(stats.decisionWinRate, 0.25),
  };
  let loss = {
    ko_tko: safeNumber(stats.koLossRate, 0.2),
    submission: safeNumber(stats.subLossRate, 0.15),
    decision: safeNumber(stats.decisionLossRate, 0.3),
  };

  if (!hasReliableUfcWins && preUfcFights > 0) {
    // UFC method sample is thin; use cautious proxy blend.
    const koProxy =
      0.55 * clamp(safeNumber(stats.sigLandedPerMin, 3.2) / 6, 0, 1) +
      0.45 * safeNumber(stats.koWinRate, 0.2);
    const subProxy =
      0.6 * clamp(safeNumber(stats.subAttemptsPerFight, 0.4) / 2.4, 0, 1) +
      0.4 * safeNumber(stats.subWinRate, 0.1);
    const decisionProxy = clamp(
      0.4 + 0.35 * safeNumber(stats.decisionAppearanceRate, 0.3) - 0.2 * safeNumber(stats.finishRate, 0.35),
      0.08,
      0.7,
    );
    win = {
      ko_tko: 0.6 * win.ko_tko + 0.4 * koProxy,
      submission: 0.6 * win.submission + 0.4 * subProxy,
      decision: 0.6 * win.decision + 0.4 * decisionProxy,
    };
  }

  if (!hasReliableUfcLosses && preUfcFights > 0) {
    const koLossProxy = clamp(1 - safeNumber(stats.strikingDefense, 0.52), 0.12, 0.58);
    const subLossProxy = clamp(1 - safeNumber(stats.takedownDefense, 0.6), 0.1, 0.5);
    const decisionLossProxy = clamp(0.2 + 0.6 * safeNumber(stats.decisionAppearanceRate, 0.3), 0.1, 0.7);
    loss = {
      ko_tko: 0.6 * loss.ko_tko + 0.4 * koLossProxy,
      submission: 0.6 * loss.submission + 0.4 * subLossProxy,
      decision: 0.6 * loss.decision + 0.4 * decisionLossProxy,
    };
  }

  function normalize(dist) {
    const total = METHOD_KEYS.reduce((sum, key) => sum + Math.max(safeNumber(dist[key], 0), 0.0001), 0);
    return {
      ko_tko: Math.max(safeNumber(dist.ko_tko, 0), 0.0001) / total,
      submission: Math.max(safeNumber(dist.submission, 0), 0.0001) / total,
      decision: Math.max(safeNumber(dist.decision, 0), 0.0001) / total,
    };
  }

  return {
    win: normalize(win),
    loss: normalize(loss),
    source: hasReliableUfcWins && hasReliableUfcLosses ? "ufc-primary" : "ufc-with-career-fallback",
  };
}

function determineFavoriteUnderdog({
  fighterAName,
  fighterBName,
  marketA,
  marketB,
  modelA,
  modelB,
}) {
  if (Number.isFinite(marketA) && Number.isFinite(marketB)) {
    if (marketA >= marketB) {
      return {
        favoriteSide: "fighterA",
        underdogSide: "fighterB",
        favoriteName: fighterAName,
        underdogName: fighterBName,
        source: "market",
      };
    }
    return {
      favoriteSide: "fighterB",
      underdogSide: "fighterA",
      favoriteName: fighterBName,
      underdogName: fighterAName,
      source: "market",
    };
  }

  if (modelA >= modelB) {
    return {
      favoriteSide: "fighterA",
      underdogSide: "fighterB",
      favoriteName: fighterAName,
      underdogName: fighterBName,
      source: "model",
    };
  }
  return {
    favoriteSide: "fighterB",
    underdogSide: "fighterA",
    favoriteName: fighterBName,
    underdogName: fighterAName,
    source: "model",
  };
}

function buildMethodAlignment({
  favoriteStats,
  underdogStats,
  favoriteName,
  underdogName,
}) {
  const favoriteDist = getFighterMethodDistributions(favoriteStats);
  const underdogDist = getFighterMethodDistributions(underdogStats);

  const alignments = METHOD_KEYS.map((method) => {
    const favoriteWinRate = favoriteDist.win[method];
    const underdogLossRate = underdogDist.loss[method];
    const score = favoriteWinRate * underdogLossRate;
    const linesUp = score >= 0.14 || (favoriteWinRate >= 0.38 && underdogLossRate >= 0.34);
    return {
      method,
      favoriteWinRate,
      underdogLossRate,
      alignmentScore: score,
      linesUp,
    };
  }).sort((left, right) => right.alignmentScore - left.alignmentScore);

  return {
    favoriteName,
    underdogName,
    source:
      favoriteDist.source === "ufc-primary" && underdogDist.source === "ufc-primary"
        ? "ufc-primary"
        : "ufc-plus-career-fallback",
    alignments,
  };
}

function methodLabel(method) {
  if (method === "ko_tko") return "KO/TKO";
  if (method === "submission") return "submission";
  if (method === "decision") return "decision";
  return method;
}

function roundLabel(roundKey) {
  if (roundKey === "round1") return "Round 1";
  if (roundKey === "round2") return "Round 2";
  return "Round 3+";
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
  return clamp(winProbability * profitIfWin - (1 - winProbability) * loseAmount, -0.8, 0.8);
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
  const baseRoundA = buildRoundFinishShares(fighterAStats, fighterBStats);
  const baseRoundB = buildRoundFinishShares(fighterBStats, fighterAStats);

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

  function drawRound(roundShares) {
    const roll = Math.random();
    if (roll < roundShares.round1) return "round1";
    if (roll < roundShares.round1 + roundShares.round2) return "round2";
    return "round3_plus";
  }

  let aWins = 0;
  const methodTotals = {
    fighterA: { ko_tko: 0, submission: 0, decision: 0 },
    fighterB: { ko_tko: 0, submission: 0, decision: 0 },
  };
  const roundTotals = {
    fighterA: { round1: 0, round2: 0, round3_plus: 0, decision: 0 },
    fighterB: { round1: 0, round2: 0, round3_plus: 0, decision: 0 },
  };

  for (let i = 0; i < simulations; i += 1) {
    const perturbation = randomStandardNormal() * sigma;
    const pA = clamp(baseWinProbabilityA + perturbation, 0.01, 0.99);
    const aWinsThisRun = Math.random() < pA;
    if (aWinsThisRun) {
      aWins += 1;
      const method = drawMethod(baseCondA);
      methodTotals.fighterA[method] += 1;
      if (method === "decision") {
        roundTotals.fighterA.decision += 1;
      } else {
        const round = drawRound(baseRoundA);
        roundTotals.fighterA[round] += 1;
      }
    } else {
      const method = drawMethod(baseCondB);
      methodTotals.fighterB[method] += 1;
      if (method === "decision") {
        roundTotals.fighterB.decision += 1;
      } else {
        const round = drawRound(baseRoundB);
        roundTotals.fighterB[round] += 1;
      }
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
    roundProbabilities: {
      fighterA: {
        round1: roundTotals.fighterA.round1 / simulations,
        round2: roundTotals.fighterA.round2 / simulations,
        round3_plus: roundTotals.fighterA.round3_plus / simulations,
        decision: roundTotals.fighterA.decision / simulations,
      },
      fighterB: {
        round1: roundTotals.fighterB.round1 / simulations,
        round2: roundTotals.fighterB.round2 / simulations,
        round3_plus: roundTotals.fighterB.round3_plus / simulations,
        decision: roundTotals.fighterB.decision / simulations,
      },
      fightTotal: {
        round1: (roundTotals.fighterA.round1 + roundTotals.fighterB.round1) / simulations,
        round2: (roundTotals.fighterA.round2 + roundTotals.fighterB.round2) / simulations,
        round3_plus:
          (roundTotals.fighterA.round3_plus + roundTotals.fighterB.round3_plus) /
          simulations,
        decision: (roundTotals.fighterA.decision + roundTotals.fighterB.decision) / simulations,
      },
    },
    uncertaintySigma: sigma,
  };
}

function formatPct(value) {
  if (!Number.isFinite(value)) return "N/A";
  return `${(value * 100).toFixed(1)}%`;
}

function buildValueBlurb({
  likelyWinnerName,
  likelyWinnerProbability,
  likelyMethodKey,
  likelyMethodGivenWin,
  likelyRoundKey,
  likelyRoundShare,
  marketProbability,
  ev,
  methodAlignment,
}) {
  if (!likelyWinnerName || !Number.isFinite(likelyWinnerProbability)) return null;

  const marketSnippet = Number.isFinite(marketProbability)
    ? `market implies ${formatPct(marketProbability)}`
    : "market line unavailable";
  const evSnippet = Number.isFinite(ev) ? `estimated ROI ${formatPct(ev)}` : "ROI not estimated";

  const methodScript = `Most likely path is ${methodLabel(likelyMethodKey)} (${formatPct(
    likelyMethodGivenWin,
  )} of ${likelyWinnerName}'s wins).`;

  const roundScript =
    likelyMethodKey === "decision"
      ? `Model expects this to hit the cards at a high clip (${formatPct(likelyRoundShare)}).`
      : `If it ends inside the distance, timing clusters around ${roundLabel(
          likelyRoundKey,
        )} (${formatPct(likelyRoundShare)}).`;

  const alignedMethods = (methodAlignment?.alignments || []).filter((entry) => entry.linesUp);
  const alignmentScript = alignedMethods.length
    ? `Favorite-to-underdog method overlap lines up on ${alignedMethods
        .slice(0, 2)
        .map(
          (entry) =>
            `${methodLabel(entry.method)} (fav wins ${formatPct(
              entry.favoriteWinRate,
            )}, dog loses ${formatPct(entry.underdogLossRate)})`,
        )
        .join(" and ")}.`
    : "No strong method-overlap flag from favorite-win vs underdog-loss UFC tendencies.";

  const sourceScript =
    methodAlignment?.source === "ufc-primary"
      ? "Method matchup source: UFC fights only."
      : "Method matchup source: UFC-first, with pre-UFC fallback only where UFC method samples are thin.";

  return `${likelyWinnerName} is projected to win ${formatPct(
    likelyWinnerProbability,
  )} (${marketSnippet}, ${evSnippet}). ${methodScript} ${roundScript} ${alignmentScript} ${sourceScript}`;
}

function projectFight(fight, marketOdds) {
  const fighterAStats = fight.fighterA.stats || {};
  const fighterBStats = fight.fighterB.stats || {};
  const fighterAName = fight.fighterA.name;
  const fighterBName = fight.fighterB.name;

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
  });

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

  const favoriteContext = determineFavoriteUnderdog({
    fighterAName,
    fighterBName,
    marketA,
    marketB,
    modelA: simulation.fighterAWinProbability,
    modelB: simulation.fighterBWinProbability,
  });
  const favoriteStats =
    favoriteContext.favoriteSide === "fighterA" ? fighterAStats : fighterBStats;
  const underdogStats =
    favoriteContext.underdogSide === "fighterA" ? fighterAStats : fighterBStats;
  const methodAlignment = buildMethodAlignment({
    favoriteStats,
    underdogStats,
    favoriteName: favoriteContext.favoriteName,
    underdogName: favoriteContext.underdogName,
  });

  const fallbackSide =
    simulation.fighterAWinProbability >= simulation.fighterBWinProbability ? "fighterA" : "fighterB";
  const blurbSide = bestValue?.side || fallbackSide;
  const likelyWinnerProbability =
    blurbSide === "fighterA"
      ? simulation.fighterAWinProbability
      : simulation.fighterBWinProbability;
  const likelyWinnerName = blurbSide === "fighterA" ? fighterAName : fighterBName;
  const blurbMarketProbability = blurbSide === "fighterA" ? marketA : marketB;
  const blurbEv = blurbSide === "fighterA" ? fighterAEv : fighterBEv;
  const winnerMethodDistribution =
    blurbSide === "fighterA"
      ? simulation.methodProbabilities.fighterA
      : simulation.methodProbabilities.fighterB;
  const winnerRoundDistribution =
    blurbSide === "fighterA"
      ? simulation.roundProbabilities.fighterA
      : simulation.roundProbabilities.fighterB;
  const likelyMethodKey = Object.entries(winnerMethodDistribution).sort(
    (left, right) => right[1] - left[1],
  )[0]?.[0] || "decision";
  const likelyMethodGivenWin = clamp(
    safeNumber(winnerMethodDistribution[likelyMethodKey], 0) /
      Math.max(likelyWinnerProbability, 0.0001),
    0,
    1,
  );
  const finishRoundEntries = [
    ["round1", safeNumber(winnerRoundDistribution.round1, 0)],
    ["round2", safeNumber(winnerRoundDistribution.round2, 0)],
    ["round3_plus", safeNumber(winnerRoundDistribution.round3_plus, 0)],
  ].sort((left, right) => right[1] - left[1]);
  const likelyRoundKey = likelyMethodKey === "decision" ? "decision" : finishRoundEntries[0][0];
  const likelyRoundShare =
    likelyMethodKey === "decision"
      ? safeNumber(winnerRoundDistribution.decision, 0)
      : safeNumber(finishRoundEntries[0][1], 0);
  const blurb = buildValueBlurb({
    likelyWinnerName,
    likelyWinnerProbability,
    likelyMethodKey,
    likelyMethodGivenWin,
    likelyRoundKey,
    likelyRoundShare,
    marketProbability: blurbMarketProbability,
    ev: blurbEv,
    methodAlignment,
  });
  const finalBlurb =
    blurb ||
    `${likelyWinnerName} has a model lean based on aggregate striking, grappling, and experience profile.`;
  const bestValueModelProbability = bestValue
    ? bestValue.side === "fighterA"
      ? simulation.fighterAWinProbability
      : simulation.fighterBWinProbability
    : null;
  const bestValueQualified = Number.isFinite(bestValueModelProbability)
    ? bestValueModelProbability >= 0.4
    : false;

  return {
    model: {
      winProbabilities: {
        fighterA: simulation.fighterAWinProbability,
        fighterB: simulation.fighterBWinProbability,
      },
      methodProbabilities: simulation.methodProbabilities,
      roundProbabilities: simulation.roundProbabilities,
      methodAlignment,
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
      bestValueModelProbability,
      bestValueQualified,
    },
    insightBlurb: finalBlurb,
  };
}

module.exports = {
  projectFight,
};

