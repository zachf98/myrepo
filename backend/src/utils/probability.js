function americanToImpliedProbability(odds) {
  if (typeof odds !== "number" || Number.isNaN(odds) || odds === 0) {
    return null;
  }

  if (odds < 0) {
    return Math.abs(odds) / (Math.abs(odds) + 100);
  }

  return 100 / (odds + 100);
}

function normalizeTwoWayProbabilities(pA, pB) {
  if (typeof pA !== "number" || typeof pB !== "number") {
    return { pA: null, pB: null, vig: null };
  }

  const total = pA + pB;
  if (total <= 0) {
    return { pA: null, pB: null, vig: null };
  }

  return {
    pA: pA / total,
    pB: pB / total,
    vig: total - 1,
  };
}

function clamp(value, min = 0, max = 1) {
  if (Number.isNaN(value)) {
    return min;
  }
  return Math.max(min, Math.min(max, value));
}

module.exports = {
  americanToImpliedProbability,
  normalizeTwoWayProbabilities,
  clamp,
};
