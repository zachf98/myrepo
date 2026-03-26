function normalizeName(name) {
  return String(name || "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function levenshteinDistance(a, b) {
  const s = normalizeName(a);
  const t = normalizeName(b);
  const rows = s.length + 1;
  const cols = t.length + 1;

  const matrix = Array.from({ length: rows }, () => Array(cols).fill(0));

  for (let i = 0; i < rows; i += 1) matrix[i][0] = i;
  for (let j = 0; j < cols; j += 1) matrix[0][j] = j;

  for (let i = 1; i < rows; i += 1) {
    for (let j = 1; j < cols; j += 1) {
      const cost = s[i - 1] === t[j - 1] ? 0 : 1;
      matrix[i][j] = Math.min(
        matrix[i - 1][j] + 1,
        matrix[i][j - 1] + 1,
        matrix[i - 1][j - 1] + cost,
      );
    }
  }

  return matrix[rows - 1][cols - 1];
}

function similarityScore(a, b) {
  const s = normalizeName(a);
  const t = normalizeName(b);
  if (!s || !t) return 0;
  if (s === t) return 1;
  if (s.includes(t) || t.includes(s)) return 0.9;
  const distance = levenshteinDistance(s, t);
  const maxLen = Math.max(s.length, t.length);
  return maxLen ? 1 - distance / maxLen : 0;
}

module.exports = {
  normalizeName,
  similarityScore,
};
