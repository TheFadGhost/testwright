/** Small math helpers for the Jest corpus app. */

function add(a, b) {
  if (typeof a !== "number" || typeof b !== "number") {
    throw new TypeError("add expects numbers");
  }
  return a + b;
}

function mul(a, b) {
  if (a === 0 || b === 0) return 0;
  return a * b;
}

function sumAll(values) {
  let total = 0;
  for (const v of values) {
    total += v;
  }
  return total;
}

module.exports = { add, mul, sumAll };
