/** Statistics helpers without existing tests (corpus target). */

function mean(values) {
  if (!Array.isArray(values) || values.length === 0) {
    throw new RangeError("mean needs a non-empty array");
  }
  return sumAll(values) / values.length;
}

function variance(values) {
  const m = mean(values);
  return sumAll(values.map((v) => (v - m) * (v - m))) / values.length;
}

function sumAll(values) {
  let total = 0;
  for (const v of values) {
    total += v;
  }
  return total;
}

module.exports = { mean, variance, sumAll };
